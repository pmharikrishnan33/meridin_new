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


class ProductInquiryHandler(BaseHandler):

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:

        product_reference = None

        # ------------------------------------------
        # 1. Product from current message
        # ------------------------------------------

        for entity in understanding.entities:

            if entity.entity_type == EntityType.PRODUCT:

                product_reference = (
                    entity.normalized_value
                    or entity.value
                )

                break

        # ------------------------------------------
        # 2. Product from conversation context
        # ------------------------------------------

        if (
            not product_reference
            and conversation_context
            and conversation_context.current_product
        ):
            product_reference = (
                conversation_context.current_product
            )

        # ------------------------------------------
        # 3. Ask clarification
        # ------------------------------------------

        if not product_reference:

            return BotResponse(
                response_type="text",
                text=(
                    "Which product would you like "
                    "to know more about?"
                ),
                metadata={
                    "needs_clarification": True,
                    "missing": "product",
                },
            )

        # ------------------------------------------
        # 4. Exact product lookup
        # ------------------------------------------

        product = await product_service.get_product_by_reference(
            tenant_id=tenant_id,
            reference=product_reference,
        )

        # ------------------------------------------
        # 5. Search fallback
        # ------------------------------------------

        if not product:

            products = await product_service.search_products(
                tenant_id,
                ProductSearchFilters(
                    query=product_reference,
                    limit=5,
                ),
            )

            if len(products) == 1:
                product = products[0]

            elif len(products) > 1:

                return BotResponse(
                    response_type="product_list",
                    text=(
                        "I found several products. "
                        "Which one would you like details about?"
                    ),
                    products=[
                        product_service.product_to_response(
                            item
                        )
                        for item in products[:5]
                    ],
                    metadata={
                        "needs_clarification": True,
                        "multiple_products": True,
                    },
                )

            else:

                return BotResponse(
                    response_type="text",
                    text=(
                        f"I couldn't find "
                        f"'{product_reference}'. "
                        "Could you check the product name?"
                    ),
                    metadata={
                        "product_not_found": True,
                        "searched_for": product_reference,
                    },
                )

        # ------------------------------------------
        # 6. Response product
        # ------------------------------------------

        response_product = (
            product_service.product_to_response(
                product
            )
        )

        details = product.description or ""

        if product.stock > 0:
            details += (
                f"\n\nStock: "
                f"{product.stock} available"
            )
        else:
            details += "\n\nCurrently out of stock."

        if product.size:
            details += (
                "\nAvailable sizes: "
                + ", ".join(
                    sorted(product.size)
                )
            )

        if product.color:
            details += (
                "\nAvailable colors: "
                + ", ".join(
                    sorted(product.color)
                )
            )

        if product.brand:
            details += (
                f"\nBrand: {product.brand}"
            )

        if product.material:
            details += (
                f"\nMaterial: {product.material}"
            )

        if conversation_context:
            conversation_context.current_product = (
                product.id
            )

        return BotResponse(
            response_type="product_card",
            text=details.strip(),
            products=[response_product],
            metadata={
                "product_id": product.id,
                "product_name": product.title,
            },
        )