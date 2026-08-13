"""
Product inquiry handler - handles detailed product inquiry intents.
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
from app.utils.logger import logger


class ProductInquiryHandler(BaseHandler):
    """
    Handles PRODUCT_INQUIRY intents.
    Retrieves full product details and returns a product card response.
    """

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:

        # Try to get product from entities
        product_entity = None
        for entity in understanding.entities:
            if entity.entity_type == EntityType.PRODUCT:
                product_entity = entity
                break

        # If no product entity in current message, try conversation context
        product_id = None
        if conversation_context and conversation_context.current_product:
            product_id = conversation_context.current_product
        elif product_entity:
            product_id = product_entity.normalized_value or product_entity.value

        if not product_id:
            return BotResponse(
                response_type="text",
                text="Which product would you like to know more about?",
                metadata={"needs_clarification": True, "missing": "product"},
            )

        # Fetch full product details
        product = await product_service.get_product_by_reference(tenant_id, product_id)

        if not product:
            # Try searching by name as fallback
            products = await product_service.search_products(
                tenant_id,
                ProductSearchFilters(query=product_id, limit=1),
            )
            if products:
                product = products[0]
            else:
                return BotResponse(
                    response_type="text",
                    text=f"I couldn't find '{product_id}'. Could you check the name or try another product?",
                    metadata={"product_not_found": True, "searched_for": product_id},
                )

        # Convert to response product
        response_product = product_service.product_to_response(product)

        # Build detailed description
        description = product.description

        # Add variant details
        variant_info = []
        for variant in product.variants:
            if variant.stock > 0:
                price_str = f"₹{variant.price}"
                if variant.sale_price:
                    price_str = f"₹{variant.sale_price} (was ₹{variant.price})"
                variant_info.append(
                    f"{variant.size} / {variant.color} — {price_str} ({variant.stock} in stock)"
                )

        details = f"\n\n{description}"
        if variant_info:
            details += "\n\nAvailable variants:\n" + "\n".join(variant_info)

        # Update context
        if conversation_context:
            conversation_context.current_product = product.id

        return BotResponse(
            response_type="product_card",
            text=details,
            products=[response_product],
            metadata={
                "product_id": product.id,
                "product_name": product.name,
            },
        )
