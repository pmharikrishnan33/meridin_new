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
from pymongo.errors import DuplicateKeyError

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

from app.services.product_service import product_service


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
        "max_products_per_response": 3,
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
    @staticmethod
    def _expected_provider_message_count(
        response: BotResponse,
    ) -> int:
        """
        Calculate how many WhatsApp provider messages
        are expected for one BotResponse.
        """

        count = 0

        if (
            response.response_type
            in {
                "product_list",
                "product_card",
            }
        ):
            count += len(
                response.products[:3]
            )

        elif response.text:
            count += 1

        if response.quick_replies:
            count += 1

        return count


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

    async def understand(
        self,
        text: str,
        *,
        use_synonyms: bool = True,
    ) -> MessageUnderstanding:
        """
        Understand one customer message.

        ML inference is explicitly executed outside the FastAPI
        event-loop thread.
        """

        if not text or not text.strip():
            raise ValueError(
                "Message text must not be empty."
            )

        preprocessed = preprocessor.process(
            text
        )

        ml_text = (
            preprocessed.vocabulary_matched
            if use_synonyms
            else preprocessed.normalized
        )

        prediction = (
            await intent_classifier.predict_async(
                ml_text
            )
        )

        extraction = (
            await entity_extractor.extract_async(
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

        settings = self._merge_tenant_settings(
            tenant_settings
        )

        use_synonyms = bool(
            settings.get(
                "feature_flags",
                {}
            ).get(
                "use_synonyms",
                True,
            )
        )

        understanding = await self.understand(
            text,
            use_synonyms=use_synonyms,
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

        try:
            await conversation_manager.save_message(
                inbound_msg
            )

        except DuplicateKeyError:

            if whatsapp_message_id:
                raise DuplicateWhatsAppMessage(
                    whatsapp_message_id
                )

            raise

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

        outbound_msg.metadata.update({
            "delivery_group_id": str(uuid4()),
            "expected_provider_messages": self._expected_provider_message_count(response),
        })

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
                "outbound_message_id": outbound_msg.id,
                "product_ids": [
                    product.product_id
                    for product in response.products
                ],
                "response_type": response.response_type,
                "delivery_group_id": outbound_msg.metadata.get("delivery_group_id"),
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

        Supported commands:

            search_again
            show_more

        Unknown commands are handled safely and do not
        reach the pagination router.
        """

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if not user_id:
            raise ValueError(
                "user_id is required"
            )

        if not command or not command.strip():
            raise ValueError(
                "command is required"
            )

        command = command.strip().lower()

        # =====================================================
        # SESSION
        # =====================================================

        session = await self._get_or_create_session(
            tenant_id,
            user_id,
        )

        # =====================================================
        # COMMAND VALIDATION / ROUTING
        # =====================================================

        if command == "search_again":

            # -------------------------------------------------
            # SEARCH AGAIN
            # -------------------------------------------------

            understanding = MessageUnderstanding(
                original_text=command,
                normalized_text=command,
                intent=IntentType.PRODUCT_SEARCH,
                intent_confidence=1.0,
                entities=[],
            )

            response = BotResponse(
                response_type="text",
                text=(
                    "Sure. Tell me what product, category, "
                    "colour, size, or price range you are "
                    "looking for."
                ),
                products=[],
                quick_replies=[],
                metadata={
                    "command": "search_again",
                    "reset_search": True,
                    "success": True,
                },
            )

            # Clear pending conversation state.
            session.clear_awaiting_entity()
            session.clear_awaiting_confirmation()

            # Clear previous search state.
            session.context.current_product = None
            session.context.current_category = None
            session.context.last_search_filters = {}
            session.context.last_search_results = []

            session.context.active_search_key = None
            session.context.active_search_offset = 0
            session.context.active_search_total = 0
            session.context.active_search_query = None
            session.context.active_search_filters = {}
            session.context.active_search_results = []
            session.context.active_search_page = 1

        elif command == "show_more":

            understanding = MessageUnderstanding(
                original_text=command,
                normalized_text=command,
                intent=IntentType.PAGINATION,
                intent_confidence=1.0,
                entities=[],
            )

            settings = self._merge_tenant_settings(tenant_settings)

            response = await intent_router.route(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=settings,
                conversation_id=session.conversation_id,
            )

        elif command in {"product_details", "view_all_sizes", "similar_products"}:

            current_product = session.context.current_product

            if not current_product:
                understanding = MessageUnderstanding(
                    original_text=command,
                    normalized_text=command,
                    intent=IntentType.PRODUCT_INQUIRY,
                    intent_confidence=1.0,
                    entities=[],
                )
                response = BotResponse(
                    response_type="text",
                    text="Please select a product first.",
                    products=[],
                    quick_replies=[
                        {"label": "Search Again", "value": "__COMMAND__:search_again"}
                    ],
                    metadata={"command": command, "success": False},
                )
            elif command == "product_details":
                understanding = MessageUnderstanding(
                    original_text=command,
                    normalized_text=command,
                    intent=IntentType.PRODUCT_INQUIRY,
                    intent_confidence=1.0,
                    entities=[
                        ExtractedEntity(
                            entity_type=EntityType.PRODUCT,
                            value=current_product,
                            confidence=1.0,
                            normalized_value=current_product,
                        )
                    ],
                )
                settings = self._merge_tenant_settings(tenant_settings)
                response = await intent_router.route(
                    understanding=understanding,
                    tenant_id=tenant_id,
                    tenant_settings=settings,
                    conversation_id=session.conversation_id,
                )
            elif command == "view_all_sizes":
                understanding = MessageUnderstanding(
                    original_text=command,
                    normalized_text=command,
                    intent=IntentType.AVAILABILITY,
                    intent_confidence=1.0,
                    entities=[
                        ExtractedEntity(
                            entity_type=EntityType.PRODUCT,
                            value=current_product,
                            confidence=1.0,
                            normalized_value=current_product,
                        )
                    ],
                )
                availability = await product_service.check_availability(
                    tenant_id=tenant_id,
                    product_id=current_product,
                )
                sizes = availability.get("available_sizes", [])
                product_name = availability.get("product_name", current_product)
                response = BotResponse(
                    response_type="text",
                    text=(
                        f"Available sizes for {product_name}: " + ", ".join(sizes)
                        if sizes else f"No sizes are currently in stock for {product_name}."
                    ),
                    products=[],
                    quick_replies=[
                        {"label": "View Product", "value": "__COMMAND__:product_details"},
                        {"label": "Search Again", "value": "__COMMAND__:search_again"},
                    ],
                    metadata={"command": command, "product_id": current_product},
                )
            else:
                product = await product_service.get_product_by_reference(
                    tenant_id=tenant_id,
                    reference=current_product,
                )
                if not product:
                    response = BotResponse(
                        response_type="text",
                        text="I couldn't find similar products right now.",
                        products=[],
                        quick_replies=[{"label": "Search Again", "value": "__COMMAND__:search_again"}],
                        metadata={"command": command, "success": False},
                    )
                else:
                    from app.models.schemas import ProductSearchFilters
                    filters = ProductSearchFilters(
                        category=product.category,
                        type=product.type,
                        brand=product.brand,
                        limit=5,
                        offset=0,
                    )
                    similar = await product_service.search_products(
                        tenant_id=tenant_id,
                        filters=filters,
                    )
                    similar = [item for item in similar if item.id != product.id][:5]
                    response = BotResponse(
                        response_type="product_list" if similar else "text",
                        text=(
                            "Here are some similar products:"
                            if similar
                            else "I couldn't find similar products right now."
                        ),
                        products=[
                            product_service.product_to_response(item)
                            for item in similar
                        ],
                        quick_replies=[{"label": "Search Again", "value": "__COMMAND__:search_again"}],
                        metadata={"command": command, "source_product_id": product.id},
                    )
                    if similar:
                        session.context.current_product = similar[0].id

        else:

            understanding = MessageUnderstanding(
                original_text=command,
                normalized_text=command,
                intent=IntentType.UNKNOWN,
                intent_confidence=1.0,
                entities=[],
            )

            response = BotResponse(
                response_type="text",
                text="I couldn't process that selection. Please try again.",
                products=[],
                quick_replies=[
                    {"label": "Search Again", "value": "__COMMAND__:search_again"}
                ],
                metadata={
                    "command": command,
                    "success": False,
                    "unsupported_command": True,
                },
            )

        # =====================================================
        # SAVE INBOUND COMMAND
        # =====================================================

        inbound_msg = Message(
            id=str(uuid4()),

            tenant_id=tenant_id,

            conversation_id=session.conversation_id,

            customer_id=session.customer_id,

            whatsapp_message_id=whatsapp_message_id,

            direction=MessageDirection.INBOUND,

            message_type=message_type,

            text=command,

            intent=understanding.intent,

            intent_confidence=(
                understanding.intent_confidence
            ),

            entities={},

            metadata=inbound_metadata or {},
        )

        try:

            await conversation_manager.save_message(
                inbound_msg
            )

        except DuplicateKeyError:

            if whatsapp_message_id:
                raise DuplicateWhatsAppMessage(
                    whatsapp_message_id
                )

            raise

        # =====================================================
        # SESSION INBOUND
        # =====================================================

        session.add_message(
            message_id=inbound_msg.id,

            direction=MessageDirection.INBOUND,

            text=command,

            intent=understanding.intent,

            intent_confidence=(
                understanding.intent_confidence
            ),

            entities=[],

            metadata=inbound_metadata or {},
        )

        # =====================================================
        # SAVE OUTBOUND
        # =====================================================

        delivery_group_id = str(uuid4())

        outbound_msg = self._build_outbound_message(
            tenant_id=tenant_id,
            session=session,
            inbound_message=inbound_msg,
            response=response,
        )

        outbound_msg.metadata = {
            **(outbound_msg.metadata or {}),

            "delivery_group_id": (
                delivery_group_id
            ),

            "expected_provider_messages": (
                self._expected_provider_message_count(
                    response
                )
            ),

            "command": command,
        }

        await conversation_manager.save_message(
            outbound_msg
        )

        # =====================================================
        # SESSION OUTBOUND
        # =====================================================

        session.add_message(
            message_id=outbound_msg.id,
            direction=MessageDirection.OUTBOUND,
            text=response.text or "",
            is_from_bot=True,
            bot_response_type=response.response_type,
            metadata={
                "outbound_message_id": outbound_msg.id,
                "product_ids": [
                    product.product_id
                    for product in response.products
                ],
                "response_type": response.response_type,
                "pagination": bool(
                    response.metadata.get("pagination", False)
                ),
            },
        )

        # =====================================================
        # SAVE SESSION
        # =====================================================

        await conversation_manager.save_session(
            session
        )

        # =====================================================
        # RESULT
        # =====================================================

        return ProcessedMessage(
            conversation_id=session.conversation_id,

            understanding=understanding,

            response=response,

            outbound_message_id=outbound_msg.id,
        )

message_service = MessageService()
