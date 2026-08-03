"""
Pagination handler.

Consumes stored active-search state and returns the next page of cached
results in a bot-friendly response.
"""

from typing import Any, Dict, Optional

from app.handlers.base_handler import BaseHandler
from app.models.schemas import BotResponse, ConversationContext, MessageUnderstanding


class PaginationHandler(BaseHandler):
    """Handle follow-up pagination requests for cached search results."""

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:
        if conversation_context is None:
            return BotResponse(
                response_type="text",
                text="I don't have a search page to show right now.",
                metadata={"pagination": False},
            )

        result_ids = conversation_context.active_search_results or []
        if not result_ids:
            return BotResponse(
                response_type="text",
                text="There are no more results to show.",
                metadata={"pagination": False, "results_count": 0},
            )

        page_size = conversation_context.active_search_page_size or 10
        total = conversation_context.active_search_total or len(result_ids)
        current_page = conversation_context.active_search_page or 1
        next_page = current_page + 1
        offset = min((next_page - 1) * page_size, total)
        page_items = result_ids[offset:offset + page_size]
        has_next = offset + page_size < total

        if not page_items:
            return BotResponse(
                response_type="text",
                text="There are no more results to show.",
                metadata={"pagination": False, "results_count": 0},
            )

        conversation_context.active_search_offset = offset
        conversation_context.active_search_page = next_page

        return BotResponse(
            response_type="product_list",
            text=f"Showing page {next_page} of your search results.",
            products=[],
            metadata={
                "pagination": True,
                "page": next_page,
                "page_size": page_size,
                "offset": offset,
                "total": total,
                "has_next": has_next,
                "items": page_items,
            },
        )
