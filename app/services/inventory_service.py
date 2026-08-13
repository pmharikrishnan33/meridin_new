"""
Inventory service - handles stock level queries and inventory operations.

Provides a read-only interface for checking flat product stock levels.
When MongoDB is unavailable the service returns conservative
defaults so the bot can still respond to the user.
"""

from typing import Dict, Any, List, Optional

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.models.schemas import Product
from app.utils.helpers import normalize_mongo_doc
from app.utils.logger import logger


class InventoryService:
    """
    Service layer for inventory-related queries.

    Queries MongoDB directly but degrades gracefully when the database
    is unavailable.
    """

    async def get_stock_level(
        self,
        tenant_id: str,
        product_id: str,
        size: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get the stock level for a product, optionally filtered by size/color.

        A flat product-level stock count is used. Size and color lists are
        independent in this MVP, so a request matches when each value exists.
        """
        if not mongodb.is_connected:
            logger.debug("Stock level check skipped — MongoDB unavailable.")
            return {"in_stock": False, "total_stock": 0, "variants": []}

        doc = await collections.products(tenant_id).find_one({
            "_id": product_id,
            "tenant_id": tenant_id,
        })

        if not doc:
            return {"in_stock": False, "total_stock": 0, "variants": []}

        product = Product(**normalize_mongo_doc(doc))
        size_matches = not size or any(value.lower() == size.lower() for value in product.size)
        color_matches = not color or any(value.lower() == color.lower() for value in product.color)
        in_stock = size_matches and color_matches and product.stock > 0

        return {
            "in_stock": in_stock,
            "total_stock": product.stock if in_stock else 0,
            "variants": [],
        }

    async def is_in_stock(
        self,
        tenant_id: str,
        product_id: str,
        size: Optional[str] = None,
        color: Optional[str] = None,
    ) -> bool:
        """Quick boolean check for stock availability."""
        result = await self.get_stock_level(tenant_id, product_id, size, color)
        return result["in_stock"]

    async def get_low_stock_products(
        self,
        tenant_id: str,
        threshold: int = 5,
        limit: int = 50,
    ) -> List[Product]:
        """
        Return products whose flat stock value is below the threshold.
        """
        if not mongodb.is_connected:
            return []

        cursor = (collections.products(tenant_id).find({"tenant_id": tenant_id}).limit(limit))

        low_stock: List[Product] = []
        async for doc in cursor:
            product = Product(**normalize_mongo_doc(doc))
            if product.stock < threshold:
                low_stock.append(product)

        return low_stock

    async def get_stock_summary(self, tenant_id: str) -> Dict[str, Any]:
        """
        Return an aggregate stock summary for a tenant.

        Returns total product count and counts of in-stock vs out-of-stock
        products. ``total_variants`` is retained as a compatibility key.
        """
        if not mongodb.is_connected:
            return {"total_products": 0, "total_variants": 0, "in_stock": 0, "out_of_stock": 0}

        cursor = collections.products(tenant_id).find({"tenant_id": tenant_id})

        total_products = 0
        total_variants = 0
        in_stock = 0
        out_of_stock = 0

        async for doc in cursor:
            total_products += 1
            product = Product(**normalize_mongo_doc(doc))
            total_variants += 1
            if product.stock > 0:
                in_stock += 1
            else:
                out_of_stock += 1

        return {
            "total_products": total_products,
            "total_variants": total_variants,
            "in_stock": in_stock,
            "out_of_stock": out_of_stock,
        }


inventory_service = InventoryService()
