import re
from typing import List, Optional, Dict, Any

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.database.redis_cache import redis_cache
from app.models.schemas import Product, ProductSearchFilters
from app.utils.helpers import normalize_mongo_doc
from app.utils.logger import logger


class ProductRepository:

    async def search(
        self,
        tenant_id: str,
        filters: ProductSearchFilters,
    ) -> List[Product]:

        if not mongodb.is_connected:
            logger.warning(
                "Product search skipped because MongoDB is unavailable."
            )
            return []

        query: Dict[str, Any] = {
            "tenant_id": tenant_id,
        }

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
            ]

        if filters.category:
            query["category"] = {
                "$regex": (
                    "^"
                    + re.escape(filters.category.strip())
                    + "$"
                ),
                "$options": "i",
            }

        if filters.type:
            query["type"] = {
                "$regex": (
                    "^"
                    + re.escape(filters.type.strip())
                    + "$"
                ),
                "$options": "i",
            }

        if filters.color:
            query["color"] = {
                "$regex": (
                    "^"
                    + re.escape(filters.color.strip())
                    + "$"
                ),
                "$options": "i",
            }

        if filters.size:
            query["size"] = {
                "$regex": (
                    "^"
                    + re.escape(filters.size.strip())
                    + "$"
                ),
                "$options": "i",
            }

        if filters.age_group:
            query["age_group"] = {
                "$regex": (
                    "^"
                    + re.escape(filters.age_group.strip())
                    + "$"
                ),
                "$options": "i",
            }

        if filters.min_price is not None:
            query.setdefault(
                "price", {}
            )["$gte"] = filters.min_price

        if filters.max_price is not None:
            query.setdefault(
                "price", {}
            )["$lte"] = filters.max_price

        if filters.in_stock_only:
            query["stock"] = {
                "$gt": 0
            }

        cursor = (
            collections.products(tenant_id)
            .find(query)
            .skip(filters.offset)
            .limit(filters.limit)
        )

        sort_map = {
            "price_asc": [("price", 1)],
            "price_desc": [("price", -1)],
            "newest": [("created_at", -1)],
        }

        sort_spec = sort_map.get(
            filters.sort_by
        )

        if sort_spec:
            cursor = cursor.sort(sort_spec)

        products: List[Product] = []

        async for document in cursor:
            products.append(
                Product(
                    **normalize_mongo_doc(
                        document
                    )
                )
            )

        logger.info(
            "Product search returned %s results for tenant %s",
            len(products),
            tenant_id,
        )

        return products