from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.database.redis_cache import redis_cache
from app.models.schemas import Product, ProductSearchFilters
from app.utils.helpers import normalize_mongo_doc
from app.utils.logger import logger


class ProductRepository:
    """
    MongoDB data-access layer for tenant products.

    Database contract:
        inventory.<tenant_id>
    """

    @staticmethod
    def _normalize_text(value: str) -> str:
        return value.strip().lower()

    async def find_by_id(
        self,
        tenant_id: str,
        product_id: str,
    ) -> Optional[Product]:

        if not tenant_id or not product_id:
            return None

        if not mongodb.is_connected:
            return None

        product_id = product_id.strip()

        document = await collections.products(tenant_id).find_one(
            {
                "_id": product_id,
                "tenant_id": tenant_id,
            }
        )

        # Support ObjectId databases if your existing inventory uses ObjectId.
        if document is None:
            try:
                from bson import ObjectId

                if ObjectId.is_valid(product_id):
                    document = await collections.products(tenant_id).find_one(
                        {
                            "_id": ObjectId(product_id),
                            "tenant_id": tenant_id,
                        }
                    )
            except Exception:
                pass

        if document is None:
            return None

        try:
            return Product(
                **normalize_mongo_doc(document)
            )
        except Exception:
            logger.exception(
                "Invalid product document: %s",
                document.get("_id"),
            )
            return None

    async def find_by_title(
        self,
        tenant_id: str,
        title: str,
    ) -> Optional[Product]:

        if not tenant_id or not title:
            return None

        if not mongodb.is_connected:
            return None

        escaped_title = re.escape(title.strip())

        document = await collections.products(tenant_id).find_one(
            {
                "tenant_id": tenant_id,
                "title": {
                    "$regex": f"^{escaped_title}$",
                    "$options": "i",
                },
            }
        )

        if document is None:
            return None

        try:
            return Product(
                **normalize_mongo_doc(document)
            )
        except Exception:
            logger.exception(
                "Invalid product document: %s",
                document.get("_id"),
            )
            return None

    async def find_by_ids(
        self,
        tenant_id: str,
        product_ids: List[str],
    ) -> List[Product]:

        if not tenant_id or not product_ids:
            return []

        if not mongodb.is_connected:
            return []

        unique_ids = list(
            dict.fromkeys(
                product_id.strip()
                for product_id in product_ids
                if product_id and product_id.strip()
            )
        )

        if not unique_ids:
            return []

        cursor = collections.products(tenant_id).find(
            {
                "tenant_id": tenant_id,
                "_id": {
                    "$in": unique_ids
                },
            }
        )

        products_by_id: Dict[str, Product] = {}

        async for document in cursor:
            try:
                product = Product(
                    **normalize_mongo_doc(document)
                )

                products_by_id[product.id] = product

            except Exception:
                logger.exception(
                    "Invalid product document skipped: %s",
                    document.get("_id"),
                )

        return [
            products_by_id[product_id]
            for product_id in unique_ids
            if product_id in products_by_id
        ]

    async def search(
        self,
        tenant_id: str,
        filters: ProductSearchFilters,
    ) -> List[Product]:

        if not tenant_id:
            raise ValueError("tenant_id is required")

        if not mongodb.is_connected:
            logger.warning(
                "Product search skipped because MongoDB is unavailable."
            )
            return []

        query: Dict[str, Any] = {
            "tenant_id": tenant_id,
        }

        # --------------------------------------------------
        # TEXT SEARCH
        # --------------------------------------------------

        if filters.query:
            safe_query = re.escape(
                filters.query.strip()
            )

            query["$or"] = [
                {
                    "title": {
                        "$regex": safe_query,
                        "$options": "i",
                    }
                },
                {
                    "description": {
                        "$regex": safe_query,
                        "$options": "i",
                    }
                },
                {
                    "category": {
                        "$regex": safe_query,
                        "$options": "i",
                    }
                },
                {
                    "type": {
                        "$regex": safe_query,
                        "$options": "i",
                    }
                },
                {
                    "brand": {
                        "$regex": safe_query,
                        "$options": "i",
                    }
                },
                {
                    "material": {
                        "$regex": safe_query,
                        "$options": "i",
                    }
                },
            ]

        # --------------------------------------------------
        # EXACT / CASE-INSENSITIVE FILTERS
        # --------------------------------------------------

        def text_filter(field: str, value: Optional[str]) -> None:
            if value:
                query[field] = {
                    "$regex": (
                        "^"
                        + re.escape(value.strip())
                        + "$"
                    ),
                    "$options": "i",
                }

        text_filter("category", filters.category)
        text_filter("type", filters.type)
        text_filter("brand", filters.brand)
        text_filter("material", filters.material)
        text_filter("fit", filters.fit)
        text_filter("gender", filters.gender)
        text_filter("age_group", filters.age_group)

        # --------------------------------------------------
        # ARRAY FILTERS
        # --------------------------------------------------

        if filters.color:
            query["color"] = {
                "$elemMatch": {
                    "$regex": re.escape(filters.color.strip()),
                    "$options": "i",
                }
            }

        if filters.size:
            query["size"] = {
                "$elemMatch": {
                    "$regex": re.escape(filters.size.strip()),
                    "$options": "i",
                }
            }

        # --------------------------------------------------
        # TAGS
        # --------------------------------------------------

        if filters.tags:
            query["tags"] = {
                "$all": filters.tags
            }

        # --------------------------------------------------
        # PRICE
        # --------------------------------------------------

        if filters.min_price is not None:
            query.setdefault(
                "price",
                {}
            )["$gte"] = filters.min_price

        if filters.max_price is not None:
            query.setdefault(
                "price",
                {}
            )["$lte"] = filters.max_price

        # --------------------------------------------------
        # STOCK
        # --------------------------------------------------

        if filters.in_stock_only:
            query["stock"] = {
                "$gt": 0
            }

        # --------------------------------------------------
        # SORT
        # --------------------------------------------------

        cursor = collections.products(
            tenant_id
        ).find(query)

        sort_map = {
            "price_asc": [
                ("price", 1)
            ],
            "price_desc": [
                ("price", -1)
            ],
            "newest": [
                ("created_at", -1)
            ],
        }

        sort_spec = sort_map.get(
            filters.sort_by
        )

        if sort_spec:
            cursor = cursor.sort(sort_spec)

        # --------------------------------------------------
        # PAGINATION
        # --------------------------------------------------

        offset = max(
            0,
            filters.offset,
        )

        limit = max(
            1,
            min(filters.limit, 100),
        )

        cursor = cursor.skip(offset).limit(limit)

        products: List[Product] = []

        async for document in cursor:

            try:
                products.append(
                    Product(
                        **normalize_mongo_doc(
                            document
                        )
                    )
                )

            except Exception:
                logger.exception(
                    "Invalid product document skipped: %s",
                    document.get("_id"),
                )

        logger.info(
            "Product search returned %s results for tenant %s",
            len(products),
            tenant_id,
        )

        return products


product_repository = ProductRepository()