"""
Intent Router - routes understood messages to appropriate handlers.
"""

from typing import Optional, Dict, Any

from app.utils.logger import logger
from app.models.schemas import IntentType, MessageUnderstanding, BotResponse
from app.routing.intent_config import (
    get_intent_config,
    get_required_entities,
    check_tenant_feature
)
from app.conversation.manager import conversation_manager
from app.ai.fallback import ai_fallback


class IntentRouter:
    """
    Routes incoming messages to appropriate intent handlers.
    """

    def __init__(self):
        self._handler_cache: Dict[str, Any] = {}

    async def route(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_id: str
    ) -> BotResponse:
        """
        Route message to appropriate handler based on intent.

        Flow:
        1. Get intent config
        2. Check tenant feature flags
        3. Validate required entities
        4. Load handler
        5. Execute handler
        6. Return structured response
        """

        intent = understanding.intent
        config = get_intent_config(intent)

        logger.info(f"Routing intent: {intent.value} (confidence: {understanding.intent_confidence:.2f})")

        # Check confidence threshold
        if understanding.intent_confidence < config.min_confidence:
            logger.warning(
                f"Intent {intent.value} confidence {understanding.intent_confidence:.2f} "
                f"below threshold {config.min_confidence}, using fallback"
            )
            if config.fallback_intent:
                intent = config.fallback_intent
                config = get_intent_config(intent)
            else:
                intent = IntentType.UNKNOWN
                config = get_intent_config(intent)

        # Check tenant feature flags
        if config.allowed_tenant_features:
            for feature in config.allowed_tenant_features:
                if not check_tenant_feature(tenant_settings, feature):
                    logger.info(f"Tenant feature {feature} disabled, using fallback")
                    if config.fallback_intent:
                        intent = config.fallback_intent
                        config = get_intent_config(intent)
                    else:
                        intent = IntentType.UNKNOWN
                        config = get_intent_config(intent)
                    break

        # Validate required entities
        required_entities = get_required_entities(intent)
        missing_entities = self._check_required_entities(
            understanding, required_entities
        )

        if missing_entities:
            logger.info(f"Missing required entities for {intent.value}: {missing_entities}")
            return await self._handle_missing_entities(
                understanding, missing_entities, tenant_settings, conversation_id
            )

        # Load and execute handler
        handler = await self._get_handler(config.handler_class)

        if handler is None:
            logger.error(f"Handler not found: {config.handler_class}")
            return await self._ai_fallback_response(
                tenant_settings, conversation_id, understanding.original_text
            )

        try:
            # Get conversation context
            session = conversation_manager.get_session(conversation_id)
            context = session.context if session else None

            # Attach message history so handlers (e.g. FallbackHandler) can
            # build AI fallback prompts from recent conversation turns.
            if session is not None and context is not None:
                context._message_history = session.message_history

            # Execute handler
            response = await handler.handle(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=tenant_settings,
                conversation_context=context,
            )

            # Add routing metadata
            response.metadata.update({
                "intent": intent.value,
                "handler": config.handler_class,
                "confidence": understanding.intent_confidence
            })

            logger.info(f"Handler {config.handler_class} completed successfully")
            return response

        except Exception as e:
            logger.exception(f"Handler {config.handler_class} failed: {e}")
            return await self._ai_fallback_response(
                tenant_settings, conversation_id, understanding.original_text
            )

    def _check_required_entities(
        self,
        understanding: MessageUnderstanding,
        required_entities: list
    ) -> list:
        """
        Check if all required entities are present.
        Returns list of missing entity types.
        """

        extracted_types = {e.entity_type for e in understanding.entities}
        missing = [e for e in required_entities if e not in extracted_types]
        return missing

    async def _handle_missing_entities(
        self,
        understanding: MessageUnderstanding,
        missing_entities: list,
        tenant_settings: Dict[str, Any],
        conversation_id: str
    ) -> BotResponse:
        """
        Handle case where required entities are missing.
        """

        # Store what we're awaiting in conversation context
        session = conversation_manager.get_session(conversation_id)
        if session and missing_entities:
            session.context.awaiting_entity = missing_entities[0]
            session.context.awaiting_confirmation = True
            session.context.confirmation_context = {
                "intent": understanding.intent.value,
                "missing_entities": [e.value for e in missing_entities]
            }
            await conversation_manager.save_session(session)

        # Generate clarification question
        entity_names = {
            "product": "which product",
            "color": "which color",
            "size": "which size",
            "fit": "which fit",
            "price": "what price range",
            "order_id": "your order ID",
        }

        questions = []
        for entity in missing_entities:
            entity_name = entity_names.get(entity.value, entity.value)
            questions.append(f"Could you please specify {entity_name}?")

        clarification = " ".join(questions)

        return BotResponse(
            response_type="text",
            text=clarification,
            metadata={"needs_clarification": True, "missing_entities": [e.value for e in missing_entities]}
        )

    # Mapping of handler class names to their module paths.
    # The naming convention is inconsistent (e.g. "ProductSearchHandler"
    # lives in product_search.py, "AvailabilityHandler" in product_availability.py),
    # so we use an explicit mapping rather than a fragile string transform.
    _HANDLER_MODULES: Dict[str, str] = {
        "GreetingHandler": "app.handlers.greeting",
        "ProductSearchHandler": "app.handlers.product_search",
        "ProductInquiryHandler": "app.handlers.product_inquiry",
        "AvailabilityHandler": "app.handlers.product_availability",
        "OrderStatusHandler": "app.handlers.order_status",
        "CancelOrderHandler": "app.handlers.cancel_order",
        "ReturnRequestHandler": "app.handlers.return_request",
        "ComplaintHandler": "app.handlers.complaint",
        "ThanksHandler": "app.handlers.thanks",
        "FallbackHandler": "app.handlers.fallback",
    }

    async def _get_handler(self, handler_class: str):
        """
        Dynamically load handler class.
        """

        if handler_class in self._handler_cache:
            return self._handler_cache[handler_class]

        module_path = self._HANDLER_MODULES.get(handler_class)
        if module_path is None:
            logger.error(f"Unknown handler class: {handler_class}")
            return None

        try:
            module = __import__(module_path, fromlist=[handler_class])
            handler_cls = getattr(module, handler_class)
            handler_instance = handler_cls()
            self._handler_cache[handler_class] = handler_instance
            return handler_instance
        except ImportError as e:
            logger.error(f"Failed to import handler {handler_class}: {e}")
            return None
        except AttributeError as e:
            logger.error(f"Handler class not found: {handler_class}")
            return None

    def _fallback_response(self, tenant_settings: Dict[str, Any]) -> BotResponse:
        """
        Generate fallback response when routing fails.

        Uses the AI fallback generator when the tenant has AI responses
        enabled and the OpenRouter client is configured; otherwise returns
        a static message.
        """

        fallback_msg = tenant_settings.get("fallback_message", "I didn't understand that. Could you please rephrase?")

        return BotResponse(
            response_type="text",
            text=fallback_msg,
            metadata={"fallback": True}
        )

    async def _ai_fallback_response(
        self,
        tenant_settings: Dict[str, Any],
        conversation_id: str,
        user_text: str,
    ) -> BotResponse:
        """
        Attempt an AI-powered fallback response.

        Only used when ``enable_ai_responses`` is on and the OpenRouter
        client is configured.  Returns a static fallback otherwise.
        """

        feature_flags = tenant_settings.get("feature_flags", {})
        if not feature_flags.get("enable_ai_responses", False) or not ai_fallback.is_available:
            return self._fallback_response(tenant_settings)

        try:
            session = conversation_manager.get_session(conversation_id)
            history = None
            if session is not None:
                history = []
                for msg in session.message_history[-10:]:
                    text = msg.get("text", "")
                    if not text:
                        continue
                    role = "assistant" if msg.get("direction") == "outbound" else "user"
                    history.append({"role": role, "content": text})

            from app.models.schemas import IntentType, MessageUnderstanding
            understanding = MessageUnderstanding(
                original_text=user_text,
                normalized_text=user_text,
                intent=IntentType.UNKNOWN,
                intent_confidence=0.0,
            )
            response = await ai_fallback.generate(
                understanding=understanding,
                tenant_settings=tenant_settings,
                conversation_history=history,
            )
            return response
        except Exception as exc:
            logger.warning(f"AI fallback failed, using static response: {exc}")
            return self._fallback_response(tenant_settings)


intent_router = IntentRouter()