"""
Intent Router - routes understood messages to appropriate handlers.

Product-search requirement orchestration is intentionally delegated to
ProductSearchHandler. That handler is the single authority for:

- metadata normalization
- category resolution
- category-specific requirements
- follow-up questions
- product search
- conversational search state
"""

from __future__ import annotations

from typing import Any, Dict

from app.ai.fallback import ai_fallback
from app.conversation.manager import conversation_manager
from app.models.schemas import (
    BotResponse,
    EntityType,
    ExtractedEntity,
    IntentType,
    MessageUnderstanding,
)
from app.routing.intent_config import (
    check_tenant_feature,
    get_intent_config,
)
from app.utils.logger import logger


DISABLED_INTENTS = {
    IntentType.ORDER_STATUS,
    IntentType.CANCEL_ORDER,
    IntentType.RETURN_REQUEST,
}


PAGINATION_PHRASES = {
    "show more",
    "more",
    "next",
    "next page",
    "more products",
    "show me more",
}


class IntentRouter:
    """
    Routes incoming messages to the appropriate handler.

    Product search is deliberately delegated to ProductSearchHandler.
    ProductSearchHandler owns the metadata-driven conversational
    requirement workflow.
    """

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
        "PaginationHandler": "app.handlers.pagination_handler",
    }

    def __init__(self) -> None:
        self._handler_cache: Dict[str, Any] = {}

    async def route(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_id: str,
    ) -> BotResponse:
        """
        Route an understood message to the appropriate handler.

        Product-search conversations are delegated directly to
        ProductSearchHandler. The handler is responsible for all
        metadata-driven requirement checks.
        """

        session = conversation_manager.get_session(
            conversation_id
        )

        context = (
            session.context
            if session is not None
            else None
        )

        normalized_text = (
            understanding.normalized_text or ""
        ).strip().lower()

        if normalized_text in PAGINATION_PHRASES:
            understanding.intent = IntentType.PAGINATION

        # ============================================================
        # 1. CONTINUE A PENDING ENTITY COLLECTION
        # ============================================================
        #
        # Example:
        #
        #   Bot:
        #       What size would you like?
        #
        #   User:
        #       M
        #
        # The pending entity must be interpreted as the answer to the
        # existing product-search requirement.
        #
        # IMPORTANT:
        #
        # We do NOT clear the previous search context here.
        # ProductSearchHandler needs the previous filters so that:
        #
        #   black + shirt
        #
        # can become:
        #
        #   black + shirt + M
        #
        # ============================================================

        if (
            session is not None
            and context is not None
            and context.awaiting_entity is not None
        ):
            awaiting_entity = context.awaiting_entity

            extracted_entity = self._find_entity(
                understanding.entities,
                awaiting_entity,
            )

            if extracted_entity is not None:
                logger.info(
                    "Resolved pending entity %s from "
                    "follow-up message",
                    awaiting_entity.value,
                )

                pending_intent = (
                    context.confirmation_context.get(
                        "intent"
                    )
                    if context.confirmation_context
                    else None
                )

                if pending_intent:
                    try:
                        understanding.intent = IntentType(
                            pending_intent
                        )
                    except ValueError:
                        understanding.intent = (
                            IntentType.PRODUCT_SEARCH
                        )
                else:
                    understanding.intent = (
                        IntentType.PRODUCT_SEARCH
                    )

                # Do not clear awaiting_entity here.
                #
                # ProductSearchHandler will:
                #
                # 1. merge the previous filters
                # 2. add the new entity
                # 3. normalize metadata
                # 4. evaluate requirements
                # 5. either ask the next question or search
                #
                # The handler clears the pending state only when
                # appropriate.

            else:
                # The user did not provide an entity matching the
                # requested requirement.
                #
                # Prefer the exact metadata-defined question stored
                # in confirmation_context when available.
                requirement = (
                    context.confirmation_context.get(
                        "requirement"
                    )
                    if context.confirmation_context
                    else None
                )

                question = None

                if isinstance(
                    requirement,
                    dict,
                ) and requirement:
                    try:
                        from app.conversation.requirements import (
                            conversation_requirement_engine,
                        )

                        question = (
                            conversation_requirement_engine
                            .question_for_requirement(
                                requirement
                            )
                        )
                    except Exception as exc:
                        logger.warning(
                            "Could not rebuild pending "
                            "requirement question: %s",
                            exc,
                        )

                if not question:
                    question = (
                        self._fallback_question_for_entity(
                            awaiting_entity
                        )
                    )

                return BotResponse(
                    response_type="text",
                    text=question,
                    metadata={
                        "needs_clarification": True,
                        "missing": awaiting_entity.value,
                        "awaiting_entity": (
                            awaiting_entity.value
                        ),
                    },
                )

        # ============================================================
        # 2. DISABLED INTENTS
        # ============================================================

        intent = understanding.intent

        if intent in DISABLED_INTENTS:
            logger.info(
                "Intent %s is disabled in the current Meridin phase",
                intent.value,
            )

            intent = IntentType.UNKNOWN
            understanding.intent = intent

        # ============================================================
        # 3. SMART SEARCH OVERRIDE
        # ============================================================

        config = get_intent_config(
            intent
        )

        extracted_types = {
            entity.entity_type
            for entity in understanding.entities
        }

        if intent in {
            IntentType.PRODUCT_INQUIRY,
            IntentType.AVAILABILITY,
        }:
            if EntityType.PRICE in extracted_types:
                logger.info(
                    "Smart override: switched %s to "
                    "product_search because a price filter "
                    "was detected",
                    intent.value,
                )

                intent = IntentType.PRODUCT_SEARCH
                understanding.intent = intent

                config = get_intent_config(
                    intent
                )

        # ============================================================
        # 4. PRODUCT SEARCH
        # ============================================================
        #
        # There is intentionally NO requirement evaluation here.
        #
        # ProductSearchHandler owns the complete product-search
        # workflow because it has access to:
        #
        #   tenant metadata
        #   category IDs
        #   category requirements
        #   normalized filters
        #   conversation context
        #
        # This prevents the router from accidentally evaluating:
        #
        #   requirements = []
        #
        # and incorrectly deciding that a search is ready.
        #
        # ============================================================

        if intent == IntentType.PRODUCT_SEARCH:
            return await self._execute_product_search(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=tenant_settings,
                conversation_id=conversation_id,
            )

        # ============================================================
        # 5. NORMAL INTENT CONFIDENCE CHECK
        # ============================================================

        logger.info(
            "Routing intent: %s (confidence: %.2f)",
            intent.value,
            understanding.intent_confidence,
        )

        if (
            understanding.intent_confidence
            < config.min_confidence
        ):
            logger.warning(
                "Intent %s confidence %.2f below threshold %.2f",
                intent.value,
                understanding.intent_confidence,
                config.min_confidence,
            )

            if config.fallback_intent:
                intent = config.fallback_intent
                understanding.intent = intent

                config = get_intent_config(
                    intent
                )
            else:
                intent = IntentType.UNKNOWN
                understanding.intent = intent

                config = get_intent_config(
                    intent
                )

        # ============================================================
        # 6. TENANT FEATURE FLAGS
        # ============================================================

        if config.allowed_tenant_features:
            for feature in config.allowed_tenant_features:
                if not check_tenant_feature(
                    tenant_settings,
                    feature,
                ):
                    logger.info(
                        "Tenant feature %s disabled",
                        feature,
                    )

                    if config.fallback_intent:
                        intent = config.fallback_intent
                        understanding.intent = intent

                        config = get_intent_config(
                            intent
                        )
                    else:
                        intent = IntentType.UNKNOWN
                        understanding.intent = intent

                        config = get_intent_config(
                            intent
                        )

                    break

        # ============================================================
        # 7. GENERIC REQUIRED ENTITY VALIDATION
        # ============================================================

        required_entities = (
            config.required_entities
            if hasattr(
                config,
                "required_entities",
            )
            else []
        )

        missing_entities = (
            self._check_required_entities(
                understanding,
                required_entities,
                context,
            )
        )

        if missing_entities:
            return await self._handle_missing_entities(
                understanding=understanding,
                missing_entities=missing_entities,
                tenant_settings=tenant_settings,
                conversation_id=conversation_id,
            )

        # ============================================================
        # 8. EXECUTE NORMAL HANDLER
        # ============================================================

        handler = await self._get_handler(
            config.handler_class
        )

        if handler is None:
            logger.error(
                "Handler not found: %s",
                config.handler_class,
            )

            return await self._ai_fallback_response(
                tenant_settings,
                conversation_id,
                understanding.original_text,
            )

        try:
            session = conversation_manager.get_session(
                conversation_id
            )

            context = (
                session.context
                if session is not None
                else None
            )

            if (
                session is not None
                and context is not None
            ):
                context._message_history = (
                    session.message_history
                )

            response = await handler.handle(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=tenant_settings,
                conversation_context=context,
            )

            response.metadata.update(
                {
                    "intent": intent.value,
                    "handler": config.handler_class,
                    "confidence": (
                        understanding.intent_confidence
                    ),
                }
            )

            return response

        except Exception as exc:
            logger.exception(
                "Handler %s failed: %s",
                config.handler_class,
                exc,
            )

            return await self._ai_fallback_response(
                tenant_settings,
                conversation_id,
                understanding.original_text,
            )

    async def _execute_product_search(
        self,
        *,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_id: str,
    ) -> BotResponse:
        """
        Execute ProductSearchHandler.

        Requirement checking is intentionally not performed here.
        ProductSearchHandler performs:

            entity extraction
                ↓
            previous-context merge
                ↓
            metadata normalization
                ↓
            category requirement lookup
                ↓
            missing requirement question
                ↓
            search
        """

        config = get_intent_config(
            IntentType.PRODUCT_SEARCH
        )

        # Respect tenant feature flags for product search.
        if config.allowed_tenant_features:
            for feature in config.allowed_tenant_features:
                if not check_tenant_feature(
                    tenant_settings,
                    feature,
                ):
                    logger.info(
                        "Tenant feature %s disabled",
                        feature,
                    )

                    if config.fallback_intent:
                        fallback_intent = (
                            config.fallback_intent
                        )

                        fallback_config = (
                            get_intent_config(
                                fallback_intent
                            )
                        )

                        fallback_handler = (
                            await self._get_handler(
                                fallback_config.handler_class
                            )
                        )

                        if fallback_handler is not None:
                            session = (
                                conversation_manager.get_session(
                                    conversation_id
                                )
                            )

                            context = (
                                session.context
                                if session is not None
                                else None
                            )

                            return await fallback_handler.handle(
                                understanding=understanding,
                                tenant_id=tenant_id,
                                tenant_settings=tenant_settings,
                                conversation_context=context,
                            )

                    return self._fallback_response(
                        tenant_settings
                    )

        handler = await self._get_handler(
            config.handler_class
        )

        if handler is None:
            logger.error(
                "Product search handler not found: %s",
                config.handler_class,
            )

            return await self._ai_fallback_response(
                tenant_settings,
                conversation_id,
                understanding.original_text,
            )

        session = conversation_manager.get_session(
            conversation_id
        )

        context = (
            session.context
            if session is not None
            else None
        )

        if (
            session is not None
            and context is not None
        ):
            context._message_history = (
                session.message_history
            )

        try:
            response = await handler.handle(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=tenant_settings,
                conversation_context=context,
            )

            response.metadata.update(
                {
                    "intent": (
                        IntentType.PRODUCT_SEARCH.value
                    ),
                    "handler": config.handler_class,
                    "confidence": (
                        understanding.intent_confidence
                    ),
                }
            )

            return response

        except Exception as exc:
            logger.exception(
                "Product search handler failed: %s",
                exc,
            )

            return await self._ai_fallback_response(
                tenant_settings,
                conversation_id,
                understanding.original_text,
            )

    @staticmethod
    def _find_entity(
        entities,
        entity_type: EntityType,
    ) -> ExtractedEntity | None:
        """
        Find the highest-confidence entity of the requested type.
        """

        candidates = [
            entity
            for entity in entities
            if entity.entity_type == entity_type
        ]

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda entity: (
                entity.confidence,
                entity.end_pos - entity.start_pos,
            ),
        )

    @staticmethod
    def _fallback_question_for_entity(
        entity_type: EntityType,
    ) -> str:
        """
        Fallback question for a pending entity.

        Metadata-defined questions are preferred. This is only used
        when the pending metadata requirement is unavailable.
        """

        questions = {
            EntityType.PRODUCT: (
                "What product are you looking for?"
            ),
            EntityType.CATEGORY: (
                "What type of clothing are you looking for?"
            ),
            EntityType.COLOR: (
                "What color would you like?"
            ),
            EntityType.SIZE: (
                "What size would you like?"
            ),
            EntityType.FIT: (
                "What fit would you prefer?"
            ),
            EntityType.PRICE: (
                "What price range would you prefer?"
            ),
            EntityType.BRAND: (
                "Do you have a preferred brand?"
            ),
            EntityType.MATERIAL: (
                "Do you have a preferred material?"
            ),
            EntityType.GENDER: (
                "Who are you shopping for?"
            ),
            EntityType.STYLE: (
                "What style would you prefer?"
            ),
            EntityType.PATTERN: (
                "What pattern would you prefer?"
            ),
            EntityType.OCCASION: (
                "What occasion are you shopping for?"
            ),
            EntityType.SEASON: (
                "Which season are you shopping for?"
            ),
            EntityType.SLEEVE: (
                "What sleeve style would you prefer?"
            ),
            EntityType.NECK: (
                "What neck style would you prefer?"
            ),
            EntityType.ORDER_ID: (
                "Could you please provide your order ID?"
            ),
        }

        return questions.get(
            entity_type,
            "Could you please provide the requested information?",
        )

    def _check_required_entities(
        self,
        understanding: MessageUnderstanding,
        required_entities: list,
        context=None,
    ) -> list:
        """
        Check whether generic required entities are available.
        """

        available_entities = {
            entity.entity_type
            for entity in understanding.entities
        }

        if (
            context
            and context.current_product
        ):
            available_entities.add(
                EntityType.PRODUCT
            )

        return [
            entity_type
            for entity_type in required_entities
            if entity_type not in available_entities
        ]

    async def _handle_missing_entities(
        self,
        understanding: MessageUnderstanding,
        missing_entities: list,
        tenant_settings: Dict[str, Any],
        conversation_id: str,
    ) -> BotResponse:
        """
        Handle generic missing entities.
        """

        session = conversation_manager.get_session(
            conversation_id
        )

        if (
            session is not None
            and missing_entities
        ):
            missing_entity = missing_entities[0]

            session.context.awaiting_entity = (
                missing_entity
            )

            session.context.awaiting_confirmation = False

            session.context.confirmation_context = {
                "intent": understanding.intent.value,
                "missing_entities": [
                    entity.value
                    for entity in missing_entities
                ],
            }

            await conversation_manager.save_session(
                session
            )

        entity_names = {
            "product": "which product",
            "category": "which category",
            "color": "which color",
            "size": "which size",
            "fit": "which fit",
            "price": "what price range",
            "brand": "which brand",
            "material": "which material",
            "gender": "who you are shopping for",
            "style": "which style",
            "pattern": "which pattern",
            "occasion": "which occasion",
            "season": "which season",
            "sleeve": "which sleeve style",
            "neck": "which neck style",
            "order_id": "your order ID",
        }

        questions = []

        for entity in missing_entities:
            entity_name = entity_names.get(
                entity.value,
                entity.value,
            )

            questions.append(
                f"Could you please specify {entity_name}?"
            )

        clarification = " ".join(
            questions
        )

        return BotResponse(
            response_type="text",
            text=clarification,
            metadata={
                "needs_clarification": True,
                "missing_entities": [
                    entity.value
                    for entity in missing_entities
                ],
            },
        )

    async def _get_handler(
        self,
        handler_class: str,
    ):
        """
        Dynamically load a handler class.
        """

        if handler_class in self._handler_cache:
            return self._handler_cache[
                handler_class
            ]

        module_path = self._HANDLER_MODULES.get(
            handler_class
        )

        if module_path is None:
            logger.error(
                "Unknown handler class: %s",
                handler_class,
            )
            return None

        try:
            module = __import__(
                module_path,
                fromlist=[handler_class],
            )

            handler_cls = getattr(
                module,
                handler_class,
            )

            handler_instance = handler_cls()

            self._handler_cache[
                handler_class
            ] = handler_instance

            return handler_instance

        except ImportError as exc:
            logger.error(
                "Failed to import handler %s: %s",
                handler_class,
                exc,
            )
            return None

        except AttributeError:
            logger.error(
                "Handler class not found: %s",
                handler_class,
            )
            return None

        except Exception as exc:
            logger.exception(
                "Failed to initialize handler %s: %s",
                handler_class,
                exc,
            )
            return None

    def _fallback_response(
        self,
        tenant_settings: Dict[str, Any],
    ) -> BotResponse:
        """
        Generate static fallback response.
        """

        fallback_msg = tenant_settings.get(
            "fallback_message",
            "I didn't understand that. "
            "Could you please rephrase?",
        )

        return BotResponse(
            response_type="text",
            text=fallback_msg,
            metadata={
                "fallback": True
            },
        )

    async def _ai_fallback_response(
        self,
        tenant_settings: Dict[str, Any],
        conversation_id: str,
        user_text: str,
    ) -> BotResponse:
        """
        Attempt an AI-powered fallback response.
        """

        feature_flags = (
            tenant_settings.get(
                "feature_flags",
                {},
            )
            or {}
        )

        if (
            not feature_flags.get(
                "enable_ai_responses",
                False,
            )
            or not ai_fallback.is_available
        ):
            return self._fallback_response(
                tenant_settings
            )

        try:
            session = conversation_manager.get_session(
                conversation_id
            )

            history = None

            if session is not None:
                history = []

                for message in (
                    session.message_history[-10:]
                ):
                    text = message.get(
                        "text",
                        "",
                    )

                    if not text:
                        continue

                    role = (
                        "assistant"
                        if message.get(
                            "direction"
                        )
                        == "outbound"
                        else "user"
                    )

                    history.append(
                        {
                            "role": role,
                            "content": text,
                        }
                    )

            understanding = MessageUnderstanding(
                original_text=user_text,
                normalized_text=user_text,
                intent=IntentType.UNKNOWN,
                intent_confidence=0.0,
            )

            return await ai_fallback.generate(
                understanding=understanding,
                tenant_settings=tenant_settings,
                conversation_history=history,
            )

        except Exception as exc:
            logger.warning(
                "AI fallback failed, using static response: %s",
                exc,
            )

            return self._fallback_response(
                tenant_settings
            )


intent_router = IntentRouter()