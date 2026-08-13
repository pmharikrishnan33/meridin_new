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

    def _build_mongo_query(
        self,
        filters: ProductSearchFilters,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build a MongoDB query dict from ProductSearchFilters.
        """

        query: Dict[str, Any] = {"tenant_id": tenant_id} if tenant_id else {}

        def contains(value: str) -> Dict[str, str]:
            return {"$regex": re.escape(value), "$options": "i"}

        def exact(value: str) -> Dict[str, str]:
            return {"$regex": f"^{re.escape(value)}$", "$options": "i"}

        if filters.query:
            query["$or"] = [
                {"title": contains(filters.query)},
                {"description": contains(filters.query)},
                {"category": contains(filters.query)},
            ]

        if filters.category:
            query["category"] = exact(filters.category)

        if filters.type:
            query["type"] = exact(filters.type)

        if filters.sub_category:
            query["sub_category"] = exact(filters.sub_category)

        if filters.brand:
            query["brand"] = exact(filters.brand)

        if filters.color:
            query["color"] = exact(filters.color)

        if filters.size:
            query["size"] = exact(filters.size)

        if filters.fit:
            query["fit"] = exact(filters.fit)

        if filters.gender:
            query["gender"] = exact(filters.gender)

        if filters.tags:
            query["tags"] = {
                "$in": [
                    {"$regex": re.escape(tag), "$options": "i"}
                    for tag in filters.tags
                ]
            }
        if filters.min_price is not None:
            query.setdefault("price", {})["$gte"] = filters.min_price
        if filters.max_price is not None:
            query.setdefault("price", {})["$lte"] = filters.max_price
        if filters.in_stock_only:
            query["stock"] = {"$gt": 0}

        return query

    def _build_sort(self, sort_by: str) -> List[tuple]:
        """
        Build MongoDB sort spec from sort_by string.
        """

        sort_map = {
            "price_asc": [("price", 1)],
            "price_desc": [("price", -1)],
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

        query = self._build_mongo_query(filters, tenant_id)
        
        # 1. Start building the query cursor
        cursor = collections.products(tenant_id).find(query)
        
        # 2. Check if we actually have sorting rules
        sort_spec = self._build_sort(filters.sort_by)
        
        # 3. ONLY apply the sort command if the list is not empty
        if sort_spec:
            cursor = cursor.sort(sort_spec)
            
        cursor = cursor.skip(filters.offset).limit(filters.limit)

        products = []
        async for doc in cursor:
            products.append(Product(**self._normalize_document(doc)))

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

        doc = await collections.products(tenant_id).find_one({
            "_id": self._product_id_filter(product_id),
            "tenant_id": tenant_id,
        })

        if doc:
            product = Product(**self._normalize_document(doc))
            await redis_cache.set(cache_key, product.model_dump(by_alias=True), ttl=600)
            return product

        logger.warning(f"Product not found: {product_id} (tenant: {tenant_id})")
        return None

    async def get_product_by_reference(self, tenant_id: str, reference: str) -> Optional[Product]:
        """Look up a product by stable ID first, then by a case-insensitive name."""
        product = await self.get_product_by_id(tenant_id, reference)
        if product or not mongodb.is_connected:
            return product

        doc = await collections.products(tenant_id).find_one({
            "tenant_id": tenant_id,
            "title": {"$regex": f"^{re.escape(reference)}$", "$options": "i"},
        })
        return Product(**self._normalize_document(doc)) if doc else None

    async def check_availability(
        self,
        tenant_id: str,
        product_id: str,
        size: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check product availability using the current flat inventory model.

        Stock is tracked at product level, not at size/color variant level.
        Therefore size/color are availability attributes, while stock is
        product-level.
        """

        product = await self.get_product_by_reference(
            tenant_id,
            product_id,
        )

        if not product:
            return {
                "available": False,
                "reason": "product_not_found",
            }

        size_matches = (
            True
            if not size
            else any(
                value.strip().lower() == size.strip().lower()
                for value in product.size
            )
        )

        color_matches = (
            True
            if not color
            else any(
                value.strip().lower() == color.strip().lower()
                for value in product.color
            )
        )

        if not size_matches:
            return {
                "available": False,
                "reason": "size_not_available",
                "product_name": product.name,
                "requested_size": size,
                "available_sizes": sorted(product.size),
                "stock": product.stock,
            }

        if not color_matches:
            return {
                "available": False,
                "reason": "color_not_available",
                "product_name": product.name,
                "requested_color": color,
                "available_colors": sorted(product.color),
                "stock": product.stock,
            }

        if product.stock <= 0:
            return {
                "available": False,
                "reason": "out_of_stock",
                "product_name": product.name,
                "stock": 0,
                "available_sizes": sorted(product.size),
                "available_colors": sorted(product.color),
            }

        return {
            "available": True,
            "reason": "available",
            "product_name": product.name,
            "stock": product.stock,
            "requested_size": size,
            "requested_color": color,
            "available_sizes": sorted(product.size),
            "available_colors": sorted(product.color),
            "price": product.base_price,
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
        Convert extracted entities into product search filters.

        PRODUCT is treated as a free-text product query.
        CATEGORY is treated as a category filter.
        STYLE is mapped to the product 'type' field.
        """

        filters = ProductSearchFilters()

        for entity in entities:
            value = entity.normalized_value or entity.value

            if not value:
                continue

            value = value.strip()

            if entity.entity_type == EntityType.PRODUCT:
                filters.query = value.lower()

            elif entity.entity_type == EntityType.CATEGORY:
                filters.category = value.lower()

            elif entity.entity_type == EntityType.BRAND:
                filters.brand = value.lower()

            elif entity.entity_type == EntityType.COLOR:
                filters.color = value.lower()

            elif entity.entity_type == EntityType.SIZE:
                filters.size = value.upper()

            elif entity.entity_type == EntityType.FIT:
                filters.fit = value.lower()

            elif entity.entity_type == EntityType.STYLE:
                filters.type = value.lower()

            elif entity.entity_type == EntityType.GENDER:
                filters.gender = value.lower()

            elif entity.entity_type == EntityType.PRICE:
                try:
                    price = float(value)

                    operator = (entity.metadata or {}).get(
                        "operator",
                        "exact",
                    )

                    if operator == "max":
                        filters.max_price = price

                    elif operator == "min":
                        filters.min_price = price

                    else:
                        filters.max_price = price

                except (ValueError, TypeError):
                    logger.warning(
                        f"Unable to parse price entity: {value}"
                    )

        return filters

    def product_to_response(self, product: Product) -> ResponseProduct:
        """
        Convert a Product model to a ResponseProduct for the bot response.
        """

        sizes = sorted(product.size)
        colors = sorted(product.color)
        in_stock = product.stock > 0
        price = product.base_price
        sale_price = None
        image = product.images[0] if product.images else None
        product_type = product.type or product.sub_category

        return ResponseProduct(
            product_id=product.id,
            name=product.name,
            price=price,
            sale_price=sale_price,
            currency=product.currency,
            image=image,
            stock=product.stock,
            category=product.category,
            product_type=product_type,
            description=product.description,
            sizes_available=sizes,
            colors_available=colors,
            in_stock=in_stock,
        )

    @staticmethod
    def _normalize_document(doc: Dict[str, Any]) -> Dict[str, Any]:
        """Convert MongoDB identifiers to the string form used by Product."""
        normalized = dict(doc)
        if "_id" in normalized:
            normalized["_id"] = str(normalized["_id"])
        return normalized

    @staticmethod
    def _product_id_filter(product_id: str) -> Any:
        """Match either a legacy string ID or a BSON ObjectId."""
        candidates = [product_id]
        try:
            from bson import ObjectId
            if ObjectId.is_valid(product_id):
                candidates.append(ObjectId(product_id))
        except ImportError:
            pass
        return {"$in": candidates} if len(candidates) > 1 else product_id


product_service = ProductService()
