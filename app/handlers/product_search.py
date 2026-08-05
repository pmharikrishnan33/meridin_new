"""
Product search handler - handles product search intents.
"""

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

        # Convert entities to search filters
        filters = product_service.entities_to_filters(understanding.entities)

        # If conversation context exists, merge with last search filters
        if conversation_context and conversation_context.last_search_filters:
            filters_dict = filters.model_dump()
            merged = ConversationContextManager.merge_filters(
                conversation_context.last_search_filters,
                filters_dict,
            )
            filters = ProductSearchFilters(**merged)

        # Apply tenant max products limit while preserving enough room for
        # page-1 + follow-up "show more" pagination.
        max_products = tenant_settings.get("feature_flags", {}).get(
            "max_products_per_response", 5
        )
        page_window = 3
        filters.limit = min(max(filters.limit, page_window * 2), max(max_products, page_window * 2))

        # Search products
        products = await product_service.search_products(tenant_id, filters)

        if not products:
            return BotResponse(
                response_type="text",
                text="I couldn't find any products matching your search. "
                     "Could you try different keywords or filters?",
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

        # Convert to response products
        response_products = [
            product_service.product_to_response(p) for p in products[:3]
        ]

        # Update conversation context with search
        if conversation_context:
            conversation_context.last_search_filters = filters.model_dump()
            conversation_context.last_search_results = [p.id for p in products]
            conversation_context.active_search_key = page["search_key"]
            conversation_context.active_search_offset = page["offset"]
            conversation_context.active_search_total = page["total"]
            conversation_context.active_search_query = filters.query
            conversation_context.active_search_filters = filters.model_dump(exclude_none=True)
            conversation_context.active_search_page = page["page"]
            conversation_context.active_search_page_size = page["page_size"]
            conversation_context.active_search_results = [p.id for p in products]

        # Build response text
        if len(products) == 1:
            text = "I found this item for you:"
        else:
            text = f"I found {len(products)} items for you:"

        quick_replies = [
            {"label": "More Details", "value": "product_details"},
            {"label": "Filter by Price", "value": "filter_price"},
        ]
        if len(products) > 3:
            quick_replies.append({"label": "Show more", "value": "show_more"})

        return BotResponse(
            response_type="product_list",
            text=text,
            products=response_products,
            quick_replies=quick_replies,
            metadata={
                "search_performed": True,
                "results_count": len(products),
                "filters_applied": filters.model_dump(exclude_none=True),
                "page": 1,
                "page_size": 3,
                "has_more": len(products) > 3,
                "default_color": "No specific color",
            },
        )
