"""
Product search handler.

Workflow:

    user search
        ↓
    entity extraction
        ↓
    normalize filters
        ↓
    merge pending conversation state
        ↓
    ask missing required detail
        ↓
    persist pending filters
        ↓
    search inventory
        ↓
    rank candidates
        ↓
    return top products
        ↓
    pagination state
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.handlers.base_handler import BaseHandler

from app.models.schemas import (
    BotResponse,
    ConversationContext,
    EntityType,
    MessageUnderstanding,
    ProductSearchFilters,
)

from app.services.product_service import (
    product_service,
)

from app.services.catalog_metadata_service import (
    catalog_metadata_service,
)

from app.services.inventory_search_service import (
    inventory_search_service,
)

from app.search.zero_result_handler import (
    build_relaxation_message,
    find_best_relaxation,
)


class ProductSearchHandler(BaseHandler):
    """
    Handles clothing product searches.

    Required conversational flow:

        "black shirt"
              ↓
        ask size
              ↓
        "M"
              ↓
        merge:
            category/type = shirt
            color = black
            size = M
              ↓
        search
              ↓
        rank
              ↓
        show top products
    """

    MAX_PRODUCTS_PER_RESPONSE = 3

    DEFAULT_PRODUCTS_PER_RESPONSE = 3

    SEARCH_LIMIT = 100

    # =========================================================
    # MAIN HANDLER
    # =========================================================

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[
            ConversationContext
        ],
    ) -> BotResponse:

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        # =====================================================
        # 1. EXTRACT FILTERS
        # =====================================================

        filters = (
            product_service.entities_to_filters(
                understanding.entities
            )
        )

        # =====================================================
        # 2. NORMALIZE CATALOG VALUES
        # =====================================================

        (
            filters,
            size_clarification,
        ) = await (
            catalog_metadata_service.normalize_filters(
                tenant_id,
                filters,
                understanding.original_text,
            )
        )

        # =====================================================
        # 3. MERGE PENDING SEARCH
        # =====================================================

        pending_filters: Dict[str, Any] = {}

        if conversation_context:

            pending_filters = dict(
                conversation_context.pending_search_filters
                or {}
            )

        if pending_filters:

            current_filters = (
                filters.model_dump(
                    exclude_none=True
                )
            )

            merged_filters = {
                **pending_filters,
                **current_filters,
            }

            filters = ProductSearchFilters(
                **merged_filters
            )

        # =====================================================
        # 4. HANDLE SIZE NORMALIZATION FAILURE
        # =====================================================

        if size_clarification:

            if conversation_context:

                conversation_context.awaiting_entity = (
                    EntityType.SIZE
                )

                conversation_context.pending_search_filters = (
                    filters.model_dump(
                        exclude_none=True
                    )
                )

            return BotResponse(
                response_type="text",
                text=size_clarification,
                products=[],
                quick_replies=[],
                metadata={
                    "needs_clarification": True,
                    "missing": "size",
                    "pending_search_filters": (
                        filters.model_dump(
                            exclude_none=True
                        )
                    ),
                },
            )

        # =====================================================
        # 5. DETERMINE WHAT DETAILS WE HAVE
        # =====================================================

        has_product_query = bool(
            filters.query
        )

        has_category = bool(
            filters.category
        )

        has_type = bool(
            filters.type
        )

        has_color = bool(
            filters.color
        )

        has_size = bool(
            filters.size
        )

        has_search_scope = (
            has_product_query
            or has_category
            or has_type
        )

        # =====================================================
        # 6. MISSING PRODUCT CATEGORY
        # =====================================================

        if not has_search_scope:

            if conversation_context:

                conversation_context.awaiting_entity = (
                    EntityType.CATEGORY
                )

                conversation_context.pending_search_filters = (
                    filters.model_dump(
                        exclude_none=True
                    )
                )

            return BotResponse(
                response_type="text",
                text=(
                    "What type of clothing are you "
                    "looking for? For example, shirt, "
                    "t-shirt, dress, jeans, or kurta."
                ),
                products=[],
                quick_replies=[],
                metadata={
                    "needs_clarification": True,
                    "missing": "category",
                },
            )

        # =====================================================
        # 7. MISSING COLOR
        # =====================================================

        if not has_color:

            if conversation_context:

                conversation_context.awaiting_entity = (
                    EntityType.COLOR
                )

                conversation_context.pending_search_filters = (
                    filters.model_dump(
                        exclude_none=True
                    )
                )

            search_name = (
                filters.category
                or filters.type
                or filters.query
                or "that product"
            )

            return BotResponse(
                response_type="text",
                text=(
                    f"What color would you like "
                    f"for {search_name}?"
                ),
                products=[],
                quick_replies=[],
                metadata={
                    "needs_clarification": True,
                    "missing": "color",
                    "pending_search_filters": (
                        filters.model_dump(
                            exclude_none=True
                        )
                    ),
                },
            )

        # =====================================================
        # 8. MISSING SIZE
        # =====================================================

        if not has_size:

            if conversation_context:

                conversation_context.awaiting_entity = (
                    EntityType.SIZE
                )

                conversation_context.pending_search_filters = (
                    filters.model_dump(
                        exclude_none=True
                    )
                )

            return BotResponse(
                response_type="text",
                text=(
                    "What size are you looking for?"
                ),
                products=[],
                quick_replies=[
                    {
                        "label": "S",
                        "value": "S",
                    },
                    {
                        "label": "M",
                        "value": "M",
                    },
                    {
                        "label": "L",
                        "value": "L",
                    },
                    {
                        "label": "XL",
                        "value": "XL",
                    },
                ],
                metadata={
                    "needs_clarification": True,
                    "missing": "size",
                    "pending_search_filters": (
                        filters.model_dump(
                            exclude_none=True
                        )
                    ),
                },
            )

        # =====================================================
        # 9. PENDING SEARCH IS NOW COMPLETE
        # =====================================================

        if conversation_context:

            conversation_context.awaiting_entity = None

            conversation_context.pending_search_filters = {}

        # =====================================================
        # 10. RESPONSE LIMIT
        # =====================================================

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

        # =====================================================
        # 11. INVENTORY SEARCH
        # =====================================================

        filters.limit = (
            self.SEARCH_LIMIT
        )

        filters.offset = 0

        filters.in_stock_only = True

        products = (
            await product_service.search_products(
                tenant_id,
                filters,
            )
        )

        response_text: Optional[str] = None

        # =====================================================
        # 12. ZERO RESULT RELAXATION
        # =====================================================

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
                relaxed_filters_dict: Dict[
                    str,
                    Any,
                ],
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

                return await (
                    product_service.search_products(
                        tenant_id,
                        relaxed_filters,
                    )
                )

            best_key = await (
                find_best_relaxation(
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
                    for key, value
                    in filters_dict.items()
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

                products = await (
                    product_service.search_products(
                        tenant_id,
                        relaxed_filters,
                    )
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

        # =====================================================
        # 13. STILL NO PRODUCTS
        # =====================================================

        if not products:

            return BotResponse(
                response_type="text",
                text=(
                    "I couldn't find any in-stock "
                    "products matching those details. "
                    "Would you like another color, "
                    "size, or style?"
                ),
                products=[],
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
                    "filters_applied": (
                        filters.model_dump(
                            exclude_none=True
                        )
                    ),
                },
            )

        # =====================================================
        # 14. RANKING
        # =====================================================

        products = (
            product_service.rank_products(
                products=products,
                filters=filters,
            )
        )

        # =====================================================
        # 15. BUILD PAGINATION STATE
        # =====================================================

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

        # =====================================================
        # 16. SAVE CONVERSATION STATE
        # =====================================================

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

            conversation_context.current_product = (
                products[0].id
            )

            conversation_context.current_category = (
                filters.category
                or filters.type
                or conversation_context.current_category
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

        # =====================================================
        # 17. RESPONSE PRODUCTS
        # =====================================================

        response_products = [
            product_service.product_to_response(
                product
            )
            for product in products[
                :page_size
            ]
        ]

        # =====================================================
        # 18. MORE RESULTS
        # =====================================================

        has_more = (
            len(products)
            > page_size
        )

        # =====================================================
        # 19. RESPONSE TEXT
        # =====================================================

        if response_text is None:

            if len(products) == 1:
                response_text = (
                    "I found this product for you:"
                )
            else:
                response_text = (
                    "I found these products for you:"
                )

        # =====================================================
        # 20. QUICK REPLIES
        # =====================================================

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

        # =====================================================
        # 21. FINAL RESPONSE
        # =====================================================

        return BotResponse(
            response_type="product_list",
            text=response_text,
            products=response_products,
            quick_replies=quick_replies,
            metadata={
                "search_performed": True,
                "ranking_applied": True,
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


product_search_handler = ProductSearchHandler()