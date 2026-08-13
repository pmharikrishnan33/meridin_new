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

        if conversation_context and conversation_context.last_search_filters:
            filters_dict = filters.model_dump()
            merged = ConversationContextManager.merge_filters(
                conversation_context.last_search_filters,
                filters_dict,
            )
            filters = ProductSearchFilters(**merged)

        page_size = 3
        search_limit = 30
        filters.limit = search_limit
        filters.offset = 0

        products = await product_service.search_products(tenant_id, filters)
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
            result_ids=[p.id for p in products],
            page=1,
            page_size=3,
        )

        response_products = [
            product_service.product_to_response(p) for p in products[:3]
        ]

        if conversation_context:
            conversation_context.last_search_filters = filters.model_dump()
            conversation_context.last_search_results = [p.id for p in products]
            conversation_context.current_product = products[0].id
            conversation_context.active_search_key = page["search_key"]
            conversation_context.active_search_offset = page["offset"]
            conversation_context.active_search_total = page["total"]
            conversation_context.active_search_query = filters.query
            conversation_context.active_search_filters = filters.model_dump(exclude_none=True)
            conversation_context.active_search_page = page["page"]
            conversation_context.active_search_page_size = page["page_size"]
            conversation_context.active_search_results = [p.id for p in products]

        if not response_text:
            if len(products) == 1:
                response_text = "I found this item for you:"
            else:
                if len(products) > page_size:
                    response_text = (
                        f"I found more products for you. Here are the first {page_size}:"
                    )
                else:
                    response_text = f"I found {len(products)} items for you:"

        quick_replies = [
            {"label": "More Details", "value": "product_details"},
            {"label": "Filter by Price", "value": "filter_price"},
        ]
        if len(products) > page_size:
            quick_replies.append({"label": "Show more", "value": "show_more"})

        return BotResponse(
            response_type="product_list",
            text=response_text,
            products=response_products,
            quick_replies=quick_replies,
            metadata={
                "search_performed": True,
                "results_count": len(products),
                "filters_applied": filters.model_dump(exclude_none=True),
                "page": 1,
                "page_size": page_size,
                "has_more": len(products) > page_size,
                "default_color": "No specific color",
            },
        )
