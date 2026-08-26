"""
Product availability handler.

Responsibilities:
- Check availability for a specific product.
- Check availability for a product variant by size/color.
- Fall back to catalogue-level availability when no product
  is explicitly identified.
- Keep all product operations tenant-scoped.
- Respect tenant response limits.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.handlers.base_handler import BaseHandler
from app.models.schemas import (
    BotResponse,
    ConversationContext,
    EntityType,
    MessageUnderstanding,
)
from app.services.product_service import product_service


class AvailabilityHandler(BaseHandler):
    """
    Handles AVAILABILITY intents.

    Supported workflows:

        1. Product availability
           "Is the black shirt available in M?"

        2. Product availability using conversation context
           "Is it available in XL?"

        3. Catalogue availability
           "What shirts are available in black?"

    The handler does not access MongoDB directly.
    All product/database operations go through ProductService.
    """

    # =========================================================
    # MAIN HANDLER
    # =========================================================

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if understanding is None:
            raise ValueError(
                "understanding is required"
            )

        # -----------------------------------------------------
        # EXTRACT ENTITIES
        # -----------------------------------------------------

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

        # -----------------------------------------------------
        # PRODUCT IDENTIFICATION
        # -----------------------------------------------------

        product_id: Optional[str] = None

        if product_entity:

            product_id = (
                product_entity.normalized_value
                or product_entity.value
            )

        elif (
            conversation_context
            and conversation_context.current_product
        ):

            product_id = (
                conversation_context.current_product
            )

        # -----------------------------------------------------
        # SIZE
        # -----------------------------------------------------

        size: Optional[str] = None

        if size_entity:

            size = (
                size_entity.normalized_value
                or size_entity.value
            )

            if size:
                size = size.strip()

        # -----------------------------------------------------
        # COLOR
        # -----------------------------------------------------

        color: Optional[str] = None

        if color_entity:

            color = (
                color_entity.normalized_value
                or color_entity.value
            )

            if color:
                color = color.strip()

        # -----------------------------------------------------
        # CATALOGUE AVAILABILITY
        # -----------------------------------------------------

        if not product_id:

            return await self._handle_catalog_availability(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=tenant_settings,
                conversation_context=conversation_context,
            )

        product_id = product_id.strip()

        if not product_id:

            return await self._handle_catalog_availability(
                understanding=understanding,
                tenant_id=tenant_id,
                tenant_settings=tenant_settings,
                conversation_context=conversation_context,
            )

        # -----------------------------------------------------
        # PRODUCT AVAILABILITY
        # -----------------------------------------------------

        availability = (
            await product_service.check_availability(
                tenant_id=tenant_id,
                product_id=product_id,
                size=size,
                color=color,
            )
        )

        if not availability:
            return BotResponse(
                response_type="text",
                text=(
                    "I couldn't check the availability "
                    "right now. Please try again."
                ),
                quick_replies=[],
                metadata={
                    "availability_checked": False,
                    "available": False,
                    "reason": "empty_availability_response",
                },
            )

        available = bool(
            availability.get(
                "available",
                False,
            )
        )

        product_name = (
            availability.get(
                "product_name"
            )
            or product_id
        )

        # =====================================================
        # NOT AVAILABLE
        # =====================================================

        if not available:

            reason = availability.get(
                "reason",
                "out_of_stock",
            )

            if reason == "product_not_found":

                text = (
                    f"I couldn't find "
                    f"'{product_name}'. "
                    "Could you check the product name?"
                )

            elif reason == "size_not_available":

                if color:

                    text = (
                        f"{product_name} is not available "
                        f"in size {size} and color {color}."
                    )

                else:

                    text = (
                        f"{product_name} is not available "
                        f"in size {size}."
                    )

            elif reason == "color_not_available":

                if size:

                    text = (
                        f"{product_name} is not available "
                        f"in color {color} and size {size}."
                    )

                else:

                    text = (
                        f"{product_name} is not available "
                        f"in color {color}."
                    )

            elif reason == "variant_not_found":

                variant_description = []

                if size:
                    variant_description.append(
                        f"size {size}"
                    )

                if color:
                    variant_description.append(
                        f"color {color}"
                    )

                if variant_description:

                    text = (
                        f"{product_name} doesn't have "
                        f"a variant in "
                        f"{' and '.join(variant_description)}."
                    )

                else:

                    text = (
                        f"The requested variant of "
                        f"{product_name} is not available."
                    )

            else:

                text = (
                    f"Unfortunately, {product_name} "
                    "is currently out of stock"
                )

                if size:
                    text += f" in size {size}"

                if color:
                    text += f" in color {color}"

                text += "."

            quick_replies = [
                {
                    "label": "See All Sizes",
                    "value": "__COMMAND__:view_all_sizes",
                },
                {
                    "label": "Similar Products",
                    "value": "__COMMAND__:similar_products",
                },
                {
                    "label": "Search Again",
                    "value": "__COMMAND__:search_again",
                },
            ]

            return BotResponse(
                response_type="text",
                text=text,
                quick_replies=quick_replies,
                products=[],
                metadata={
                    "availability_checked": True,
                    "available": False,
                    "reason": reason,
                    "product_name": product_name,
                    "requested_size": size,
                    "requested_color": color,
                },
            )

        # =====================================================
        # AVAILABLE
        # =====================================================

        product_stock = availability.get(
            "stock",
            0,
        )

        try:
            product_stock = int(
                product_stock or 0
            )
        except (TypeError, ValueError):
            product_stock = 0

        if size and color:

            text = (
                f"Yes! {product_name} is available "
                f"in size {size} and color {color}."
            )

            if product_stock > 0:
                text += (
                    f" There are {product_stock} "
                    "unit(s) in stock."
                )

        elif size:

            text = (
                f"Yes! {product_name} is available "
                f"in size {size}."
            )

            if product_stock > 0:
                text += (
                    f" There are {product_stock} "
                    "unit(s) in stock."
                )

        elif color:

            text = (
                f"Yes! {product_name} is available "
                f"in color {color}."
            )

            if product_stock > 0:
                text += (
                    f" There are {product_stock} "
                    "unit(s) in stock."
                )

        else:

            text = (
                f"Yes! {product_name} is currently "
                "in stock."
            )

            if product_stock > 0:
                text += (
                    f" There are {product_stock} "
                    "unit(s) available."
                )

        # -----------------------------------------------------
        # AVAILABLE SIZES
        # -----------------------------------------------------

        all_sizes = availability.get(
            "available_sizes",
            [],
        )

        if isinstance(all_sizes, (list, tuple)):

            normalized_sizes = [
                str(value).strip()
                for value in all_sizes
                if value is not None
                and str(value).strip()
            ]

            if normalized_sizes:

                text += (
                    "\n\nAvailable sizes: "
                    + ", ".join(
                        normalized_sizes
                    )
                )

        # -----------------------------------------------------
        # AVAILABLE COLORS
        # -----------------------------------------------------

        all_colors = availability.get(
            "available_colors",
            [],
        )

        if isinstance(all_colors, (list, tuple)):

            normalized_colors = [
                str(value).strip()
                for value in all_colors
                if value is not None
                and str(value).strip()
            ]

            if normalized_colors:

                text += (
                    "\nAvailable colors: "
                    + ", ".join(
                        normalized_colors
                    )
                )

        # -----------------------------------------------------
        # RESPONSE
        # -----------------------------------------------------

        return BotResponse(
            response_type="text",
            text=text,
            quick_replies=[
                {
                    "label": "View Product",
                    "value": "__COMMAND__:product_details",
                },
                {
                    "label": "Search Again",
                    "value": "__COMMAND__:search_again",
                },
            ],
            products=[],
            metadata={
                "availability_checked": True,
                "available": True,
                "product_name": product_name,
                "product_id": product_id,
                "stock": product_stock,
                "requested_size": size,
                "requested_color": color,
                "available_sizes": all_sizes,
                "available_colors": all_colors,
            },
        )

    # =========================================================
    # CATALOGUE AVAILABILITY
    # =========================================================

    async def _handle_catalog_availability(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:
        """
        Check stock for a catalogue-level query when no
        individual product is identified.
        """

        # -----------------------------------------------------
        # BUILD FILTERS
        # -----------------------------------------------------

        filters = (
            product_service.entities_to_filters(
                understanding.entities
            )
        )

        # -----------------------------------------------------
        # USE CONVERSATION CATEGORY
        # -----------------------------------------------------

        if (
            not filters.category
            and conversation_context
            and conversation_context.current_category
        ):

            filters.category = (
                conversation_context.current_category
            )

        # -----------------------------------------------------
        # DETERMINE QUERY SCOPE
        # -----------------------------------------------------

        has_category = bool(
            filters.category
            and filters.category.strip()
        )

        has_query = bool(
            filters.query
            and filters.query.strip()
        )

        has_color = bool(
            filters.color
            and filters.color.strip()
        )

        has_size = bool(
            filters.size
            and filters.size.strip()
        )

        # -----------------------------------------------------
        # NOTHING TO SEARCH
        # -----------------------------------------------------

        if not has_category and not has_query:

            return BotResponse(
                response_type="text",
                text=(
                    "Which product category are you "
                    "looking for?"
                ),
                quick_replies=[],
                products=[],
                metadata={
                    "needs_clarification": True,
                    "missing": "category",
                    "availability_checked": False,
                },
            )

        # -----------------------------------------------------
        # CATEGORY WITHOUT VARIANT CRITERIA
        # -----------------------------------------------------

        if (
            has_category
            and not has_color
            and not has_size
            and not has_query
        ):

            return BotResponse(
                response_type="text",
                text=(
                    f"Which color or size are you "
                    f"looking for in "
                    f"{filters.category}?"
                ),
                quick_replies=[],
                products=[],
                metadata={
                    "needs_clarification": True,
                    "missing": "color_or_size",
                    "category": filters.category,
                    "availability_checked": False,
                },
            )

        # -----------------------------------------------------
        # TENANT RESPONSE LIMIT
        # -----------------------------------------------------

        feature_flags = (
            tenant_settings.get(
                "feature_flags",
                {}
            )
            or {}
        )

        configured_limit = feature_flags.get(
            "max_products_per_response",
            5,
        )

        try:

            configured_limit = int(
                configured_limit
            )

        except (TypeError, ValueError):

            configured_limit = 5

        filters.limit = max(
            1,
            min(
                configured_limit,
                3,
            ),
        )

        # -----------------------------------------------------
        # ONLY RETURN PRODUCTS WITH STOCK
        # -----------------------------------------------------

        filters.in_stock_only = True

        # -----------------------------------------------------
        # SEARCH
        # -----------------------------------------------------

        products = (
            await product_service.search_products(
                tenant_id,
                filters,
            )
        )

        # -----------------------------------------------------
        # NO RESULTS
        # -----------------------------------------------------

        if not products:

            return BotResponse(
                response_type="text",
                text=(
                    "I couldn't find any in-stock "
                    "products matching that. Would you "
                    "like another color, size, or category?"
                ),
                quick_replies=[
                    {
                        "label": "Search Again",
                        "value": "__COMMAND__:search_again",
                    }
                ],
                products=[],
                metadata={
                    "availability_checked": True,
                    "available": False,
                    "results_count": 0,
                },
            )

        # -----------------------------------------------------
        # UPDATE CONVERSATION CONTEXT
        # -----------------------------------------------------

        if conversation_context:

            conversation_context.current_product = (
                products[0].id
            )

            conversation_context.last_search_filters = (
                filters.model_dump(
                    exclude_none=True
                )
            )

            conversation_context.last_search_results = [
                product.id
                for product in products
            ]

        # -----------------------------------------------------
        # BUILD PRODUCT RESPONSE
        # -----------------------------------------------------

        product_responses = [
            product_service.product_to_response(
                product
            )
            for product in products
        ]

        return BotResponse(
            response_type="product_list",
            text=(
                f"Yes, I found "
                f"{len(products)} in-stock "
                "option(s):"
            ),
            products=product_responses,
            quick_replies=[
                {
                    "label": "Search Again",
                    "value": "__COMMAND__:search_again",
                }
            ],
            metadata={
                "availability_checked": True,
                "available": True,
                "results_count": len(products),
                "category": filters.category,
                "color": filters.color,
                "size": filters.size,
            },
        )


availability_handler = AvailabilityHandler()
