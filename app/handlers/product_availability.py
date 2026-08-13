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
)
from app.services.product_service import product_service
from app.utils.logger import logger


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
            return BotResponse(
                response_type="text",
                text="Which product would you like to check availability for?",
                metadata={"needs_clarification": True, "missing": "product"},
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

            if reason == "Product not found":
                text = f"I couldn't find '{product_name}'. Could you check the name?"
            elif reason == "No matching variant found":
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
        product_stock = availability.get("product_stock", 0)

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
        all_sizes = availability.get("all_sizes", [])
        all_colors = availability.get("all_colors", [])

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
