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

        # Apply tenant max products limit
        max_products = tenant_settings.get("feature_flags", {}).get(
            "max_products_per_response", 5
        )
        filters.limit = min(filters.limit, max_products)

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

        # Convert to response products
        response_products = [
            product_service.product_to_response(p) for p in products
        ]

        # Update conversation context with search
        if conversation_context:
            conversation_context.last_search_filters = filters.model_dump()
            conversation_context.last_search_results = [p.id for p in products]

        # Build response text
        if len(products) == 1:
            text = "I found this item for you:"
        else:
            text = f"I found {len(products)} items for you:"

        return BotResponse(
            response_type="product_list",
            text=text,
            products=response_products,
            quick_replies=[
                {"label": "More Details", "value": "product_details"},
                {"label": "Filter by Price", "value": "filter_price"},
            ],
            metadata={
                "search_performed": True,
                "results_count": len(products),
                "filters_applied": filters.model_dump(exclude_none=True),
            },
        )
