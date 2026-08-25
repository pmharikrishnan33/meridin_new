"""
Product availability handler - checks stock for specific products/variants.
"""

from typing import Dict, Any, Optional

from app.handlers.base_handler import BaseHandler
from app.models.schemas import (
    MessageUnderstanding,
    ConversationContext,
    BotResponse,
    EntityType,
    ProductSearchFilters,
)
from app.services.product_service import product_service


class AvailabilityHandler(BaseHandler):
    """
    Handles AVAILABILITY intents.
    Checks stock availability for a product, optionally filtered by size/color.
    """

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:

        # Extract product, size, and color entities
        product_entity = None
        size_entity = None
        color_entity = None

        for entity in understanding.entities:
            if entity.entity_type == EntityType.PRODUCT:
                product_entity = entity
            elif entity.entity_type == EntityType.SIZE:
                size_entity = entity
            elif entity.entity_type == EntityType.COLOR:
                color_entity = entity

        if product_entity:
            product_id = product_entity.normalized_value or product_entity.value
        elif conversation_context and conversation_context.current_product:
            product_id = conversation_context.current_product
        else:
            return await self._handle_catalog_availability(
                understanding, tenant_id, tenant_settings, conversation_context
            )

        size = size_entity.normalized_value or size_entity.value if size_entity else None
        color = color_entity.normalized_value or color_entity.value if color_entity else None

        # Check availability
        availability = await product_service.check_availability(
            tenant_id, product_id, size=size, color=color
        )

        if not availability["available"]:
            reason = availability.get("reason", "out of stock")
            product_name = availability.get("product_name", product_id)

            if reason == "product_not_found":
                text = f"I couldn't find '{product_name}'. Could you check the name?"
            elif reason in {"size_not_available", "color_not_available"}:
                text = (
                    f"{product_name} doesn't have a variant matching"
                    f"{' size ' + size if size else ''}"
                    f"{' and color ' + color if color else ''}."
                )
            else:
                text = (
                    f"Unfortunately, {product_name} is currently out of stock"
                    f"{' in ' + size if size else ''}"
                    f"{' in ' + color if color else ''}."
                )

            quick_replies = [
                {"label": "See All Sizes", "value": "view_all_sizes"},
                {"label": "Similar Products", "value": "similar_products"},
            ]

            return BotResponse(
                response_type="text",
                text=text,
                quick_replies=quick_replies,
                metadata={
                    "availability_checked": True,
                    "available": False,
                    "product_name": product_name,
                },
            )

        # Build response text
        product_name = availability["product_name"]
        product_stock = availability.get("stock", 0)

        if size and color:
            text = (
                f"Yes! {product_name} is available in {size} / {color}. "
                f"The product has {product_stock} unit(s) in stock overall."
            )
        else:
            text = (
                f"Yes! {product_name} is in stock with {product_stock} unit(s) available."
            )

        # List available sizes/colors
        all_sizes = availability.get("available_sizes", [])
        all_colors = availability.get("available_colors", [])

        if all_sizes:
            text += f"\n\nAvailable sizes: {', '.join(all_sizes)}"
        if all_colors:
            text += f"\nAvailable colors: {', '.join(all_colors)}"

        return BotResponse(
            response_type="text",
            text=text,
            quick_replies=[
                {"label": "View Product", "value": "product_details"},
            ],
            metadata={
                "availability_checked": True,
                "available": True,
                "product_name": product_name,
                "stock": product_stock,
            },
        )

    async def _handle_catalog_availability(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:
        """Check stock for a category/filter when no individual product is selected."""
        filters = product_service.entities_to_filters(understanding.entities)
        if not filters.category and conversation_context and conversation_context.current_category:
            filters.category = conversation_context.current_category

        # A colour/size alone is not a meaningful catalogue scope unless the
        # conversation already established a category.
        if not filters.category and not filters.query:
            return BotResponse(
                response_type="text",
                text="Which product category are you looking for?",
                metadata={"needs_clarification": True, "missing": "category"},
            )

        if filters.category and not any((filters.color, filters.size, filters.query)):
            return BotResponse(
                response_type="text",
                text=f"Which color or size are you looking for in {filters.category}s?",
                metadata={"needs_clarification": True, "missing": "color_or_size"},
            )

        configured_limit = (tenant_settings.get("feature_flags", {}) or {}).get(
            "max_products_per_response", 5
        )
        try:
            filters.limit = max(1, min(int(configured_limit), 20))
        except (TypeError, ValueError):
            filters.limit = 5
        filters.in_stock_only = True
        products = await product_service.search_products(tenant_id, filters)
        if not products:
            return BotResponse(
                response_type="text",
                text="I couldn't find any in-stock products matching that. Would you like another color, size, or category?",
                metadata={"availability_checked": True, "available": False},
            )

        if conversation_context:
            conversation_context.current_product = products[0].id
            conversation_context.last_search_filters = filters.model_dump(exclude_none=True)
            conversation_context.last_search_results = [product.id for product in products]

        return BotResponse(
            response_type="product_list",
            text=f"Yes, I found {len(products)} in-stock option(s):",
            products=[product_service.product_to_response(product) for product in products],
            metadata={"availability_checked": True, "available": True, "results_count": len(products)},
        )
