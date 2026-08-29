import asyncio
from dataclasses import dataclass
from typing import Any, Dict
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.conversation.manager import conversation_manager
from app.conversation.session import ConversationSession
from app.ml.entity_extractor import entity_extractor
from app.ml.intent_classifier import intent_classifier
from app.ml.preprocessor import preprocessor
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
from app.routing.intent_router import intent_router


DEFAULT_TENANT_SETTINGS: Dict[str, Any] = {
    "welcome_message": "Welcome! How can I help you today?",
    "fallback_message": (
        "I didn't understand that. Could you please rephrase?"
    ),
    "feature_flags": {
        "enable_ai_responses": True,
        "enable_product_recommendations": True,
        "enable_order_tracking": False,
        "enable_returns": False,
        "enable_cancellation": False,
        "enable_human_handoff": True,
        "enable_analytics": True,
        "use_synonyms": True,
        "max_products_per_response": 3,
    },
}


@dataclass
class ProcessedMessage:
    conversation_id: str
    understanding: MessageUnderstanding
    response: BotResponse
    outbound_message_id: str | None = None


class DuplicateWhatsAppMessage(Exception):
    def __init__(self, whatsapp_message_id: str) -> None:
        self.whatsapp_message_id = whatsapp_message_id
        super().__init__(
            f"WhatsApp message already processed: "
            f"{whatsapp_message_id}"
        )


class MessageService:

    @staticmethod
    def _expected_provider_message_count(
        response: BotResponse,
    ) -> int:
        count = 0

        if response.response_type in {
            "product_list",
            "product_card",
        }:
            count += len(response.products[:5])
        elif response.text:
            count += 1

        if response.quick_replies:
            count += 1

        return count

    def __init__(self) -> None:
        self._conversation_keys: Dict[
            tuple[str, str],
            str,
        ] = {}

    @staticmethod
    def extract_command(
        text: str,
    ) -> str | None:
        if not text:
            return None

        prefix = "__COMMAND__:"

        if not text.startswith(prefix):
            return None

        command = text[len(prefix):].strip()

        return command or None

    def understand(
        self,
        text: str,
        *,
        use_synonyms: bool = True,
    ) -> MessageUnderstanding:
        if not text or not text.strip():
            raise ValueError(
                "Message text must not be empty."
            )

        preprocessed = preprocessor.process(text)

        ml_text = (
            preprocessed.vocabulary_matched
            if use_synonyms
            else preprocessed.normalized
        )

        prediction = intent_classifier.predict(
            ml_text
        )

        extraction = entity_extractor.extract(
            ml_text,
            intent=prediction.intent.value,
        )

        return MessageUnderstanding(
            original_text=text,
            normalized_text=ml_text,
            intent=prediction.intent,
            intent_confidence=prediction.confidence,
            entities=extraction.entities,
        )

    async def _get_or_create_session(
        self,
        tenant_id: str,
        user_id: str,
    ) -> ConversationSession:

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if not user_id:
            raise ValueError(
                "user_id is required"
            )

        key = (tenant_id, user_id)

        conversation_id = self._conversation_keys.get(key)

        if conversation_id:
            existing = conversation_manager.get_session(
                conversation_id
            )

            if existing:
                return existing

        customer = (
            await conversation_manager.get_or_create_customer(
                tenant_id=tenant_id,
                phone_number=user_id,
                wa_id=user_id,
            )
        )

        session = (
            await conversation_manager.get_or_create_conversation(
                tenant_id=tenant_id,
                customer_id=customer.id,
                customer_phone=user_id,
            )
        )

        self._conversation_keys[key] = (
            session.conversation_id
        )

        return session

    @staticmethod
    def _merge_tenant_settings(
        tenant_settings: Dict[str, Any] | None,
    ) -> Dict[str, Any]:

        tenant_settings = tenant_settings or {}

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

    async def mark_outbound_sent(
        self,
        outbound_message_id: str,
        whatsapp_message_id: str | None = None,
    ) -> None:

        if not outbound_message_id:
            raise ValueError(
                "outbound_message_id is required"
            )

        await conversation_manager.update_message_delivery(
            outbound_message_id,
            status="sent",
            whatsapp_message_id=whatsapp_message_id,
        )

    async def mark_outbound_failed(
        self,
        outbound_message_id: str,
        error: str,
    ) -> None:

        if not outbound_message_id:
            raise ValueError(
                "outbound_message_id is required"
            )

        error = error or "Unknown WhatsApp delivery error"

        await conversation_manager.update_message_delivery(
            outbound_message_id,
            status="failed",
            error=error[:2000],
        )

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

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if not user_id:
            raise ValueError(
                "user_id is required"
            )

        if not text or not text.strip():
            raise ValueError(
                "Message text must not be empty."
            )

        if whatsapp_message_id:
            existing = (
                await conversation_manager.get_message_by_whatsapp_id(
                    tenant_id=tenant_id,
                    whatsapp_message_id=whatsapp_message_id,
                )
            )

            if existing:
                raise DuplicateWhatsAppMessage(
                    whatsapp_message_id
                )

        command = self.extract_command(text)

        if command:
            return await self.process_command(
                tenant_id=tenant_id,
                user_id=user_id,
                command=command,
                whatsapp_message_id=whatsapp_message_id,
                tenant_settings=tenant_settings,
                message_type=message_type,
                inbound_metadata=inbound_metadata,
            )

        settings = self._merge_tenant_settings(
            tenant_settings
        )

        use_synonyms = bool(
            settings.get(
                "feature_flags",
                {},
            ).get(
                "use_synonyms",
                True,
            )
        )

        # ML preprocessing, intent prediction, and NER are synchronous
        # scikit-learn operations. Running them directly from this async
        # method would block FastAPI's event loop. Execute the complete
        # synchronous ML pipeline in a worker thread.
        understanding = await asyncio.to_thread(
            self.understand,
            text,
            use_synonyms=use_synonyms,
        )

        session = await self._get_or_create_session(
            tenant_id,
            user_id,
        )

        reply_product = session.resolve_reply_context(
            text
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

        inbound_msg = Message(
            id=str(uuid4()),
            tenant_id=tenant_id,
            conversation_id=session.conversation_id,
            customer_id=session.customer_id,
            whatsapp_message_id=whatsapp_message_id,
            direction=MessageDirection.INBOUND,
            message_type=message_type,
            text=text,
            intent=understanding.intent,
            intent_confidence=understanding.intent_confidence,
            entities={
                entity.entity_type.value: (
                    entity.normalized_value
                    or entity.value
                )
                for entity in understanding.entities
            },
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

        session.add_message(
            message_id=inbound_msg.id,
            direction=MessageDirection.INBOUND,
            text=text,
            intent=understanding.intent,
            intent_confidence=understanding.intent_confidence,
            entities=understanding.entities,
            metadata=(
                {"reply_context_product": reply_product}
                if reply_product
                else None
            ),
        )

        session.update_context_from_understanding(
            understanding
        )

        response = await intent_router.route(
            understanding=understanding,
            tenant_id=tenant_id,
            tenant_settings=settings,
            conversation_id=session.conversation_id,
        )

        outbound_msg = self._build_outbound_message(
            tenant_id=tenant_id,
            session=session,
            inbound_message=inbound_msg,
            response=response,
        )

        outbound_msg.metadata.update({
            "delivery_group_id": str(uuid4()),
            "expected_provider_messages": (
                self._expected_provider_message_count(
                    response
                )
            ),
        })

        await conversation_manager.save_message(
            outbound_msg
        )

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
                "delivery_group_id": (
                    outbound_msg.metadata.get(
                        "delivery_group_id"
                    )
                ),
            },
        )

        await conversation_manager.save_session(
            session
        )

        return ProcessedMessage(
            conversation_id=session.conversation_id,
            understanding=understanding,
            response=response,
            outbound_message_id=outbound_msg.id,
        )

    @staticmethod
    def _build_outbound_message(
        *,
        tenant_id: str,
        session: ConversationSession,
        inbound_message: Message,
        response: BotResponse,
        pagination: bool = False,
    ) -> Message:

        return Message(
            id=str(uuid4()),
            tenant_id=tenant_id,
            conversation_id=session.conversation_id,
            customer_id=session.customer_id,
            direction=MessageDirection.OUTBOUND,
            message_type=MessageType.TEXT,
            text=response.text or "",
            is_from_bot=True,
            bot_response_type=response.response_type,
            response_to_message_id=inbound_message.id,
            delivery_status="pending",
            metadata={
                "response_type": response.response_type,
                "product_ids": [
                    product.product_id
                    for product in response.products
                ],
                "source_message_id": inbound_message.id,
                "pagination": pagination,
            },
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

        session = await self._get_or_create_session(
            tenant_id,
            user_id,
        )

        if command == "search_again":

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

            session.clear_awaiting_entity()
            session.clear_awaiting_confirmation()

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

            settings = self._merge_tenant_settings(
                tenant_settings
            )

            response = await intent_router.route(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=settings,
                conversation_id=session.conversation_id,
            )

        else:

            understanding = MessageUnderstanding(
                original_text=command,
                normalized_text=command,
                intent=IntentType.PAGINATION,
                intent_confidence=1.0,
                entities=[],
            )

            response = BotResponse(
                response_type="text",
                text=(
                    "I couldn't process that selection. "
                    "Please try again."
                ),
                products=[],
                quick_replies=[],
                metadata={
                    "command": command,
                    "success": False,
                    "unsupported_command": True,
                },
            )

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
            intent_confidence=understanding.intent_confidence,
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

        session.add_message(
            message_id=inbound_msg.id,
            direction=MessageDirection.INBOUND,
            text=command,
            intent=understanding.intent,
            intent_confidence=understanding.intent_confidence,
            entities=[],
            metadata=inbound_metadata or {},
        )

        outbound_msg = self._build_outbound_message(
            tenant_id=tenant_id,
            session=session,
            inbound_message=inbound_msg,
            response=response,
            pagination=command == "show_more",
        )

        outbound_msg.metadata.update({
            "delivery_group_id": str(uuid4()),
            "expected_provider_messages": (
                self._expected_provider_message_count(
                    response
                )
            ),
            "command": command,
        })

        await conversation_manager.save_message(
            outbound_msg
        )

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
                "pagination": (
                    command == "show_more"
                ),
            },
        )

        await conversation_manager.save_session(
            session
        )

        return ProcessedMessage(
            conversation_id=session.conversation_id,
            understanding=understanding,
            response=response,
            outbound_message_id=outbound_msg.id,
        )


message_service = MessageService()
