"""
Intent Router - routes understood messages to appropriate handlers.
"""

from typing import Any, Dict

from app.ai.fallback import ai_fallback
from app.conversation.manager import conversation_manager
from app.conversation.requirements import (
    conversation_requirement_engine,
)
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
    Routes incoming messages to appropriate handlers.
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
        Route a message to the appropriate handler.

        Product-search conversations are handled by the conversation
        requirement engine before ProductSearchHandler is called.
        """

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

        normalized_text = (
            understanding.normalized_text
            or ""
        ).strip().lower()

        if normalized_text in PAGINATION_PHRASES:
            understanding.intent = (
                IntentType.PAGINATION
            )

        # ============================================================
        # 1. CONTINUE A PENDING ENTITY COLLECTION
        # ============================================================
        #
        # If the previous bot message asked:
        #
        #   "What size would you like?"
        #
        # and the customer replies:
        #
        #   "L"
        #
        # we MUST interpret "L" as a SIZE answer before running
        # normal intent routing.
        #
        if (
            session is not None
            and context is not None
            and context.awaiting_entity is not None
        ):
            awaiting_entity = (
                context.awaiting_entity
            )

            extracted_entity = (
                self._find_entity(
                    understanding.entities,
                    awaiting_entity,
                )
            )

            if extracted_entity is not None:
                logger.info(
                    "Resolved pending entity %s from "
                    "follow-up message",
                    awaiting_entity.value,
                )

                # Force the conversation back to the intent that
                # created the requirement.
                pending_intent = (
                    context.confirmation_context.get(
                        "intent"
                    )
                    if context.confirmation_context
                    else None
                )

                if pending_intent:
                    try:
                        understanding.intent = (
                            IntentType(
                                pending_intent
                            )
                        )
                    except ValueError:
                        understanding.intent = (
                            IntentType.PRODUCT_SEARCH
                        )
                else:
                    understanding.intent = (
                        IntentType.PRODUCT_SEARCH
                    )

                # Keep the existing entities from the current message.
                # The requirement engine will merge them with the
                # filters already stored in the conversation context.
                context.awaiting_entity = None
                context.awaiting_confirmation = False
                context.confirmation_context = {}

                await conversation_manager.save_session(
                    session
                )

            else:
                # The user answered, but not with the requested entity.
                # Ask the same question rather than incorrectly routing
                # the message as a completely new intent.
                question = (
                    conversation_requirement_engine.question_for(
                        awaiting_entity
                    )
                )

                return BotResponse(
                    response_type="text",
                    text=question,
                    metadata={
                        "needs_clarification": True,
                        "missing": awaiting_entity.value,
                        "awaiting_entity": awaiting_entity.value,
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
                    "Smart override: switched %s to product_search "
                    "because a price filter was detected",
                    intent.value,
                )

                intent = IntentType.PRODUCT_SEARCH
                understanding.intent = intent

                config = get_intent_config(
                    intent
                )

        # ============================================================
        # 4. PRODUCT SEARCH CONVERSATION
        # ============================================================
        #
        # This is the important new gate.
        #
        # ProductSearchHandler should only run when the requirements
        # engine says that the conversation has enough information.
        #
        if intent == IntentType.PRODUCT_SEARCH:
            return await self._route_product_search(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=tenant_settings,
                conversation_id=conversation_id,
                session=session,
            )

        # ============================================================
        # 5. NORMAL INTENT ROUTING
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
            for feature in (
                config.allowed_tenant_features
            ):
                if not check_tenant_feature(
                    tenant_settings,
                    feature,
                ):
                    logger.info(
                        "Tenant feature %s disabled",
                        feature,
                    )

                    if config.fallback_intent:
                        intent = (
                            config.fallback_intent
                        )
                        understanding.intent = intent
                        config = get_intent_config(
                            intent
                        )
                    else:
                        intent = (
                            IntentType.UNKNOWN
                        )
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
                    "confidence": understanding.intent_confidence,
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

    async def _route_product_search(
        self,
        *,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_id: str,
        session,
    ) -> BotResponse:
        """
        Handle conversational product search.

        Existing search filters are merged with entities from the
        current message. The requirement engine decides whether the
        product search can proceed.
        """

        if session is None:
            return BotResponse(
                response_type="text",
                text=(
                    "I couldn't start the product search. "
                    "Please try again."
                ),
                metadata={
                    "search_error": True,
                },
            )

        context = session.context

        new_filters = (
            conversation_requirement_engine.entity_to_filters(
                understanding.entities
            )
        )

        existing_filters = dict(
            context.last_search_filters or {}
        )

        merged_filters = (
            conversation_requirement_engine.merge_filters(
                existing_filters,
                new_filters,
            )
        )

        # ============================================================
        # NEW SEARCH DETECTION
        # ============================================================
        #
        # If the incoming message contains a new product/category,
        # start a new search rather than inheriting an unrelated
        # previous search.
        #

        current_query = merged_filters.get(
            "query"
        )
        current_category = merged_filters.get(
            "category"
        )

        new_query = new_filters.get(
            "query"
        )
        new_category = new_filters.get(
            "category"
        )

        if (
            (new_query and current_query != new_query)
            or (
                new_category
                and current_category != new_category
            )
        ):
            if (
                context.last_search_filters
                and (
                    new_query
                    or new_category
                )
            ):
                previous_query = (
                    context.last_search_filters.get(
                        "query"
                    )
                )

                previous_category = (
                    context.last_search_filters.get(
                        "category"
                    )
                )

                if (
                    (
                        new_query
                        and previous_query
                        and new_query.lower()
                        != previous_query.lower()
                    )
                    or (
                        new_category
                        and previous_category
                        and new_category.lower()
                        != previous_category.lower()
                    )
                ):
                    merged_filters = dict(
                        new_filters
                    )

        # ============================================================
        # STORE CURRENT REQUIREMENTS
        # ============================================================

        context.last_search_filters = dict(
            merged_filters
        )

        if merged_filters.get("category"):
            context.current_category = (
                merged_filters["category"]
            )

        if merged_filters.get("query"):
            context.current_product = (
                merged_filters["query"]
            )

        # ============================================================
        # CHECK REQUIREMENTS
        # ============================================================

        (
            ready_to_search,
            missing_entity,
            question,
        ) = conversation_requirement_engine.evaluate(
            current_filters=merged_filters,
            context=context,
        )

        if not ready_to_search:
            context.awaiting_entity = (
                missing_entity
            )

            context.awaiting_confirmation = False

            context.confirmation_context = {
                "intent": IntentType.PRODUCT_SEARCH.value,
                "missing_entities": [
                    missing_entity.value
                ]
                if missing_entity
                else [],
            }

            await conversation_manager.save_session(
                session
            )

            return BotResponse(
                response_type="text",
                text=question,
                metadata={
                    "needs_clarification": True,
                    "missing": (
                        missing_entity.value
                        if missing_entity
                        else None
                    ),
                    "filters": merged_filters,
                },
            )

        # ============================================================
        # SEARCH IS NOW ALLOWED
        # ============================================================

        context.awaiting_entity = None
        context.awaiting_confirmation = False
        context.confirmation_context = {}

        # Build an understanding object containing all active
        # conversational filters so ProductSearchHandler can search
        # using the complete request.
        understanding.entities = (
            self._filters_to_entities(
                merged_filters,
                understanding.entities,
            )
        )

        await conversation_manager.save_session(
            session
        )

        config = get_intent_config(
            IntentType.PRODUCT_SEARCH
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

        try:
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
                    "intent": IntentType.PRODUCT_SEARCH.value,
                    "handler": config.handler_class,
                    "confidence": understanding.intent_confidence,
                    "requirements_complete": True,
                    "search_filters": merged_filters,
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
            if entity.entity_type
            == entity_type
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
    def _filters_to_entities(
        filters: Dict[str, Any],
        existing_entities,
    ):
        """
        Convert merged search filters back into entities so the
        existing ProductSearchHandler can continue to operate without
        requiring a complete rewrite.
        """

        entities = list(
            existing_entities or []
        )

        existing_types = {
            entity.entity_type
            for entity in entities
        }

        mapping = {
            "category": EntityType.CATEGORY,
            "query": EntityType.PRODUCT,
            "color": EntityType.COLOR,
            "size": EntityType.SIZE,
            "fit": EntityType.FIT,
            "brand": EntityType.BRAND,
            "material": EntityType.MATERIAL,
            "gender": EntityType.GENDER,
        }

        for key, entity_type in mapping.items():
            value = filters.get(key)

            if not value:
                continue

            # Replace any existing entity of this type with the
            # authoritative conversational value.
            entities = [
                entity
                for entity in entities
                if entity.entity_type != entity_type
            ]

            entities.append(
                ExtractedEntity(
                    entity_type=entity_type,
                    value=str(value),
                    normalized_value=str(value),
                    confidence=1.0,
                )
            )

        # Price needs to preserve its operator metadata.
        if filters.get("max_price") is not None:
            entities = [
                entity
                for entity in entities
                if entity.entity_type != EntityType.PRICE
            ]

            entities.append(
                ExtractedEntity(
                    entity_type=EntityType.PRICE,
                    value=str(
                        filters["max_price"]
                    ),
                    normalized_value=str(
                        filters["max_price"]
                    ),
                    confidence=1.0,
                    metadata={
                        "operator": "max"
                    },
                )
            )

        elif filters.get("min_price") is not None:
            entities = [
                entity
                for entity in entities
                if entity.entity_type != EntityType.PRICE
            ]

            entities.append(
                ExtractedEntity(
                    entity_type=EntityType.PRICE,
                    value=str(
                        filters["min_price"]
                    ),
                    normalized_value=str(
                        filters["min_price"]
                    ),
                    confidence=1.0,
                    metadata={
                        "operator": "min"
                    },
                )
            )

        return entities

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

        session = (
            conversation_manager.get_session(
                conversation_id
            )
        )

        if (
            session is not None
            and missing_entities
        ):
            missing_entity = (
                missing_entities[0]
            )

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
            session = (
                conversation_manager.get_session(
                    conversation_id
                )
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