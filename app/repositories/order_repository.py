"""
Repository layer for order data access.

Encapsulates MongoDB queries behind a clean interface so that handlers
and services don't couple directly to collection names or query syntax.
"""

from typing import List, Optional

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.models.schemas import Order, OrderStatus
from app.utils.helpers import normalize_mongo_doc
from app.utils.logger import logger


class OrderRepository:
    """
    MongoDB-backed repository for Order documents.
    """

    COLLECTION_NAME = "orders"

    async def find_by_id(self, tenant_id: str, order_id: str) -> Optional[Order]:
        """Retrieve an order by its MongoDB _id."""
        if not mongodb.is_connected:
            return None

        doc = await collections.orders.find_one({
            "_id": order_id,
            "tenant_id": tenant_id,
        })
        return Order(**normalize_mongo_doc(doc)) if doc else None

    async def find_by_number(self, tenant_id: str, order_number: str) -> Optional[Order]:
        """Retrieve an order by its human-readable order number."""
        if not mongodb.is_connected:
            return None

        doc = await collections.orders.find_one({
            "tenant_id": tenant_id,
            "order_number": order_number,
        })
        return Order(**normalize_mongo_doc(doc)) if doc else None

    async def find_by_customer(
        self,
        tenant_id: str,
        customer_id: str,
        limit: int = 20,
    ) -> List[Order]:
        """List recent orders for a customer."""
        if not mongodb.is_connected:
            return []

        cursor = (
            collections.orders
            .find({"tenant_id": tenant_id, "customer_id": customer_id})
            .sort("created_at", -1)
            .limit(limit)
        )

        orders: List[Order] = []
        async for doc in cursor:
            orders.append(Order(**normalize_mongo_doc(doc)))

        return orders

    async def update_status(
        self,
        tenant_id: str,
        order_id: str,
        status: OrderStatus,
    ) -> bool:
        """Update an order's status. Returns True if a document was modified."""
        if not mongodb.is_connected:
            return False

        result = await collections.orders.update_one(
            {"_id": order_id, "tenant_id": tenant_id},
            {"$set": {"status": status.value}},
        )
        return result.modified_count > 0


order_repository = OrderRepository()
