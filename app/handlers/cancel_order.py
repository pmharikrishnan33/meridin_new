"""
Cancel order handler - handles order cancellation requests.
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


class CancelOrderHandler(BaseHandler):
    """
    Handles CANCEL_ORDER intents.
    Attempts to cancel an order and returns confirmation or failure message.
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
                text="Could you please provide your order ID so I can process the cancellation?",
                metadata={"needs_clarification": True, "missing": "order_id"},
            )

        # Look up order first to check eligibility
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

        # Attempt cancellation
        success = await order_service.cancel_order(tenant_id, order.id)

        if success:
            text = (
                f"✅ Your order #{order.order_number} has been cancelled successfully. "
                f"A refund will be processed to your original payment method "
                f"within 3-5 business days."
            )
            quick_replies = [
                {"label": "Place New Order", "value": "browse_products"},
                {"label": "Track Another Order", "value": "track_order"},
            ]
        else:
            text = (
                f"⚠️ I'm unable to cancel order #{order.order_number} at this time. "
                f"The order is currently in '{order.status.value}' status, "
                f"which means it cannot be cancelled automatically. "
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
                "cancel_attempted": True,
                "order_id": order.id,
                "order_number": order.order_number,
                "cancelled": success,
            },
        )
