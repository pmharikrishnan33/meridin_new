"""
Pagination handler.

Displays the next 3 products from the ORIGINAL ranked
search result list.

Important:

- Does NOT perform the original search again.
- Does NOT change ranking.
- Does NOT reorder products.
- Does NOT run ML.
- Fetches the next 3 products in one database operation.
"""

from typing import Any, Dict, Optional

from app.handlers.base_handler import BaseHandler

from app.models.schemas import (
    BotResponse,
    ConversationContext,
    MessageUnderstanding,
)

from app.services.product_service import (
    product_service,
)


PAGE_SIZE = 3


class PaginationHandler(BaseHandler):
    """
    Handle the Show More button.

    Every click advances exactly 3 positions in the
    stored ranked result list.
    """

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[
            ConversationContext
        ],
    ) -> BotResponse:

        # =====================================================
        # NO CONTEXT
        # =====================================================

        if conversation_context is None:

            return BotResponse(
                response_type="text",

                text=(
                    "I don't have a previous "
                    "search to continue."
                ),

                products=[],

                quick_replies=[],

                metadata={
                    "pagination": False,
                    "reason":
                        "missing_context",
                },
            )

        # =====================================================
        # GET COMPLETE RANKED RESULTS
        # =====================================================

        result_ids = (
            conversation_context
            .active_search_results
            or []
        )

        if not result_ids:

            return BotResponse(
                response_type="text",

                text=(
                    "There are no more "
                    "products to show."
                ),

                products=[],

                quick_replies=[],

                metadata={
                    "pagination": False,
                    "results_count": 0,
                },
            )

        # =====================================================
        # CURRENT PAGE
        # =====================================================

        current_page = (
            conversation_context
            .active_search_page
            or 1
        )

        # =====================================================
        # NEXT PAGE
        # =====================================================

        next_page = current_page + 1

        # =====================================================
        # OFFSET
        #
        # Page 1:
        #   0,1,2
        #
        # Page 2:
        #   3,4,5
        #
        # Page 3:
        #   6,7,8
        # =====================================================

        offset = (
            (next_page - 1)
            * PAGE_SIZE
        )

        total = len(result_ids)

        # =====================================================
        # GET NEXT THREE IDS
        # =====================================================

        page_ids = result_ids[
            offset:
            offset + PAGE_SIZE
        ]

        if not page_ids:

            return BotResponse(
                response_type="text",

                text=(
                    "There are no more "
                    "products to show."
                ),

                products=[],

                quick_replies=[],

                metadata={
                    "pagination": False,
                    "results_count": 0,
                    "page": current_page,
                    "total": total,
                },
            )

        # =====================================================
        # FETCH PRODUCTS
        # =====================================================
        #
        # IMPORTANT:
        #
        # find_by_ids() may return products in MongoDB order,
        # not necessarily in ranked order.
        #
        # Therefore we explicitly rebuild the response in
        # page_ids order.
        # =====================================================

        products = (
            await product_service
            .get_products_by_ids(
                tenant_id=tenant_id,
                product_ids=page_ids,
            )
        )

        products_by_id = {
            product.id: product
            for product in products
        }

        ordered_products = []

        for product_id in page_ids:

            product = products_by_id.get(
                product_id
            )

            if product:

                ordered_products.append(
                    product
                )

        # =====================================================
        # DATABASE MAY HAVE MISSING PRODUCTS
        # =====================================================

        if not ordered_products:

            return BotResponse(
                response_type="text",

                text=(
                    "Some products from the "
                    "previous search are no "
                    "longer available."
                ),

                products=[],

                quick_replies=[],

                metadata={
                    "pagination": False,
                    "page": next_page,
                    "requested_ids":
                        page_ids,
                    "total": total,
                },
            )

        # =====================================================
        # HAS NEXT PAGE?
        # =====================================================

        has_next = (
            offset + PAGE_SIZE
            < total
        )

        # =====================================================
        # UPDATE PAGINATION STATE
        # =====================================================

        conversation_context.active_search_offset = (
            offset
        )

        conversation_context.active_search_page = (
            next_page
        )

        # IMPORTANT:
        # Never replace active_search_results.
        #
        # It must always contain the COMPLETE ranked list.

        conversation_context.active_search_results = (
            result_ids
        )

        # =====================================================
        # RESPONSE PRODUCTS
        # =====================================================

        response_products = [
            product_service.product_to_response(
                product
            )
            for product in ordered_products
        ]

        # =====================================================
        # SHOW MORE BUTTON
        # =====================================================

        quick_replies = []

        if has_next:

            quick_replies = [
                {
                    "label": "Show more",
                    "value": "show_more",
                }
            ]

        # =====================================================
        # RESPONSE
        # =====================================================

        return BotResponse(
            response_type="product_list",

            text=(
                "Here are more products "
                "from your search:"
            ),

            products=response_products,

            quick_replies=quick_replies,

            metadata={
                "pagination": True,

                "page": next_page,

                "page_size":
                    PAGE_SIZE,

                "offset": offset,

                "total": total,

                "has_next": has_next,

                "items": page_ids,

                "results_count":
                    len(ordered_products),

                "default_color":
                    "No specific color",
            },
        )