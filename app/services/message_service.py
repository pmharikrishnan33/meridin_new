"""Application service that turns incoming text into a bot response."""

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
)
from app.routing.intent_router import intent_router


DEFAULT_TENANT_SETTINGS: Dict[str, Any] = {
    "welcome_message": "Welcome! How can I help you today?",
    "fallback_message": "I didn't understand that. Could you please rephrase?",
    "feature_flags": {
        "enable_ai_responses": True,
        "enable_product_recommendations": True,
        "enable_order_tracking": True,
        "enable_returns": True,
        "enable_cancellation": True,
        "enable_human_handoff": True,
        "enable_analytics": True,
        "max_products_per_response": 5,
    },
}


@dataclass
class ProcessedMessage:
    conversation_id: str
    understanding: MessageUnderstanding
    response: BotResponse


class MessageService:
    """Coordinates normalization, ML understanding, session state, and routing."""

    def __init__(self) -> None:
        self._conversation_keys: Dict[tuple[str, str], str] = {}

    def understand(self, text: str) -> MessageUnderstanding:
        """Create a single canonical understanding object for a text message."""
        if not text or not text.strip():
            raise ValueError("Message text must not be empty.")

        # Run the full preprocessing pipeline: normalization + vocabulary matching
        preprocessed = preprocessor.process(text)
        normalized_text = preprocessed.vocabulary_matched

        prediction = intent_classifier.predict(normalized_text)
        extraction = entity_extractor.extract(text, intent=prediction.intent.value)
        return MessageUnderstanding(
            original_text=text,
            normalized_text=normalized_text,
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
    ) -> ProcessedMessage:
        """Process one inbound message and return the response without sending it."""
        understanding = self.understand(text)
        session = await self._get_or_create_session(tenant_id, user_id)

        # Resolve a lightweight reply context when the user refers back to the
        # most recent bot-selected product search list.
        reply_product = session.resolve_reply_context(text)
        if reply_product:
            understanding.entities.append(
                ExtractedEntity(
                    entity_type=EntityType.PRODUCT,
                    value=reply_product,
                    confidence=1.0,
                    normalized_value=reply_product,
                )
            )

        # Persist inbound message to MongoDB when available
        inbound_msg = Message(
            id=str(uuid4()),
            tenant_id=tenant_id,
            conversation_id=session.conversation_id,
            customer_id=session.customer_id,
            direction=MessageDirection.INBOUND,
            message_type=MessageType.TEXT,
            text=text,
            intent=understanding.intent,
            intent_confidence=understanding.intent_confidence,
            entities={
                e.entity_type.value: e.normalized_value or e.value
                for e in understanding.entities
            },
        )
        await conversation_manager.save_message(inbound_msg)

        session.add_message(
            message_id=inbound_msg.id,
            direction=MessageDirection.INBOUND,
            text=text,
            intent=understanding.intent,
            intent_confidence=understanding.intent_confidence,
            entities=understanding.entities,
            metadata={"reply_context_product": reply_product} if reply_product else None,
        )
        session.update_context_from_understanding(understanding)

        settings = {
            **DEFAULT_TENANT_SETTINGS,
            **(tenant_settings or {}),
            "feature_flags": {
                **DEFAULT_TENANT_SETTINGS["feature_flags"],
                **(tenant_settings or {}).get("feature_flags", {}),
            },
        }
        response = await intent_router.route(
            understanding=understanding,
            tenant_id=tenant_id,
            tenant_settings=settings,
            conversation_id=session.conversation_id,
        )

        # Persist outbound message to MongoDB when available
        outbound_metadata = {
            "response_type": response.response_type,
            "product_ids": [p.product_id for p in response.products],
            "source_message_id": inbound_msg.id,
        }

        outbound_msg = Message(
            id=str(uuid4()),
            tenant_id=tenant_id,
            conversation_id=session.conversation_id,
            customer_id=session.customer_id,
            direction=MessageDirection.OUTBOUND,
            message_type=MessageType.TEXT,
            text=response.text or "",
            is_from_bot=True,
            bot_response_type=response.response_type,
            response_to_message_id=inbound_msg.id,
            metadata=outbound_metadata,
        )
        await conversation_manager.save_message(outbound_msg)

        session.add_message(
            message_id=outbound_msg.id,
            direction=MessageDirection.OUTBOUND,
            text=response.text or "",
            is_from_bot=True,
            bot_response_type=response.response_type,
            metadata=outbound_metadata,
        )

        # Persist session state
        await conversation_manager.save_session(session)

        return ProcessedMessage(session.conversation_id, understanding, response)


message_service = MessageService()
