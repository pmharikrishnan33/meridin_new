from dataclasses import dataclass
from typing import Any, Dict
from uuid import uuid4

from app.conversation.session import ConversationSession
from app.conversation.manager import conversation_manager

from app.ml.entity_extractor import entity_extractor
from app.ml.intent_classifier import intent_classifier
from app.ml.preprocessor import preprocessor

from app.models.schemas import (
    BotResponse,
    EntityType,
    ExtractedEntity,
    Message,
    MessageDirection,
    MessageType,
    MessageUnderstanding,
    IntentType,
)

from app.routing.intent_router import intent_router


DEFAULT_TENANT_SETTINGS: Dict[str, Any] = {
    "welcome_message": "Welcome! How can I help you today?",
    "fallback_message": "I didn't understand that. Could you please rephrase?",
    "feature_flags": {
        "enable_ai_responses": True,
        "enable_product_recommendations": True,
        "enable_order_tracking": False,
        "enable_returns": False,
        "enable_cancellation": False,
        "enable_human_handoff": True,
        "enable_analytics": True,
        "max_products_per_response": 5,
    },
}

@staticmethod
def extract_command(
    text: str,
) -> str | None:

    prefix = "__COMMAND__:"

    if not text.startswith(prefix):
        return None

    command = text[
        len(prefix):
    ].strip()

    return command or None


@dataclass
class ProcessedMessage:
    conversation_id: str
    understanding: MessageUnderstanding
    response: BotResponse
    outbound_message_id: str | None = None

class DuplicateWhatsAppMessage(Exception):
    """
    Raised when Meta sends the same WhatsApp message more than once.
    """

    def __init__(
        self,
        whatsapp_message_id: str,
    ):
        self.whatsapp_message_id = (
            whatsapp_message_id
        )

        super().__init__(
            "WhatsApp message already processed: "
            f"{whatsapp_message_id}"
        )

class MessageService:
    """Coordinates normalization, ML understanding, session state, and routing."""

    def __init__(self) -> None:
        self._conversation_keys: Dict[tuple[str, str], str] = {}

    def understand(
        self,
        text: str,
    ) -> MessageUnderstanding:

        if not text or not text.strip():
            raise ValueError(
                "Message text must not be empty."
            )

        preprocessed = (
            preprocessor.process(text)
        )

        # Use the normalized text as the canonical
        # ML input. This preserves typo correction
        # without aggressive vocabulary replacement.
        ml_text = preprocessed.normalized

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
            intent_confidence=prediction.confidence,
            entities=extraction.entities,
        )

    async def _get_or_create_session(self, tenant_id: str, user_id: str) -> ConversationSession:
        """
        Get or create a conversation session through the ConversationManager.

        Uses the MongoDB-backed ConversationManager so that customer records
        and conversation state are persisted when the database is available.
        A local cache of (tenant_id, user_id) -> conversation_id keeps
        sessions alive across requests even when MongoDB is disconnected.
        """
        key = (tenant_id, user_id)
        conversation_id = self._conversation_keys.get(key)
        if conversation_id:
            existing = conversation_manager.get_session(conversation_id)
            if existing:
                return existing

        # Resolve customer (persisted when MongoDB is available, transient otherwise)
        customer = await conversation_manager.get_or_create_customer(
            tenant_id=tenant_id,
            phone_number=user_id,
            wa_id=user_id,
        )

        # Get or create the conversation session via the manager
        session = await conversation_manager.get_or_create_conversation(
            tenant_id=tenant_id,
            customer_id=customer.id,
            customer_phone=user_id,
        )

        self._conversation_keys[key] = session.conversation_id
        return session

    async def process(
        self,
        *,
        tenant_id: str,
        user_id: str,
        text: str,
        tenant_settings: Dict[str, Any] | None = None,
        whatsapp_message_id: str | None = None,
        message_type: MessageType = MessageType.TEXT,
        inbound_metadata: Dict[str, Any] | None = None,
    ) -> ProcessedMessage:

        if not text or not text.strip():
            raise ValueError(
                "Message text must not be empty."
            )

        # =========================================================
        # IDEMPOTENCY
        # =========================================================

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

        # =========================================================
        # COMMAND
        # =========================================================

        command = self.extract_command(
            text
        )

        if command:

            return await self.process_command(
                tenant_id=tenant_id,
                user_id=user_id,
                command=command,
                whatsapp_message_id=(
                    whatsapp_message_id
                ),
                tenant_settings=tenant_settings,
                message_type=message_type,
                inbound_metadata=(
                    inbound_metadata
                ),
            )

        # =========================================================
        # NORMAL TEXT → ML
        # =========================================================

        understanding = self.understand(
            text
        )

        # =========================================================
        # SESSION
        # =========================================================

        session = await self._get_or_create_session(
            tenant_id,
            user_id,
        )

        # =========================================================
        # REPLY CONTEXT
        # =========================================================

        reply_product = (
            session.resolve_reply_context(
                text
            )
        )

        if reply_product:

            understanding.entities.append(
                ExtractedEntity(
                    entity_type=EntityType.PRODUCT,
                    value=reply_product,
                    confidence=1.0,
                    normalized_value=reply_product,
                )
            )

        # =========================================================
        # SAVE INBOUND
        # =========================================================

        inbound_msg = Message(
            id=str(uuid4()),

            tenant_id=tenant_id,
            conversation_id=session.conversation_id,
            customer_id=session.customer_id,

            whatsapp_message_id=(
                whatsapp_message_id
            ),

            direction=MessageDirection.INBOUND,

            message_type=message_type,

            text=text,

            intent=understanding.intent,

            intent_confidence=(
                understanding.intent_confidence
            ),

            entities={
                e.entity_type.value:
                    e.normalized_value or e.value
                for e in understanding.entities
            },

            metadata=(
                inbound_metadata or {}
            ),
        )

        await conversation_manager.save_message(
            inbound_msg
        )

        # =========================================================
        # SESSION
        # =========================================================

        session.add_message(
            message_id=inbound_msg.id,
            direction=MessageDirection.INBOUND,
            text=text,
            intent=understanding.intent,
            intent_confidence=(
                understanding.intent_confidence
            ),
            entities=understanding.entities,
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

        # =========================================================
        # SETTINGS
        # =========================================================

        settings = {
            **DEFAULT_TENANT_SETTINGS,
            **(tenant_settings or {}),
            "feature_flags": {
                **DEFAULT_TENANT_SETTINGS[
                    "feature_flags"
                ],
                **(tenant_settings or {}).get(
                    "feature_flags",
                    {},
                ),
            },
        }

        # =========================================================
        # ROUTE
        # =========================================================

        response = await intent_router.route(
            understanding=understanding,
            tenant_id=tenant_id,
            tenant_settings=settings,
            conversation_id=(
                session.conversation_id
            ),
        )

        # =========================================================
        # SAVE OUTBOUND
        # =========================================================

        outbound_msg = Message(
            id=str(uuid4()),

            tenant_id=tenant_id,
            conversation_id=session.conversation_id,
            customer_id=session.customer_id,

            direction=MessageDirection.OUTBOUND,

            message_type=MessageType.TEXT,

            text=response.text or "",

            is_from_bot=True,

            bot_response_type=(
                response.response_type
            ),

            response_to_message_id=(
                inbound_msg.id
            ),

            delivery_status="pending",

            metadata={
                "response_type":
                    response.response_type,

                "product_ids": [
                    p.product_id
                    for p in response.products
                ],

                "source_message_id":
                    inbound_msg.id,
            },
        )

        await conversation_manager.save_message(
            outbound_msg
        )

        # =========================================================
        # SESSION OUTBOUND
        # =========================================================

        session.add_message(
            message_id=outbound_msg.id,
            direction=MessageDirection.OUTBOUND,
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

        await conversation_manager.save_session(
            session
        )

        return ProcessedMessage(
            conversation_id=(
                session.conversation_id
            ),
            understanding=understanding,
            response=response,
            outbound_message_id=(
                outbound_msg.id
            ),
        )
        
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

        command = command.strip().lower()

        # =========================================================
        # GET SESSION
        # =========================================================

        session = await self._get_or_create_session(
            tenant_id,
            user_id,
        )

        # =========================================================
        # CREATE UNDERSTANDING
        # =========================================================

        understanding = MessageUnderstanding(
            original_text=command,
            normalized_text=command,
            intent=IntentType.PAGINATION,
            intent_confidence=1.0,
            entities=[],
        )

        # =========================================================
        # SAVE COMMAND AS INBOUND MESSAGE
        # =========================================================

        inbound_msg = Message(
            id=str(uuid4()),

            tenant_id=tenant_id,
            conversation_id=session.conversation_id,
            customer_id=session.customer_id,

            whatsapp_message_id=(
                whatsapp_message_id
            ),

            direction=MessageDirection.INBOUND,

            message_type=message_type,

            text=command,

            intent=IntentType.PAGINATION,

            intent_confidence=1.0,

            entities={},

            metadata=(
                inbound_metadata or {}
            ),
        )

        await conversation_manager.save_message(
            inbound_msg
        )

        session.add_message(
            message_id=inbound_msg.id,
            direction=MessageDirection.INBOUND,
            text=command,
            intent=IntentType.PAGINATION,
            intent_confidence=1.0,
            entities=[],
            metadata=(
                inbound_metadata or {}
            ),
        )

        # =========================================================
        # ONLY SHOW_MORE IS SUPPORTED HERE
        # =========================================================

        if command != "show_more":

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

            # =====================================================
            # ROUTE PAGINATION
            # =====================================================

            settings = {
                **DEFAULT_TENANT_SETTINGS,
                **(tenant_settings or {}),
                "feature_flags": {
                    **DEFAULT_TENANT_SETTINGS[
                        "feature_flags"
                    ],
                    **(tenant_settings or {}).get(
                        "feature_flags",
                        {},
                    ),
                },
            }

            response = await intent_router.route(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=settings,
                conversation_id=(
                    session.conversation_id
                ),
            )

        # =========================================================
        # SAVE OUTBOUND
        # =========================================================

        outbound_msg = Message(
            id=str(uuid4()),

            tenant_id=tenant_id,
            conversation_id=session.conversation_id,
            customer_id=session.customer_id,

            direction=MessageDirection.OUTBOUND,

            message_type=MessageType.TEXT,

            text=response.text or "",

            is_from_bot=True,

            bot_response_type=(
                response.response_type
            ),

            response_to_message_id=(
                inbound_msg.id
            ),

            delivery_status="pending",

            metadata={
                "response_type":
                    response.response_type,

                "product_ids": [
                    p.product_id
                    for p in response.products
                ],

                "source_message_id":
                    inbound_msg.id,

                "pagination": True,
            },
        )

        await conversation_manager.save_message(
            outbound_msg
        )

        session.add_message(
            message_id=outbound_msg.id,
            direction=MessageDirection.OUTBOUND,
            text=response.text or "",
            is_from_bot=True,
            bot_response_type=(
                response.response_type
            ),
            metadata={
                "pagination": True,
                "outbound_message_id":
                    outbound_msg.id,
            },
        )

        await conversation_manager.save_session(
            session
        )

        return ProcessedMessage(
            conversation_id=(
                session.conversation_id
            ),
            understanding=understanding,
            response=response,
            outbound_message_id=(
                outbound_msg.id
            ),
        )

message_service = MessageService()
