from typing import Any, Dict, Optional

from app.conversation.context import ConversationContextManager
from app.conversation.requirements import (
    conversation_requirement_engine,
)
from app.handlers.base_handler import BaseHandler
from app.models.schemas import (
    BotResponse,
    ConversationContext,
    IntentType,
    MessageUnderstanding,
    ProductSearchFilters,
)
from app.search.zero_result_handler import (
    build_relaxation_message,
    find_best_relaxation,
)
from app.services.catalog_metadata_service import (
    catalog_metadata_service,
)
from app.services.inventory_search_service import (
    inventory_search_service,
)
from app.services.product_service import product_service


def _rank_products(
    products,
    filters: ProductSearchFilters,
):
    """
    Rank already tenant-filtered products before display.

    ProductService already performs the primary deterministic ranking.
    This secondary ranking is intentionally lightweight and only
    reorders the returned candidates.
    """

    if not products:
        return []

    query_tokens = set(
        (filters.query or "").lower().split()
    )

    def score(product):
        title = (
            product.title or ""
        ).lower()

        searchable_text = " ".join(
            part
            for part in (
                product.title,
                product.description,
                product.category,
                product.type,
                product.brand,
                product.material,
                product.fit,
                product.gender,
            )
            if part
        ).lower()

        query_score = 0.0

        if query_tokens:
            title_matches = sum(
                1
                for token in query_tokens
                if token in title
            )

            overall_matches = sum(
                1
                for token in query_tokens
                if token in searchable_text
            )

            query_score = (
                0.7
                * (
                    title_matches
                    / len(query_tokens)
                )
                + 0.3
                * (
                    overall_matches
                    / len(query_tokens)
                )
            )

        attribute_checks = 0
        attribute_matches = 0

        scalar_filters = (
            (
                filters.category,
                product.category,
            ),
            (
                filters.type,
                product.type,
            ),
            (
                filters.brand,
                product.brand,
            ),
            (
                filters.material,
                product.material,
            ),
            (
                filters.fit,
                product.fit,
            ),
            (
                filters.gender,
                product.gender,
            ),
            (
                filters.age_group,
                product.age_group,
            ),
        )

        for requested, actual in scalar_filters:
            if requested:
                attribute_checks += 1

                if (
                    actual
                    and requested.strip().lower()
                    == actual.strip().lower()
                ):
                    attribute_matches += 1

        if filters.color:
            attribute_checks += 1

            if any(
                filters.color.strip().lower()
                == str(value).strip().lower()
                for value in (
                    product.color or []
                )
            ):
                attribute_matches += 1

        if filters.size:
            attribute_checks += 1

            if any(
                filters.size.strip().lower()
                == str(value).strip().lower()
                for value in (
                    product.size or []
                )
            ):
                attribute_matches += 1

        attribute_score = (
            attribute_matches
            / attribute_checks
            if attribute_checks
            else 0.0
        )

        featured_score = (
            1.0
            if product.is_featured
            else 0.0
        )

        stock_score = min(
            max(
                product.stock,
                0,
            )
            / 10.0,
            1.0,
        )

        return (
            (
                0.60 * query_score
                + 0.25 * attribute_score
                + 0.10 * featured_score
                + 0.05 * stock_score
            ),
            product.created_at.timestamp()
            if product.created_at
            else 0.0,
        )

    return sorted(
        products,
        key=score,
        reverse=True,
    )


class ProductSearchHandler(BaseHandler):
    """
    Handles PRODUCT_SEARCH.

    This handler is the single authority for the product-search
    conversation workflow.

    It does not hardcode:

        - which category requires which attribute
        - which dress type should be requested
        - which shirt size should be requested
        - category-specific questions
        - category-specific options

    Those rules come from inventory_metadata.category_requirements.
    """

    MAX_PRODUCTS_PER_RESPONSE = 3
    DEFAULT_PRODUCTS_PER_RESPONSE = 3
    SEARCH_LIMIT = 100

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:

        # =========================================================
        # 1. BUILD FILTERS FROM CURRENT MESSAGE
        # =========================================================

        filters = (
            product_service.entities_to_filters(
                understanding.entities
            )
        )

        # =========================================================
        # 2. MERGE PREVIOUS CONVERSATION FILTERS
        # =========================================================
        #
        # IMPORTANT:
        #
        # query/category represent a new product scope.
        #
        # type, color, size, gender, fit, etc. can be refinements
        # or answers to metadata requirements and therefore MUST
        # inherit the previous search context.
        #
        # Example:
        #
        #   black dress
        #
        # followed by:
        #
        #   maxi
        #
        # must become:
        #
        #   black + dress + maxi
        #
        # NOT:
        #
        #   maxi only
        #
        # =========================================================

        if (
            conversation_context
            and conversation_context.last_search_filters
        ):
            incoming_has_new_product_scope = any(
                (
                    filters.query,
                    filters.category,
                )
            )

            if not incoming_has_new_product_scope:
                previous_filters = (
                    ProductSearchFilters(
                        **conversation_context.last_search_filters
                    )
                )

                merged_dict = (
                    ConversationContextManager.merge_filters(
                        previous_filters.model_dump(
                            exclude_none=True
                        ),
                        filters.model_dump(
                            exclude_none=True
                        ),
                    )
                )

                filters = ProductSearchFilters(
                    **merged_dict
                )

        # =========================================================
        # 3. NORMALIZE METADATA
        # =========================================================
        #
        # This resolves:
        #
        #   department
        #   category
        #   category_id
        #   department_id
        #   color
        #   color_id
        #   size
        #   size_id
        #   size_group
        #   type aliases
        #
        # using the tenant's inventory_metadata document.
        #
        # =========================================================

        (
            filters,
            _,
        ) = await (
            catalog_metadata_service.normalize_filters(
                tenant_id,
                filters,
                understanding.original_text,
            )
        )

        # =========================================================
        # 4. LOAD CATEGORY-SPECIFIC REQUIREMENTS
        # =========================================================
        #
        # This is the critical step.
        #
        # The category ID is resolved first and then metadata is
        # queried for the requirements belonging to that category.
        #
        # Example metadata:
        #
        # category_requirements["201"]
        #
        # can define:
        #
        #   size -> required
        #
        # while another category can define:
        #
        #   type -> required
        #
        # No category is hardcoded here.
        #
        # =========================================================

        requirements = (
            await catalog_metadata_service.get_category_requirements(
                tenant_id=tenant_id,
                category_id=filters.category_id,
                category=filters.category,
            )
        )

        # =========================================================
        # 5. CHECK REQUIREMENTS
        # =========================================================

        (
            ready_to_search,
            missing_requirement,
            question,
        ) = conversation_requirement_engine.evaluate(
            current_filters=filters.model_dump(
                exclude_none=True
            ),
            requirements=requirements,
            context=conversation_context,
        )

        if not ready_to_search:
            if conversation_context:
                entity_type = (
                    conversation_requirement_engine
                    .entity_type_for_requirement(
                        missing_requirement
                    )
                    if missing_requirement
                    else None
                )

                conversation_context.awaiting_entity = (
                    entity_type
                )

                conversation_context.awaiting_confirmation = (
                    False
                )

                missing_key = (
                    str(
                        missing_requirement.get(
                            "key",
                            "",
                        )
                    )
                    if missing_requirement
                    else ""
                )

                conversation_context.confirmation_context = {
                    "intent": (
                        IntentType.PRODUCT_SEARCH.value
                    ),
                    "missing_entities": (
                        [
                            entity_type.value
                        ]
                        if entity_type
                        else []
                    ),
                    "missing_attributes": (
                        [missing_key]
                        if missing_key
                        else []
                    ),
                    "requirement": (
                        dict(
                            missing_requirement
                        )
                        if missing_requirement
                        else {}
                    ),
                }

                # Save the normalized filters so the next user
                # message can refine this exact search.
                conversation_context.last_search_filters = (
                    filters.model_dump(
                        exclude_none=True
                    )
                )

                if filters.category:
                    conversation_context.current_category = (
                        filters.category
                    )

                if filters.query:
                    conversation_context.current_product = (
                        filters.query
                    )

            return BotResponse(
                response_type="text",
                text=(
                    question
                    or (
                        "Could you please provide "
                        "the missing information?"
                    )
                ),
                metadata={
                    "needs_clarification": True,
                    "missing": (
                        missing_requirement.get(
                            "key"
                        )
                        if missing_requirement
                        else None
                    ),
                    "missing_requirement": (
                        missing_requirement
                    ),
                    "filters": filters.model_dump(
                        exclude_none=True
                    ),
                },
            )

        # =========================================================
        # 6. REQUIREMENTS COMPLETE
        # =========================================================

        if conversation_context:
            conversation_context.last_search_filters = (
                filters.model_dump(
                    exclude_none=True
                )
            )

            if filters.category:
                conversation_context.current_category = (
                    filters.category
                )

            if filters.query:
                conversation_context.current_product = (
                    filters.query
                )

            conversation_context.awaiting_entity = None
            conversation_context.awaiting_confirmation = False
            conversation_context.confirmation_context = {}

        # =========================================================
        # 7. TENANT RESPONSE LIMIT
        # =========================================================

        feature_flags = (
            tenant_settings.get(
                "feature_flags",
                {},
            )
            or {}
        )

        configured_page_size = (
            feature_flags.get(
                "max_products_per_response",
                self.DEFAULT_PRODUCTS_PER_RESPONSE,
            )
        )

        try:
            page_size = max(
                1,
                min(
                    int(
                        configured_page_size
                    ),
                    self.MAX_PRODUCTS_PER_RESPONSE,
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            page_size = (
                self.DEFAULT_PRODUCTS_PER_RESPONSE
            )

        # =========================================================
        # 8. SEARCH
        # =========================================================

        filters.limit = self.SEARCH_LIMIT
        filters.offset = 0
        filters.in_stock_only = True

        products = (
            await product_service.search_products(
                tenant_id,
                filters,
            )
        )

        products = _rank_products(
            products,
            filters,
        )

        response_text: Optional[str] = None

        # =========================================================
        # 9. ZERO-RESULT RELAXATION
        # =========================================================

        if not products:
            filters_dict = (
                filters.model_dump(
                    exclude_none=True
                )
            )

            filters_dict.pop(
                "limit",
                None,
            )

            filters_dict.pop(
                "offset",
                None,
            )

            async def search_fn(
                relaxed_filters_dict: Dict[str, Any],
            ):
                relaxed_filters = (
                    ProductSearchFilters(
                        **relaxed_filters_dict
                    )
                )

                relaxed_filters.limit = (
                    self.SEARCH_LIMIT
                )

                relaxed_filters.offset = 0
                relaxed_filters.in_stock_only = True

                results = (
                    await product_service.search_products(
                        tenant_id,
                        relaxed_filters,
                    )
                )

                return _rank_products(
                    results,
                    relaxed_filters,
                )

            best_key = (
                await find_best_relaxation(
                    query=(
                        understanding.original_text
                    ),
                    filters=filters_dict,
                    search_fn=search_fn,
                )
            )

            if best_key:
                relaxed_dict = {
                    key: value
                    for key, value in (
                        filters_dict.items()
                    )
                    if key != best_key
                }

                relaxed_filters = (
                    ProductSearchFilters(
                        **relaxed_dict
                    )
                )

                relaxed_filters.limit = (
                    self.SEARCH_LIMIT
                )

                relaxed_filters.offset = 0
                relaxed_filters.in_stock_only = True

                products = (
                    await product_service.search_products(
                        tenant_id,
                        relaxed_filters,
                    )
                )

                products = _rank_products(
                    products,
                    relaxed_filters,
                )

                if products:
                    filters = relaxed_filters

                    response_text = (
                        build_relaxation_message(
                            query=(
                                understanding.original_text
                            ),
                            filters=filters_dict,
                            removed_key=best_key,
                            removed_value=(
                                filters_dict[
                                    best_key
                                ]
                            ),
                        )
                    )

        # =========================================================
        # 10. STILL NO PRODUCTS
        # =========================================================

        if not products:
            return BotResponse(
                response_type="text",
                text=(
                    "I couldn't find any products "
                    "matching your search. "
                    "Could you try a different "
                    "color, size, type, or category?"
                ),
                quick_replies=[
                    {
                        "label": "Search Again",
                        "value": (
                            "__COMMAND__:search_again"
                        ),
                    }
                ],
                metadata={
                    "search_performed": True,
                    "results_count": 0,
                    "filters": filters.model_dump(
                        exclude_none=True
                    ),
                },
            )

        # =========================================================
        # 11. PAGINATION
        # =========================================================

        page = (
            inventory_search_service.build_search_page(
                tenant_id=tenant_id,
                filters=filters,
                result_ids=[
                    product.id
                    for product in products
                ],
                page=1,
                page_size=page_size,
            )
        )

        # =========================================================
        # 12. SAVE CONVERSATION STATE
        # =========================================================

        if conversation_context:
            conversation_context.last_search_filters = (
                filters.model_dump(
                    exclude_none=True
                )
            )

            conversation_context.last_search_results = [
                product.id
                for product in products
            ]

            # Keep current_product as the user's search product
            # when available. Do not replace it with a product ID.
            if filters.query:
                conversation_context.current_product = (
                    filters.query
                )

            conversation_context.active_search_key = (
                page["search_key"]
            )

            conversation_context.active_search_offset = (
                page["offset"]
            )

            conversation_context.active_search_total = (
                page["total"]
            )

            conversation_context.active_search_query = (
                filters.query
            )

            conversation_context.active_search_filters = (
                filters.model_dump(
                    exclude_none=True
                )
            )

            conversation_context.active_search_page = 1

            conversation_context.active_search_page_size = (
                page_size
            )

            conversation_context.active_search_results = [
                product.id
                for product in products
            ]

            conversation_context.awaiting_entity = None
            conversation_context.awaiting_confirmation = False
            conversation_context.confirmation_context = {}

        # =========================================================
        # 13. BUILD PRODUCT RESPONSE
        # =========================================================

        response_products = [
            product_service.product_to_response(
                product
            )
            for product in products[:page_size]
        ]

        has_more = (
            len(products)
            > page_size
        )

        if response_text is None:
            if len(products) == 1:
                response_text = (
                    "I found this item for you:"
                )
            else:
                response_text = (
                    "I found these products for you:"
                )

        quick_replies = []

        if has_more:
            quick_replies.append(
                {
                    "label": "Show more",
                    "value": (
                        "__COMMAND__:show_more"
                    ),
                }
            )

        # =========================================================
        # 14. FINAL RESPONSE
        # =========================================================

        return BotResponse(
            response_type="product_list",
            text=response_text,
            products=response_products,
            quick_replies=quick_replies,
            metadata={
                "search_performed": True,
                "results_count": len(products),
                "filters_applied": (
                    filters.model_dump(
                        exclude_none=True
                    )
                ),
                "page": 1,
                "page_size": page_size,
                "has_more": has_more,
                "total_results": len(products),
            },
        )

    @staticmethod
    def _should_refine_previous_search(
        filters: ProductSearchFilters,
    ) -> bool:
        """
        Determine whether the current message is a refinement.

        A message such as:

            M
            black
            maxi
            casual
            slim fit

        should normally refine the existing search.

        A message containing a new query/category represents a new
        product scope.
        """

        return not any(
            (
                filters.query,
                filters.category,
            )
        )


product_search_handler = (
    ProductSearchHandler()
)