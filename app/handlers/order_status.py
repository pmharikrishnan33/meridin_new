"""
Order status handler - retrieves and reports order status.
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


class OrderStatusHandler(BaseHandler):
    """
    Handles ORDER_STATUS intents.
    Looks up an order by order ID and returns its status.
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
                text="Could you please provide your order ID so I can check the status?",
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
                     "Please double-check your order ID and try again.",
                metadata={"order_not_found": True, "searched_for": order_id},
            )

        # Format status response
        status_info = order_service.format_order_status_response(order)

        # Build response text
        text = (
            f"Here's the status of your order #{status_info['order_number']}:\n\n"
            f"📦 Status: {status_info['status'].title()}\n"
            f"💰 Total: ₹{status_info['total']}\n"
            f"🚚 Carrier: {status_info['carrier'] or 'N/A'}\n"
            f"📍 Tracking: {status_info['tracking_number'] or 'N/A'}"
        )

        # Add items summary
        if status_info["items"]:
            item_lines = []
            for item in status_info["items"]:
                item_lines.append(f"  • {item['name']} x{item['quantity']}")
            text += "\n\nItems:\n" + "\n".join(item_lines)

        # Update conversation context
        if conversation_context:
            conversation_context.last_order_id = order.id

        return BotResponse(
            response_type="order_status",
            text=text,
            metadata={
                "order_status_checked": True,
                "order_id": order.id,
                "order_number": status_info["order_number"],
                "status": status_info["status"],
            },
        )
