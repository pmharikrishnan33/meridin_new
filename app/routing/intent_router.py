"""
Intent Router - routes understood messages to appropriate handlers.

Product-search requirement orchestration is delegated to
ProductSearchHandler. The handler is the authority for:

- metadata normalization
- category resolution
- category-specific requirements
- follow-up questions
- product search
- conversational search state

The router owns generic routing, tenant feature checks, pending-state
recovery, and final handler dispatch.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

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
    "more",
    "show more",
    "show_more",
    "next",
    "next page",
    "next_page",
    "more products",
    "more_products",
    "show me more",
    "show_me_more",
}


class IntentRouter:
    """
    Routes incoming messages to the appropriate handler.

    Product search itself is deliberately delegated to
    ProductSearchHandler.
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
        self._handler_cache: Dict[
            str,
            Any,
        ] = {}

    # ============================================================
    # PUBLIC ROUTER
    # ============================================================

    async def route(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_id: str,
    ) -> BotResponse:
        """
        Route an understood message.
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
            understanding.normalized_text
            or understanding.original_text
            or ""
        ).strip().lower()

        # --------------------------------------------------------
        # 1. PAGINATION COMMAND NORMALIZATION
        # --------------------------------------------------------

        if normalized_text in PAGINATION_PHRASES:
            understanding.intent = (
                IntentType.PAGINATION
            )

        # --------------------------------------------------------
        # 2. PENDING ENTITY COLLECTION
        # --------------------------------------------------------

        if (
            session is not None
            and context is not None
            and context.awaiting_entity is not None
        ):
            pending_response = (
                await self._handle_pending_entity(
                    understanding=understanding,
                    tenant_id=tenant_id,
                    tenant_settings=tenant_settings,
                    conversation_id=conversation_id,
                    session=session,
                )
            )

            if pending_response is not None:
                return pending_response

        # --------------------------------------------------------
        # 3. DISABLED INTENTS
        # --------------------------------------------------------

        intent = understanding.intent

        if intent in DISABLED_INTENTS:
            logger.info(
                "Intent %s is disabled in the current Meridin phase",
                intent.value,
            )

            intent = IntentType.UNKNOWN
            understanding.intent = intent

        # --------------------------------------------------------
        # 4. SMART SEARCH OVERRIDE
        # --------------------------------------------------------

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
            if (
                EntityType.PRICE
                in extracted_types
            ):
                logger.info(
                    "Smart override: switched %s to "
                    "product_search because a price filter "
                    "was detected",
                    intent.value,
                )

                intent = (
                    IntentType.PRODUCT_SEARCH
                )

                understanding.intent = intent

                config = get_intent_config(
                    intent
                )

        # --------------------------------------------------------
        # 5. PRODUCT SEARCH
        # --------------------------------------------------------

        if (
            intent
            == IntentType.PRODUCT_SEARCH
        ):
            return await self._execute_product_search(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=tenant_settings,
                conversation_id=conversation_id,
            )

        # --------------------------------------------------------
        # 6. INTENT CONFIDENCE
        # --------------------------------------------------------

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
                intent = (
                    config.fallback_intent
                )
            else:
                intent = IntentType.UNKNOWN

            understanding.intent = intent

            config = get_intent_config(
                intent
            )

        # --------------------------------------------------------
        # 7. TENANT FEATURE FLAGS
        # --------------------------------------------------------

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
                    else:
                        intent = (
                            IntentType.UNKNOWN
                        )

                    understanding.intent = intent

                    config = get_intent_config(
                        intent
                    )

                    break

        # --------------------------------------------------------
        # 8. GENERIC REQUIRED ENTITIES
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # 9. NORMAL HANDLER
        # --------------------------------------------------------

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

            if session is not None:
                session.context._message_history = (
                    session.message_history
                )

            response = await handler.handle(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=tenant_settings,
                conversation_context=context,
            )

            self._add_routing_metadata(
                response=response,
                intent=intent,
                handler=config.handler_class,
                confidence=(
                    understanding.intent_confidence
                ),
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

    # ============================================================
    # PENDING ENTITY HANDLING
    # ============================================================

    async def _handle_pending_entity(
        self,
        *,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_id: str,
        session: Any,
    ) -> Optional[BotResponse]:
        """
        Resolve a pending entity collection state.

        If the requested entity was extracted, route the message back into
        the original intent. If it was not extracted, return the exact
        metadata-defined question rather than allowing the normal intent
        router to misclassify the answer.
        """

        context = session.context

        awaiting_entity = (
            context.awaiting_entity
        )

        if awaiting_entity is None:
            return None

        extracted_entity = self._find_entity(
            understanding.entities,
            awaiting_entity,
        )

        if extracted_entity is None:
            requirement = (
                context.confirmation_context.get(
                    "requirement"
                )
                if context.confirmation_context
                else None
            )

            question = (
                self._question_from_requirement(
                    requirement
                )
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
                    "missing": (
                        awaiting_entity.value
                    ),
                    "awaiting_entity": (
                        awaiting_entity.value
                    ),
                },
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

        # ProductSearchHandler will merge the entity with previous filters.
        # Do not clear the pending state before it has validated the complete
        # metadata requirement chain.
        if (
            understanding.intent
            == IntentType.PRODUCT_SEARCH
        ):
            return await self._execute_product_search(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=tenant_settings,
                conversation_id=conversation_id,
            )

        return None

    @staticmethod
    def _question_from_requirement(
        requirement: Any,
    ) -> Optional[str]:
        if not isinstance(
            requirement,
            dict,
        ):
            return None

        question = str(
            requirement.get(
                "question",
                "",
            )
        ).strip()

        return question or None

    # ============================================================
    # PRODUCT SEARCH
    # ============================================================

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

        Requirement evaluation remains entirely inside the product-search
        handler.
        """

        config = get_intent_config(
            IntentType.PRODUCT_SEARCH
        )

        # --------------------------------------------------------
        # TENANT PRODUCT-SEARCH FEATURE CHECK
        # --------------------------------------------------------

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

                        if fallback_handler:
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

        # --------------------------------------------------------
        # LOAD HANDLER
        # --------------------------------------------------------

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

        if session is not None:
            session.context._message_history = (
                session.message_history
            )

        try:
            response = await handler.handle(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=tenant_settings,
                conversation_context=context,
            )

            # ----------------------------------------------------
            # PERSIST PENDING REQUIREMENT STATE
            # ----------------------------------------------------
            #
            # This was a major workflow hole in the supplied code:
            # ProductSearchHandler returned "missing=size", but nothing
            # stored awaiting_entity=size. Therefore the next "M" could
            # enter the normal intent pipeline instead of continuing the
            # requirement conversation.
            #
            # The router persists the state because it already owns the
            # conversation manager.
            # ----------------------------------------------------

            if (
                session is not None
                and response.metadata.get(
                    "needs_clarification"
                )
            ):
                self._persist_product_search_clarification(
                    session=session,
                    understanding=understanding,
                    response=response,
                )

                await conversation_manager.save_session(
                    session
                )

            elif session is not None:
                # A successful search completes any previous clarification
                # state.
                if response.metadata.get(
                    "search_performed"
                ):
                    session.context.awaiting_entity = None
                    session.context.awaiting_confirmation = False
                    session.context.confirmation_context = {}

                    await conversation_manager.save_session(
                        session
                    )

            self._add_routing_metadata(
                response=response,
                intent=IntentType.PRODUCT_SEARCH,
                handler=config.handler_class,
                confidence=(
                    understanding.intent_confidence
                ),
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

    def _persist_product_search_clarification(
        self,
        *,
        session: Any,
        understanding: MessageUnderstanding,
        response: BotResponse,
    ) -> None:
        """
        Persist the first missing product-search requirement.
        """

        missing = response.metadata.get(
            "missing"
        )

        if not missing:
            return

        try:
            entity_type = EntityType(
                str(missing)
            )
        except ValueError:
            logger.warning(
                "Product search returned unknown "
                "missing requirement: %s",
                missing,
            )
            return

        requirement = (
            response.metadata.get(
                "requirement"
            )
            or {
                "key": str(
                    missing
                ),
                "question": response.text
                or "",
            }
        )

        session.context.awaiting_entity = (
            entity_type
        )

        session.context.awaiting_confirmation = (
            False
        )

        session.context.confirmation_context = {
            "intent": IntentType.PRODUCT_SEARCH.value,
            "requirement": requirement,
            "missing_entities": [
                str(missing)
            ],
        }

    # ============================================================
    # GENERIC ENTITY VALIDATION
    # ============================================================

    @staticmethod
    def _find_entity(
        entities: Any,
        entity_type: EntityType,
    ) -> Optional[ExtractedEntity]:
        """
        Return the highest-confidence matching entity.
        """

        candidates = [
            entity
            for entity in (
                entities or []
            )
            if entity.entity_type
            == entity_type
        ]

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda entity: (
                entity.confidence,
                max(
                    0,
                    entity.end_pos
                    - entity.start_pos,
                ),
            ),
        )

    @staticmethod
    def _fallback_question_for_entity(
        entity_type: EntityType,
    ) -> str:
        """
        Fallback question when metadata does not contain a question.
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
        context: Any = None,
    ) -> list:
        """
        Check generic handler-level entity requirements.
        """

        available_entities = {
            entity.entity_type
            for entity in (
                understanding.entities
                or []
            )
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
            for entity_type in (
                required_entities or []
            )
            if entity_type
            not in available_entities
        ]

    async def _handle_missing_entities(
        self,
        understanding: MessageUnderstanding,
        missing_entities: list,
        tenant_settings: Dict[str, Any],
        conversation_id: str,
    ) -> BotResponse:
        """
        Persist generic missing-entity state.
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

            session.context.awaiting_confirmation = (
                False
            )

            session.context.confirmation_context = {
                "intent": understanding.intent.value,
                "missing_entities": [
                    entity.value
                    for entity
                    in missing_entities
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

        for entity in (
            missing_entities
        ):
            entity_name = entity_names.get(
                entity.value,
                entity.value,
            )

            questions.append(
                f"Could you please specify {entity_name}?"
            )

        return BotResponse(
            response_type="text",
            text=" ".join(questions),
            metadata={
                "needs_clarification": True,
                "missing_entities": [
                    entity.value
                    for entity
                    in missing_entities
                ],
            },
        )

    # ============================================================
    # HANDLER LOADING
    # ============================================================

    async def _get_handler(
        self,
        handler_class: str,
    ):
        """
        Dynamically load and cache a handler instance.
        """

        if (
            handler_class
            in self._handler_cache
        ):
            return self._handler_cache[
                handler_class
            ]

        module_path = (
            self._HANDLER_MODULES.get(
                handler_class
            )
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
                fromlist=[
                    handler_class
                ],
            )

            handler_cls = getattr(
                module,
                handler_class,
            )

            handler_instance = (
                handler_cls()
            )

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

    # ============================================================
    # RESPONSE HELPERS
    # ============================================================

    @staticmethod
    def _add_routing_metadata(
        *,
        response: BotResponse,
        intent: IntentType,
        handler: str,
        confidence: float,
    ) -> None:
        """
        Add routing information without replacing handler-generated
        metadata.
        """

        response.metadata.update(
            {
                "intent": intent.value,
                "handler": handler,
                "confidence": confidence,
            }
        )

    def _fallback_response(
        self,
        tenant_settings: Dict[str, Any],
    ) -> BotResponse:
        """
        Generate static tenant-configured fallback.
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

            understanding = (
                MessageUnderstanding(
                    original_text=user_text,
                    normalized_text=user_text,
                    intent=IntentType.UNKNOWN,
                    intent_confidence=0.0,
                )
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