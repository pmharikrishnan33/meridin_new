"""
Order service - handles order status lookup, cancellation, and returns.
"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.models.schemas import (
    Order,
    OrderStatus,
    ExtractedEntity,
    EntityType,
)
from app.utils.logger import logger


class OrderService:
    """
    Service layer for order-related operations.
    Queries MongoDB collections directly.
    """

    async def get_order_by_id(self, tenant_id: str, order_id: str) -> Optional[Order]:
        """
        Retrieve an order by its ID.
        """

        if not mongodb.is_connected:
            logger.warning("Order lookup skipped because MongoDB is unavailable.")
            return None

        doc = await collections.orders.find_one({
            "_id": order_id,
            "tenant_id": tenant_id,
        })

        if doc:
            return Order(**doc)

        logger.warning(f"Order not found: {order_id} (tenant: {tenant_id})")
        return None

    async def get_order_by_number(self, tenant_id: str, order_number: str) -> Optional[Order]:
        """
        Retrieve an order by its order number.
        """

        if not mongodb.is_connected:
            logger.warning("Order lookup skipped because MongoDB is unavailable.")
            return None

        doc = await collections.orders.find_one({
            "tenant_id": tenant_id,
            "order_number": order_number,
        })

        if doc:
            return Order(**doc)

        logger.warning(f"Order not found by number: {order_number} (tenant: {tenant_id})")
        return None

    async def get_order_status(self, tenant_id: str, order_id: str) -> Optional[Order]:
        """
        Get order status — alias for get_order_by_id.
        """

        return await self.get_order_by_id(tenant_id, order_id)

    async def cancel_order(self, tenant_id: str, order_id: str) -> bool:
        """
        Cancel an order if it's in a cancellable state.
        Returns True if cancellation succeeded.
        """

        if not mongodb.is_connected:
            logger.warning("Order cancellation skipped because MongoDB is unavailable.")
            return False

        doc = await collections.orders.find_one({
            "_id": order_id,
            "tenant_id": tenant_id,
        })

        if not doc:
            logger.warning(f"Cancel failed — order not found: {order_id}")
            return False

        order = Order(**doc)

        # Only allow cancellation for pending/confirmed/processing orders
        cancellable = {
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
            OrderStatus.PROCESSING,
        }

        if order.status not in cancellable:
            logger.info(
                f"Cancel failed — order {order_id} in status {order.status.value} "
                f"(not cancellable)"
            )
            return False

        await collections.orders.update_one(
            {"_id": order_id, "tenant_id": tenant_id},
            {
                "$set": {
                    "status": OrderStatus.CANCELLED.value,
                    "cancelled_at": datetime.now(timezone.utc),
                }
            },
        )

        logger.info(f"Order {order_id} cancelled successfully")
        return True

    async def request_return(
        self,
        tenant_id: str,
        order_id: str,
        reason: str = "",
    ) -> bool:
        """
        Mark an order as return-requested.
        Returns True if the return request was recorded.
        """

        if not mongodb.is_connected:
            logger.warning("Return request skipped because MongoDB is unavailable.")
            return False

        doc = await collections.orders.find_one({
            "_id": order_id,
            "tenant_id": tenant_id,
        })

        if not doc:
            logger.warning(f"Return request failed — order not found: {order_id}")
            return False

        order = Order(**doc)

        # Only allow returns for delivered orders
        if order.status != OrderStatus.DELIVERED:
            logger.info(
                f"Return request failed — order {order_id} in status "
                f"{order.status.value} (not eligible for return)"
            )
            return False

        await collections.orders.update_one(
            {"_id": order_id, "tenant_id": tenant_id},
            {
                "$set": {
                    "status": OrderStatus.RETURNED.value,
                    "notes": reason if not order.notes else f"{order.notes} | Return requested: {reason}",
                }
            },
        )

        logger.info(f"Return requested for order {order_id}")
        return True

    def extract_order_id(self, entities: List[ExtractedEntity]) -> Optional[str]:
        """
        Extract order ID from a list of entities.
        """

        for entity in entities:
            if entity.entity_type == EntityType.ORDER_ID:
                return entity.normalized_value or entity.value

        return None

    def format_order_status_response(self, order: Order) -> Dict[str, Any]:
        """
        Format an order into a human-readable status dict.
        """

        status_messages = {
            OrderStatus.PENDING: "Your order is being processed.",
            OrderStatus.CONFIRMED: "Your order has been confirmed.",
            OrderStatus.PROCESSING: "Your order is being prepared for shipping.",
            OrderStatus.SHIPPED: f"Your order has been shipped. Tracking number: {order.tracking_number or 'N/A'}",
            OrderStatus.DELIVERED: "Your order has been delivered.",
            OrderStatus.CANCELLED: "Your order has been cancelled.",
            OrderStatus.RETURNED: "Your order has been returned.",
            OrderStatus.REFUNDED: "Your order has been refunded.",
        }

        return {
            "order_number": order.order_number,
            "status": order.status.value,
            "status_message": status_messages.get(order.status, "Status unknown."),
            "total": order.total,
            "currency": order.currency,
            "carrier": order.carrier,
            "tracking_number": order.tracking_number,
            "items": [
                {
                    "name": item.name,
                    "quantity": item.quantity,
                    "price": item.total_price,
                }
                for item in order.items
            ],
        }


order_service = OrderService()
