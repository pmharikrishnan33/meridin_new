"""
Repository layer for product data access.

Encapsulates MongoDB queries behind a clean interface so that handlers
and services don't couple directly to collection names or query syntax.
All methods are async and gracefully return empty/None when MongoDB is
unavailable.
"""

from typing import List, Optional, Dict, Any

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.database.redis_cache import redis_cache
from app.models.schemas import Product, ProductSearchFilters
from app.utils.helpers import normalize_mongo_doc
from app.utils.logger import logger


class ProductRepository:
    """
    MongoDB-backed repository for Product documents.
    """

    COLLECTION_NAME = "products"

    async def find_by_id(self, tenant_id: str, product_id: str) -> Optional[Product]:
        """Retrieve a single product by its MongoDB _id."""
        if not mongodb.is_connected:
            logger.debug("ProductRepository.find_by_id skipped — MongoDB unavailable.")
            return None

        cache_key = f"product:{tenant_id}:{product_id}"
        cached = await redis_cache.get(cache_key)
        if cached is not None:
            return Product(**cached)

        doc = await collections.products(tenant_id).find_one({
            "_id": product_id,
            "tenant_id": tenant_id,
        })
        if doc:
            product = Product(**normalize_mongo_doc(doc))
            await redis_cache.set(cache_key, product.model_dump(by_alias=True), ttl=600)
            return product

        return None

    async def find_by_name(self, tenant_id: str, name: str) -> Optional[Product]:
        """Find a product by case-insensitive exact name match."""
        if not mongodb.is_connected:
            return None

        doc = await collections.products(tenant_id).find_one({
            "tenant_id": tenant_id,
            "title": {"$regex": f"^{name}$", "$options": "i"},
        })
        return Product(**normalize_mongo_doc(doc)) if doc else None

    async def search(
        self,
        tenant_id: str,
        filters: ProductSearchFilters,
    ) -> List[Product]:
        """Search products matching the given filters."""
        if not mongodb.is_connected:
            return []

        query: Dict[str, Any] = {"tenant_id": tenant_id}

        if filters.query:
            query["$or"] = [
                {"title": {"$regex": filters.query, "$options": "i"}},
                {"description": {"$regex": filters.query, "$options": "i"}},
                {"category": {"$regex": filters.query, "$options": "i"}},
            ]
        if filters.category:
            query["category"] = {"$regex": f"^{filters.category}$", "$options": "i"}
        if filters.type:
            query["type"] = {"$regex": f"^{filters.type}$", "$options": "i"}
        if filters.color:
            query["color"] = {"$regex": f"^{filters.color}$", "$options": "i"}
        if filters.size:
            query["size"] = {"$regex": f"^{filters.size}$", "$options": "i"}
        if filters.min_price is not None:
            query.setdefault("price", {})["$gte"] = filters.min_price
        if filters.max_price is not None:
            query.setdefault("price", {})["$lte"] = filters.max_price
        if filters.in_stock_only:
            query["stock"] = {"$gt": 0}

        cursor = collections.products(tenant_id).find(query).skip(filters.offset).limit(filters.limit)

        products: List[Product] = []
        async for doc in cursor:
            products.append(Product(**normalize_mongo_doc(doc)))

        return products

    async def list_featured(self, tenant_id: str, limit: int = 10) -> List[Product]:
        """Return featured products for a tenant."""
        if not mongodb.is_connected:
            return []

        cursor = (
            collections.products(tenant_id)
            .find({"tenant_id": tenant_id, "is_featured": True, "is_active": True})
            .sort("created_at", -1)
            .limit(limit)
        )

        products: List[Product] = []
        async for doc in cursor:
            products.append(Product(**normalize_mongo_doc(doc)))

        return products


product_repository = ProductRepository()
