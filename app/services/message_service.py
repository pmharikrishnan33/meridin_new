"""
Message service.

Responsible for:

- message understanding
- command detection
- conversation/session management
- inbound message persistence
- intent routing
- outbound message persistence
- WhatsApp message idempotency
- outbound delivery status updates

Important:

This service does NOT send messages to WhatsApp.

The workflow is:

    MessageService
        ↓
    create outbound message
        ↓
    delivery_status = pending
        ↓
    webhook.py / WhatsAppSender
        ↓
    Meta WhatsApp API
        ↓
    MessageService.mark_outbound_sent()
        OR
    MessageService.mark_outbound_failed()
"""

from dataclasses import dataclass
from typing import Any, Dict
from uuid import uuid4

from app.conversation.session import (
    ConversationSession,
)

from app.conversation.manager import (
    conversation_manager,
)

from app.ml.entity_extractor import (
    entity_extractor,
)

from app.ml.intent_classifier import (
    intent_classifier,
)

from app.ml.preprocessor import (
    preprocessor,
)

from app.models.schemas import (
    BotResponse,
    EntityType,
    ExtractedEntity,
    IntentType,
    Message,
    MessageDirection,
    MessageType,
    MessageUnderstanding,
)

from app.routing.intent_router import (
    intent_router,
)


DEFAULT_TENANT_SETTINGS: Dict[str, Any] = {
    "welcome_message": (
        "Welcome! How can I help you today?"
    ),

    "fallback_message": (
        "I didn't understand that. "
        "Could you please rephrase?"
    ),

    "feature_flags": {
        "enable_ai_responses": True,
        "enable_product_recommendations": True,
        "enable_order_tracking": False,
        "enable_returns": False,
        "enable_cancellation": False,
        "enable_human_handoff": True,
        "enable_analytics": True,

        # Product search itself uses the WhatsApp
        # response limit enforced by the sender.
        "max_products_per_response": 5,
    },
}


@dataclass
class ProcessedMessage:
    """
    Result returned after processing one inbound
    WhatsApp message.
    """

    conversation_id: str

    understanding: MessageUnderstanding

    response: BotResponse

    outbound_message_id: str | None = None


class DuplicateWhatsAppMessage(Exception):
    """
    Raised when Meta sends the same WhatsApp
    message more than once.
    """

    def __init__(
        self,
        whatsapp_message_id: str,
    ) -> None:

        self.whatsapp_message_id = (
            whatsapp_message_id
        )

        super().__init__(
            "WhatsApp message already "
            "processed: "
            f"{whatsapp_message_id}"
        )


class MessageService:
    """
    Coordinates:

        normalization
            ↓
        command detection
            ↓
        ML understanding
            ↓
        conversation state
            ↓
        intent routing
            ↓
        response persistence
            ↓
        delivery status update

    MessageService does NOT communicate directly
    with Meta WhatsApp API.
    """

    def __init__(self) -> None:

        self._conversation_keys: (
            Dict[
                tuple[str, str],
                str,
            ]
        ) = {}

    # =========================================================
    # COMMAND EXTRACTION
    # =========================================================

    @staticmethod
    def extract_command(
        text: str,
    ) -> str | None:
        """
        Extract an internal command from a normalized
        WhatsApp interactive reply.

        Example:

            __COMMAND__:show_more

        becomes:

            show_more

        Normal customer messages return None.
        """

        if not text:
            return None

        prefix = "__COMMAND__:"

        if not text.startswith(prefix):
            return None

        command = text[len(prefix):].strip()

        return command or None

    # =========================================================
    # MESSAGE UNDERSTANDING
    # =========================================================

    def understand(
        self,
        text: str,
    ) -> MessageUnderstanding:
        """
        Run preprocessing, intent classification,
        and entity extraction.
        """

        if not text or not text.strip():
            raise ValueError(
                "Message text must not be empty."
            )

        preprocessed = (
            preprocessor.process(text)
        )

        ml_text = (
            preprocessed.normalized
        )

        prediction = (
            intent_classifier.predict(
                ml_text
            )
        )

        extraction = (
            entity_extractor.extract(
                ml_text,
                intent=prediction.intent.value,
            )
        )

        return MessageUnderstanding(
            original_text=text,
            normalized_text=ml_text,
            intent=prediction.intent,
            intent_confidence=(
                prediction.confidence
            ),
            entities=extraction.entities,
        )

    # =========================================================
    # SESSION
    # =========================================================

    async def _get_or_create_session(
        self,
        tenant_id: str,
        user_id: str,
    ) -> ConversationSession:
        """
        Get or create a conversation session.

        MongoDB-backed ConversationManager is the
        persistent source of truth.
        """

        key = (
            tenant_id,
            user_id,
        )

        conversation_id = (
            self._conversation_keys.get(key)
        )

        if conversation_id:

            existing = (
                conversation_manager.get_session(
                    conversation_id
                )
            )

            if existing:
                return existing

        # -----------------------------------------------------
        # CUSTOMER
        # -----------------------------------------------------

        customer = (
            await conversation_manager
            .get_or_create_customer(
                tenant_id=tenant_id,
                phone_number=user_id,
                wa_id=user_id,
            )
        )

        # -----------------------------------------------------
        # CONVERSATION
        # -----------------------------------------------------

        session = (
            await conversation_manager
            .get_or_create_conversation(
                tenant_id=tenant_id,
                customer_id=customer.id,
                customer_phone=user_id,
            )
        )

        self._conversation_keys[
            key
        ] = session.conversation_id

        return session

    # =========================================================
    # TENANT SETTINGS
    # =========================================================

    @staticmethod
    def _merge_tenant_settings(
        tenant_settings: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        """
        Merge tenant settings with safe defaults.
        """

        tenant_settings = (
            tenant_settings or {}
        )

        return {
            **DEFAULT_TENANT_SETTINGS,

            **tenant_settings,

            "feature_flags": {
                **DEFAULT_TENANT_SETTINGS[
                    "feature_flags"
                ],

                **tenant_settings.get(
                    "feature_flags",
                    {},
                ),
            },
        }

    # =========================================================
    # OUTBOUND DELIVERY STATUS
    # =========================================================

    async def mark_outbound_sent(
        self,
        outbound_message_id: str,
        whatsapp_message_id: str | None = None,
    ) -> None:
        """
        Mark an outbound message as successfully sent.

        This method must be called AFTER Meta accepts
        the outbound WhatsApp message.

        Example workflow:

            MessageService.process()
                ↓
            pending
                ↓
            WhatsAppSender.send_bot_response()
                ↓
            Meta success
                ↓
            mark_outbound_sent()
        """

        if not outbound_message_id:
            raise ValueError(
                "outbound_message_id is required"
            )

        await (
            conversation_manager
            .update_message_delivery(
                outbound_message_id,
                status="sent",
                whatsapp_message_id=(
                    whatsapp_message_id
                ),
            )
        )

    async def mark_outbound_failed(
        self,
        outbound_message_id: str,
        error: str,
    ) -> None:
        """
        Mark an outbound message as failed.

        This method must be called when the WhatsApp
        provider rejects the message or the send
        operation raises an exception.
        """

        if not outbound_message_id:
            raise ValueError(
                "outbound_message_id is required"
            )

        if not error:
            error = "Unknown WhatsApp delivery error"

        await (
            conversation_manager
            .update_message_delivery(
                outbound_message_id,
                status="failed",
                error=error[:2000],
            )
        )

    # =========================================================
    # MAIN PROCESS
    # =========================================================

    async def process(
        self,
        *,
        tenant_id: str,
        user_id: str,
        text: str,
        tenant_settings: Dict[str, Any] | None = None,
        whatsapp_message_id: str | None = None,
        message_type: MessageType = (
            MessageType.TEXT
        ),
        inbound_metadata: Dict[str, Any] | None = None,
    ) -> ProcessedMessage:
        """
        Process one inbound WhatsApp message.

        A WhatsApp message is processed exactly once
        when its WhatsApp message ID is available.
        """

        if not text or not text.strip():
            raise ValueError(
                "Message text must not be empty."
            )

        # =====================================================
        # IDEMPOTENCY
        # =====================================================

        if whatsapp_message_id:

            existing = (
                await conversation_manager
                .get_message_by_whatsapp_id(
                    tenant_id=tenant_id,
                    whatsapp_message_id=(
                        whatsapp_message_id
                    ),
                )
            )

            if existing:
                raise DuplicateWhatsAppMessage(
                    whatsapp_message_id
                )

        # =====================================================
        # COMMAND
        # =====================================================

        command = (
            self.extract_command(text)
        )

        if command:

            return await self.process_command(
                tenant_id=tenant_id,
                user_id=user_id,
                command=command,
                whatsapp_message_id=(
                    whatsapp_message_id
                ),
                tenant_settings=(
                    tenant_settings
                ),
                message_type=message_type,
                inbound_metadata=(
                    inbound_metadata
                ),
            )

        # =====================================================
        # NORMAL TEXT → ML
        # =====================================================

        understanding = (
            self.understand(text)
        )

        # =====================================================
        # SESSION
        # =====================================================

        session = (
            await self._get_or_create_session(
                tenant_id,
                user_id,
            )
        )

        # =====================================================
        # REPLY CONTEXT
        # =====================================================

        reply_product = (
            session.resolve_reply_context(
                text
            )
        )

        if reply_product:

            understanding.entities.append(
                ExtractedEntity(
                    entity_type=(
                        EntityType.PRODUCT
                    ),
                    value=reply_product,
                    confidence=1.0,
                    normalized_value=(
                        reply_product
                    ),
                )
            )

        # =====================================================
        # INBOUND MESSAGE
        # =====================================================

        inbound_msg = Message(
            id=str(uuid4()),

            tenant_id=tenant_id,

            conversation_id=(
                session.conversation_id
            ),

            customer_id=(
                session.customer_id
            ),

            whatsapp_message_id=(
                whatsapp_message_id
            ),

            direction=(
                MessageDirection.INBOUND
            ),

            message_type=message_type,

            text=text,

            intent=(
                understanding.intent
            ),

            intent_confidence=(
                understanding.intent_confidence
            ),

            entities={
                entity.entity_type.value:
                    (
                        entity.normalized_value
                        or entity.value
                    )
                for entity
                in understanding.entities
            },

            metadata=(
                inbound_metadata or {}
            ),
        )

        await (
            conversation_manager
            .save_message(
                inbound_msg
            )
        )

        # =====================================================
        # SESSION INBOUND
        # =====================================================

        session.add_message(
            message_id=inbound_msg.id,

            direction=(
                MessageDirection.INBOUND
            ),

            text=text,

            intent=(
                understanding.intent
            ),

            intent_confidence=(
                understanding.intent_confidence
            ),

            entities=(
                understanding.entities
            ),

            metadata=(
                {
                    "reply_context_product":
                        reply_product
                }
                if reply_product
                else None
            ),
        )

        session.update_context_from_understanding(
            understanding
        )

        # =====================================================
        # SETTINGS
        # =====================================================

        settings = (
            self._merge_tenant_settings(
                tenant_settings
            )
        )

        # =====================================================
        # ROUTING
        # =====================================================

        response = (
            await intent_router.route(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=settings,
                conversation_id=(
                    session.conversation_id
                ),
            )
        )

        # =====================================================
        # OUTBOUND MESSAGE
        # =====================================================

        outbound_msg = self._build_outbound_message(
            tenant_id=tenant_id,
            session=session,
            inbound_message=inbound_msg,
            response=response,
        )

        await (
            conversation_manager
            .save_message(
                outbound_msg
            )
        )

        # =====================================================
        # SESSION OUTBOUND
        # =====================================================

        session.add_message(
            message_id=outbound_msg.id,

            direction=(
                MessageDirection.OUTBOUND
            ),

            text=response.text or "",

            is_from_bot=True,

            bot_response_type=(
                response.response_type
            ),

            metadata={
                "outbound_message_id":
                    outbound_msg.id,
            },
        )

        await (
            conversation_manager
            .save_session(
                session
            )
        )

        # =====================================================
        # RESULT
        # =====================================================

        return ProcessedMessage(
            conversation_id=(
                session.conversation_id
            ),

            understanding=(
                understanding
            ),

            response=response,

            outbound_message_id=(
                outbound_msg.id
            ),
        )

    # =========================================================
    # OUTBOUND MESSAGE BUILDER
    # =========================================================

    @staticmethod
    def _build_outbound_message(
        *,
        tenant_id: str,
        session: ConversationSession,
        inbound_message: Message,
        response: BotResponse,
        pagination: bool = False,
    ) -> Message:
        """
        Build an outbound Message document.

        Delivery starts as 'pending'.

        It MUST be changed to 'sent' or 'failed'
        after WhatsApp delivery is attempted.
        """

        return Message(
            id=str(uuid4()),

            tenant_id=tenant_id,

            conversation_id=(
                session.conversation_id
            ),

            customer_id=(
                session.customer_id
            ),

            direction=(
                MessageDirection.OUTBOUND
            ),

            message_type=(
                MessageType.TEXT
            ),

            text=response.text or "",

            is_from_bot=True,

            bot_response_type=(
                response.response_type
            ),

            response_to_message_id=(
                inbound_message.id
            ),

            delivery_status="pending",

            metadata={
                "response_type":
                    response.response_type,

                "product_ids": [
                    product.product_id
                    for product
                    in response.products
                ],

                "source_message_id":
                    inbound_message.id,

                "pagination":
                    pagination,
            },
        )

    # =========================================================
    # COMMAND PROCESSING
    # =========================================================

    async def process_command(
        self,
        *,
        tenant_id: str,
        user_id: str,
        command: str,
        whatsapp_message_id: str | None,
        tenant_settings: Dict[str, Any] | None,
        message_type: MessageType,
        inbound_metadata: Dict[str, Any] | None,
    ) -> ProcessedMessage:
        """
        Process internal commands generated by
        WhatsApp interactive replies.

        Currently supported:

            show_more
        """

        command = command.strip().lower()

        # =====================================================
        # SESSION
        # =====================================================

        session = (
            await self._get_or_create_session(
                tenant_id,
                user_id,
            )
        )

        # =====================================================
        # COMMAND VALIDATION
        # =====================================================

        if command != "show_more":

            understanding = MessageUnderstanding(
                original_text=command,

                normalized_text=command,

                intent=(
                    IntentType.PAGINATION
                ),

                intent_confidence=1.0,

                entities=[],
            )

            response = BotResponse(
                response_type="text",

                text=(
                    "I couldn't process that "
                    "selection. Please try again."
                ),

                products=[],

                quick_replies=[],

                metadata={
                    "command": command,
                    "success": False,
                },
            )

        else:

            # =================================================
            # PAGINATION UNDERSTANDING
            # =================================================

            understanding = (
                MessageUnderstanding(
                    original_text=command,

                    normalized_text=command,

                    intent=(
                        IntentType.PAGINATION
                    ),

                    intent_confidence=1.0,

                    entities=[],
                )
            )

            # =================================================
            # SETTINGS
            # =================================================

            settings = (
                self._merge_tenant_settings(
                    tenant_settings
                )
            )

            # =================================================
            # PAGINATION ROUTER
            # =================================================

            response = (
                await intent_router.route(
                    understanding=(
                        understanding
                    ),

                    tenant_id=tenant_id,

                    tenant_settings=settings,

                    conversation_id=(
                        session.conversation_id
                    ),
                )
            )

        # =====================================================
        # SAVE INBOUND COMMAND
        # =====================================================

        inbound_msg = Message(
            id=str(uuid4()),

            tenant_id=tenant_id,

            conversation_id=(
                session.conversation_id
            ),

            customer_id=(
                session.customer_id
            ),

            whatsapp_message_id=(
                whatsapp_message_id
            ),

            direction=(
                MessageDirection.INBOUND
            ),

            message_type=message_type,

            text=command,

            intent=(
                understanding.intent
            ),

            intent_confidence=(
                understanding.intent_confidence
            ),

            entities={},

            metadata=(
                inbound_metadata or {}
            ),
        )

        await (
            conversation_manager
            .save_message(
                inbound_msg
            )
        )

        session.add_message(
            message_id=inbound_msg.id,

            direction=(
                MessageDirection.INBOUND
            ),

            text=command,

            intent=(
                understanding.intent
            ),

            intent_confidence=(
                understanding.intent_confidence
            ),

            entities=[],

            metadata=(
                inbound_metadata or {}
            ),
        )

        # =====================================================
        # SAVE OUTBOUND
        # =====================================================

        outbound_msg = (
            self._build_outbound_message(
                tenant_id=tenant_id,
                session=session,
                inbound_message=inbound_msg,
                response=response,
                pagination=(
                    command == "show_more"
                ),
            )
        )

        await (
            conversation_manager
            .save_message(
                outbound_msg
            )
        )

        # =====================================================
        # SESSION OUTBOUND
        # =====================================================

        session.add_message(
            message_id=outbound_msg.id,

            direction=(
                MessageDirection.OUTBOUND
            ),

            text=response.text or "",

            is_from_bot=True,

            bot_response_type=(
                response.response_type
            ),

            metadata={
                "pagination":
                    command == "show_more",

                "outbound_message_id":
                    outbound_msg.id,
            },
        )

        await (
            conversation_manager
            .save_session(
                session
            )
        )

        # =====================================================
        # RESULT
        # =====================================================

        return ProcessedMessage(
            conversation_id=(
                session.conversation_id
            ),

            understanding=(
                understanding
            ),

            response=response,

            outbound_message_id=(
                outbound_msg.id
            ),
        )


message_service = MessageService()