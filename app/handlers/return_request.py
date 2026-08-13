"""
Return request handler - processes return and exchange requests.
"""

from typing import Dict, Any, Optional

from app.handlers.base_handler import BaseHandler
from app.models.schemas import (
    MessageUnderstanding,
    ConversationContext,
    BotResponse,
    EntityType,
)
from app.services.order_service import order_service
from app.utils.logger import logger


class ReturnRequestHandler(BaseHandler):
    """
    Handles RETURN_REQUEST intents.
    Processes a return request for a delivered order.
    """

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:

        # Extract order ID from entities
        order_id = order_service.extract_order_id(understanding.entities)

        # Fall back to conversation context
        if not order_id and conversation_context and conversation_context.last_order_id:
            order_id = conversation_context.last_order_id

        if not order_id:
            return BotResponse(
                response_type="text",
                text="Could you please provide your order ID so I can process your return request?",
                metadata={"needs_clarification": True, "missing": "order_id"},
            )

        # Look up order
        order = await order_service.get_order_by_id(tenant_id, order_id)

        if not order:
            # Try order number search
            order = await order_service.get_order_by_number(tenant_id, order_id)

        if not order:
            return BotResponse(
                response_type="text",
                text=f"I couldn't find an order with ID '{order_id}'. "
                     "Please double-check your order ID.",
                metadata={"order_not_found": True, "searched_for": order_id},
            )

        # Process return request
        success = await order_service.request_return(tenant_id, order.id)

        if success:
            text = (
                f"✅ Your return request for order #{order.order_number} has been submitted. "
                f"A return shipping label will be sent to you shortly. "
                f"Once we receive the item, your refund will be processed "
                f"within 3-5 business days."
            )
            quick_replies = [
                {"label": "Track Return", "value": "track_return"},
                {"label": "Contact Support", "value": "contact_support"},
            ]
        else:
            text = (
                f"⚠️ I'm unable to process a return for order #{order.order_number} "
                f"at this time. The order is currently in '{order.status.value}' status. "
                f"Returns are only available for delivered orders. "
                f"Please contact our support team for assistance."
            )
            quick_replies = [
                {"label": "Contact Support", "value": "contact_support"},
                {"label": "Track Order", "value": "track_order"},
            ]

        return BotResponse(
            response_type="text",
            text=text,
            quick_replies=quick_replies,
            metadata={
                "return_requested": True,
                "order_id": order.id,
                "order_number": order.order_number,
                "return_processed": success,
            },
        )
