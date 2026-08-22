from typing import Dict, Any, Optional
from app.handlers.base_handler import BaseHandler
from app.models.schemas import (
    MessageUnderstanding,
    ConversationContext,
    BotResponse,
    ProductSearchFilters,
)
from app.services.product_service import product_service
from app.services.inventory_search_service import inventory_search_service
from app.services.catalog_metadata_service import catalog_metadata_service
from app.conversation.context import ConversationContextManager
from app.search.zero_result_handler import find_best_relaxation, build_relaxation_message
from app.utils.logger import logger

class ProductSearchHandler(BaseHandler):
    """
    Handles PRODUCT_SEARCH intents.
    Extracts entities, builds search filters, queries products,
    and returns a structured product list response.
    """
    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:
        
        filters = product_service.entities_to_filters(understanding.entities)
        filters, size_clarification = await catalog_metadata_service.normalize_filters(
            tenant_id,
            filters,
            understanding.original_text,
        )

        if size_clarification:
            return BotResponse(
                response_type="text",
                text=size_clarification,
                metadata={"needs_clarification": True, "missing": "size"},
            )

        if (
            conversation_context
            and conversation_context.last_search_filters
            and self._should_refine_previous_search(filters)
        ):
            filters_dict = filters.model_dump(exclude_none=True)
            merged = ConversationContextManager.merge_filters(
                conversation_context.last_search_filters,
                filters_dict,
            )
            filters = ProductSearchFilters(**merged)

        configured_limit = (tenant_settings.get("feature_flags", {}) or {}).get(
            "max_products_per_response", 5
        )
        try:
            page_size = max(1, min(int(configured_limit), 20))
        except (TypeError, ValueError):
            page_size = 3
        search_limit = 100
        filters.limit = search_limit
        filters.offset = 0

        products = await product_service.search_products(
            tenant_id,
            filters
        )
        response_text = None

        # --- NEW: Zero-Result Fallback (Auto-select available color/filter) ---
        if not products:
            filters_dict = filters.model_dump(exclude_none=True)
            filters_dict.pop("limit", None)
            filters_dict.pop("offset", None)

            async def search_fn(relaxed_filters_dict):
                rel_filters = ProductSearchFilters(**relaxed_filters_dict)
                rel_filters.limit = filters.limit
                return await product_service.search_products(tenant_id, rel_filters)

            best_key = await find_best_relaxation(
                query=understanding.original_text,
                filters=filters_dict,
                search_fn=search_fn
            )

            if best_key:
                relaxed_dict = {k: v for k, v in filters_dict.items() if k != best_key}
                relaxed_filters = ProductSearchFilters(**relaxed_dict)
                relaxed_filters.limit = filters.limit
                relaxed_filters.offset = 0
                products = await product_service.search_products(tenant_id, relaxed_filters)
                if products:
                    filters = relaxed_filters
                
                response_text = build_relaxation_message(
                    query=understanding.original_text,
                    filters=filters_dict,
                    removed_key=best_key,
                    removed_value=filters_dict[best_key]
                )

        if not products:
            return BotResponse(
                response_type="text",
                text="I couldn't find any products matching your search. Could you try different keywords or filters?",
                quick_replies=[
                    {"label": "View All Categories", "value": "browse_categories"},
                    {"label": "Popular Items", "value": "popular_items"},
                ],
                metadata={"search_performed": True, "results_count": 0},
            )

        page = inventory_search_service.build_search_page(
            tenant_id=tenant_id,
            filters=filters,
            result_ids=[
                p.id for p in products
            ],
            page=1,
            page_size=3,
        )

        # =========================================================
        # SAVE PAGINATION STATE
        # =========================================================

        if conversation_context:

            conversation_context.last_search_filters = (
                filters.model_dump()
            )

            conversation_context.last_search_results = [
                p.id for p in products
            ]

            conversation_context.current_product = (
                products[0].id
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

            conversation_context.active_search_page_size = 3

            # IMPORTANT:
            # Keep the COMPLETE ranked result list.
            conversation_context.active_search_results = [
                p.id for p in products
            ]

        # =========================================================
        # FIRST THREE PRODUCTS ONLY
        # =========================================================

        response_products = [
            product_service.product_to_response(
                product
            )
            for product in products[:3]
        ]

        has_more = len(products) > 3

        # =========================================================
        # RESPONSE TEXT
        # =========================================================

        if len(products) == 1:

            response_text = (
                "I found this item for you:"
            )

        else:

            response_text = (
                "I found these products for you:"
            )

        # =========================================================
        # ONLY SHOW MORE BUTTON
        # =========================================================

        quick_replies = []

        if has_more:

            quick_replies = [
                {
                    "label": "Show more",
                    "value": "show_more",
                }
            ]

        # =========================================================
        # RESPONSE
        # =========================================================

        return BotResponse(
            response_type="product_list",

            text=response_text,

            products=response_products,

            quick_replies=quick_replies,

            metadata={
                "search_performed": True,

                "results_count": len(products),

                "filters_applied":
                    filters.model_dump(
                        exclude_none=True
                    ),

                "page": 1,

                "page_size": 3,

                "has_more": has_more,

                "total_results": len(products),

                "default_color":
                    "No specific color",
            },
        )

    @staticmethod
    def _should_refine_previous_search(filters: ProductSearchFilters) -> bool:
        """Only inherit context for follow-up filters, not a new product search."""
        return not any((filters.query, filters.category, filters.type))
