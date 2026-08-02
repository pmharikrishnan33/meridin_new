"""
Product service - handles product search, retrieval, and availability queries.
"""

import re
from typing import List, Optional, Dict, Any

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.database.redis_cache import redis_cache
from app.models.schemas import (
    Product,
    ProductSearchFilters,
    ResponseProduct,
    ExtractedEntity,
    EntityType,
)
from app.utils.logger import logger


class ProductService:
    """
    Service layer for product-related operations.
    Queries MongoDB collections directly.
    """

    def _build_mongo_query(self, filters: ProductSearchFilters) -> Dict[str, Any]:
        """
        Build a MongoDB query dict from ProductSearchFilters.
        """

        query: Dict[str, Any] = {"tenant_id": {"$exists": True}}

        def contains(value: str) -> Dict[str, str]:
            return {"$regex": re.escape(value), "$options": "i"}

        if filters.query:
            query["name"] = contains(filters.query)

        if filters.category:
            query["category"] = contains(filters.category)

        if filters.sub_category:
            query["sub_category"] = contains(filters.sub_category)

        if filters.brand:
            query["brand"] = contains(filters.brand)

        if filters.gender:
            query["gender"] = contains(filters.gender)

        if filters.color:
            query["variants.color"] = contains(filters.color)

        if filters.size:
            query["variants.size"] = contains(filters.size)

        if filters.fit:
            query["variants.fit"] = contains(filters.fit)

        if filters.min_price is not None:
            query.setdefault("variants.price", {})["$gte"] = filters.min_price

        if filters.max_price is not None:
            query.setdefault("variants.price", {})["$lte"] = filters.max_price

        if filters.in_stock_only:
            query["variants.stock"] = {"$gt": 0}

        if filters.tags:
            query["tags"] = {"$in": filters.tags}

        return query

    def _build_sort(self, sort_by: str) -> List[tuple]:
        """
        Build MongoDB sort spec from sort_by string.
        """

        sort_map = {
            "price_asc": [("base_price", 1)],
            "price_desc": [("base_price", -1)],
            "newest": [("created_at", -1)],
            "popular": [("is_featured", -1), ("created_at", -1)],
        }
        return sort_map.get(sort_by, [])

    async def search_products(
        self,
        tenant_id: str,
        filters: ProductSearchFilters,
    ) -> List[Product]:
        """
        Search products matching the given filters.
        """

        if not mongodb.is_connected:
            logger.warning("Product search skipped because MongoDB is unavailable.")
            return []

        query = self._build_mongo_query(filters)
        query["tenant_id"] = tenant_id

        sort_spec = self._build_sort(filters.sort_by)

        cursor = (
            collections.products
            .find(query)
            .sort(sort_spec)
            .skip(filters.offset)
            .limit(filters.limit)
        )

        products = []
        async for doc in cursor:
            products.append(Product(**doc))

        logger.info(f"Product search returned {len(products)} results for tenant {tenant_id}")
        return products

    async def get_product_by_id(self, tenant_id: str, product_id: str) -> Optional[Product]:
        """
        Retrieve a single product by ID.
        """

        if not mongodb.is_connected:
            logger.warning("Product lookup skipped because MongoDB is unavailable.")
            return None

        # Check Redis cache first
        cache_key = f"product:{tenant_id}:{product_id}"
        cached = await redis_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Product cache hit: {product_id}")
            return Product(**cached)

        doc = await collections.products.find_one({
            "_id": product_id,
            "tenant_id": tenant_id,
        })

        if doc:
            product = Product(**doc)
            await redis_cache.set(cache_key, product.model_dump(by_alias=True), ttl=600)
            return product

        logger.warning(f"Product not found: {product_id} (tenant: {tenant_id})")
        return None

    async def get_product_by_reference(self, tenant_id: str, reference: str) -> Optional[Product]:
        """Look up a product by stable ID first, then by a case-insensitive name."""
        product = await self.get_product_by_id(tenant_id, reference)
        if product or not mongodb.is_connected:
            return product

        doc = await collections.products.find_one({
            "tenant_id": tenant_id,
            "name": {"$regex": f"^{re.escape(reference)}$", "$options": "i"},
        })
        return Product(**doc) if doc else None

    async def check_availability(
        self,
        tenant_id: str,
        product_id: str,
        size: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check stock availability for a product, optionally filtered by size/color.
        Returns availability info per variant.
        """

        product = await self.get_product_by_reference(tenant_id, product_id)

        if not product:
            return {"available": False, "reason": "Product not found"}

        # Filter variants
        variants = product.variants
        if size:
            variants = [v for v in variants if v.size.lower() == size.lower()]
        if color:
            variants = [v for v in variants if v.color.lower() == color.lower()]

        if not variants:
            return {
                "available": False,
                "reason": "No matching variant found",
                "product_name": product.name,
            }

        available_variants = [v for v in variants if v.stock > 0]

        return {
            "available": len(available_variants) > 0,
            "product_name": product.name,
            "total_variants": len(variants),
            "available_variants": [
                {
                    "sku": v.sku,
                    "size": v.size,
                    "color": v.color,
                    "stock": v.stock,
                    "price": v.price,
                    "sale_price": v.sale_price,
                }
                for v in available_variants
            ],
            "all_sizes": sorted(set(v.size for v in variants)),
            "all_colors": sorted(set(v.color for v in variants)),
        }

    async def get_product_inquiry(
        self,
        tenant_id: str,
        product_id: str,
    ) -> Optional[Product]:
        """
        Retrieve full product details for an inquiry.
        """

        return await self.get_product_by_id(tenant_id, product_id)

    def entities_to_filters(
        self,
        entities: List[ExtractedEntity],
    ) -> ProductSearchFilters:
        """
        Convert extracted entities into ProductSearchFilters.
        """

        filters = ProductSearchFilters()

        for entity in entities:
            if entity.entity_type == EntityType.PRODUCT:
                filters.query = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.CATEGORY:
                filters.category = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.BRAND:
                filters.brand = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.COLOR:
                filters.color = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.SIZE:
                filters.size = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.FIT:
                filters.fit = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.PRICE:
                try:
                    price = float(entity.normalized_value or entity.value)
                    value_lower = str(entity.value).lower()
                    if "under" in value_lower or "below" in value_lower or "max" in value_lower:
                        filters.max_price = price
                    elif "above" in value_lower or "over" in value_lower or "min" in value_lower:
                        filters.min_price = price
                    else:
                        filters.max_price = price
                except ValueError:
                    pass

        return filters

    def product_to_response(self, product: Product) -> ResponseProduct:
        """
        Convert a Product model to a ResponseProduct for the bot response.
        """

        # Collect available sizes and colors from variants
        sizes = sorted(set(v.size for v in product.variants))
        colors = sorted(set(v.color for v in product.variants))
        in_stock = any(v.stock > 0 for v in product.variants)

        # Use sale price if available, otherwise base price
        price = product.base_price
        sale_price = None
        for v in product.variants:
            if v.sale_price is not None:
                sale_price = v.sale_price
                break

        # Pick a representative image
        image = product.images[0] if product.images else None

        return ResponseProduct(
            product_id=product.id,
            name=product.name,
            price=price,
            sale_price=sale_price,
            currency=product.currency,
            image=image,
            sizes_available=sizes,
            colors_available=colors,
            in_stock=in_stock,
        )


product_service = ProductService()
