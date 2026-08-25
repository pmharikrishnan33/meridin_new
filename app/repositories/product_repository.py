from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.models.schemas import Product, ProductSearchFilters
from app.utils.helpers import normalize_mongo_doc
from app.utils.logger import logger


class ProductRepository:
    """
    MongoDB data-access layer for tenant products.

    Database contract:
        inventory.<tenant_id>

    Important rules:
    - Every query is tenant-scoped.
    - Product IDs may be stored as strings or MongoDB ObjectIds.
    - Search filters are combined with AND semantics.
    - Multiple OR-based conditions are placed inside $and so they
      cannot overwrite one another.
    """

    @staticmethod
    def _normalize_text(value: str) -> str:
        return value.strip().lower()

    @staticmethod
    def _id_candidates(product_id: str) -> List[Any]:
        """
        Return MongoDB-compatible candidates for a product ID.

        Supports both:
        - string IDs
        - ObjectId IDs
        """
        product_id = product_id.strip()

        candidates: List[Any] = [product_id]

        if ObjectId.is_valid(product_id):
            object_id = ObjectId(product_id)

            if object_id != product_id:
                candidates.append(object_id)

        return candidates

    @staticmethod
    def _build_text_condition(
        field: str,
        value: str,
    ) -> Dict[str, Any]:
        """
        Build a case-insensitive regex condition.
        """
        return {
            field: {
                "$regex": re.escape(value.strip()),
                "$options": "i",
            }
        }

    @staticmethod
    def _build_exact_text_condition(
        field: str,
        value: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Build a case-insensitive exact-match condition.
        """
        if not value or not value.strip():
            return None

        return {
            field: {
                "$regex": (
                    "^"
                    + re.escape(value.strip())
                    + "$"
                ),
                "$options": "i",
            }
        }

    @staticmethod
    def _build_array_condition(
        field: str,
        value: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Build a case-insensitive match for an array of strings.

        Example:
            color = ["Black", "White"]

        Query:
            {"color": {"$elemMatch": {"$regex": "^black$", ...}}}
        """
        if not value or not value.strip():
            return None

        return {
            field: {
                "$elemMatch": {
                    "$regex": (
                        "^"
                        + re.escape(value.strip())
                        + "$"
                    ),
                    "$options": "i",
                }
            }
        }

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

        if not product_id:
            return None

        document = await collections.products(
            tenant_id
        ).find_one(
            {
                "tenant_id": tenant_id,
                "_id": {
                    "$in": self._id_candidates(product_id)
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

    async def find_by_title(
        self,
        tenant_id: str,
        title: str,
    ) -> Optional[Product]:

        if not tenant_id or not title:
            return None

        if not mongodb.is_connected:
            return None

        title = title.strip()

        if not title:
            return None

        escaped_title = re.escape(title)

        document = await collections.products(
            tenant_id
        ).find_one(
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
                if isinstance(product_id, str)
                and product_id.strip()
            )
        )

        if not unique_ids:
            return []

        mongo_ids: List[Any] = []

        for product_id in unique_ids:
            mongo_ids.extend(
                self._id_candidates(product_id)
            )

        cursor = collections.products(
            tenant_id
        ).find(
            {
                "tenant_id": tenant_id,
                "_id": {
                    "$in": mongo_ids
                },
            }
        )

        products_by_id: Dict[str, Product] = {}

        async for document in cursor:
            try:
                product = Product(
                    **normalize_mongo_doc(document)
                )

                products_by_id[
                    product.id
                ] = product

            except Exception:
                logger.exception(
                    "Invalid product document skipped: %s",
                    document.get("_id"),
                )

        # Preserve the exact order requested by the caller.
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
            raise ValueError(
                "tenant_id is required"
            )

        if filters is None:
            raise ValueError(
                "filters are required"
            )

        if not mongodb.is_connected:
            logger.warning(
                "Product search skipped because "
                "MongoDB is unavailable."
            )
            return []

        # --------------------------------------------------
        # BASE TENANT CONDITION
        # --------------------------------------------------

        query: Dict[str, Any] = {
            "tenant_id": tenant_id,
        }

        # Every independent filter goes into this list.
        #
        # This is important because multiple filters may
        # themselves contain $or conditions.
        #
        # Example:
        #
        # query["$and"] = [
        #     {"$or": [...]},       # text search
        #     {"$or": [...]},       # stock
        #     {"category": ...},
        #     {"color": ...},
        # ]
        #
        # This prevents one $or from overwriting another.
        conditions: List[Dict[str, Any]] = []

        # --------------------------------------------------
        # TEXT SEARCH
        # --------------------------------------------------

        if filters.query:
            search_text = filters.query.strip()

            if search_text:
                safe_query = re.escape(
                    search_text
                )

                conditions.append(
                    {
                        "$or": [
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
                            {
                                "tags": {
                                    "$regex": safe_query,
                                    "$options": "i",
                                }
                            },
                        ]
                    }
                )

        # --------------------------------------------------
        # EXACT / CASE-INSENSITIVE FILTERS
        # --------------------------------------------------

        exact_filters = {
            "category": filters.category,
            "type": filters.type,
            "brand": filters.brand,
            "material": filters.material,
            "fit": filters.fit,
            "gender": filters.gender,
            "age_group": filters.age_group,
        }

        for field, value in exact_filters.items():
            condition = (
                self._build_exact_text_condition(
                    field,
                    value,
                )
            )

            if condition:
                conditions.append(condition)

        # --------------------------------------------------
        # ARRAY FILTERS
        # --------------------------------------------------

        color_condition = (
            self._build_array_condition(
                "color",
                filters.color,
            )
        )

        if color_condition:
            conditions.append(
                color_condition
            )

        size_condition = (
            self._build_array_condition(
                "size",
                filters.size,
            )
        )

        if size_condition:
            conditions.append(
                size_condition
            )

        # --------------------------------------------------
        # VARIANT COLOR / SIZE
        #
        # Some inventory documents may store color and
        # size only inside variants.
        #
        # If a product has top-level values, those match.
        # If not, matching variants also qualify.
        # --------------------------------------------------

        if filters.color:
            color_value = filters.color.strip()

            if color_value:
                conditions.append(
                    {
                        "$or": [
                            {
                                "color": {
                                    "$elemMatch": {
                                        "$regex": (
                                            "^"
                                            + re.escape(
                                                color_value
                                            )
                                            + "$"
                                        ),
                                        "$options": "i",
                                    }
                                }
                            },
                            {
                                "variants": {
                                    "$elemMatch": {
                                        "color": {
                                            "$regex": (
                                                "^"
                                                + re.escape(
                                                    color_value
                                                )
                                                + "$"
                                            ),
                                            "$options": "i",
                                        }
                                    }
                                }
                            },
                        ]
                    }
                )

                # Remove the previous top-level-only
                # color condition because the combined
                # top-level/variant condition replaces it.
                if color_condition:
                    conditions.remove(
                        color_condition
                    )

        if filters.size:
            size_value = filters.size.strip()

            if size_value:
                conditions.append(
                    {
                        "$or": [
                            {
                                "size": {
                                    "$elemMatch": {
                                        "$regex": (
                                            "^"
                                            + re.escape(
                                                size_value
                                            )
                                            + "$"
                                        ),
                                        "$options": "i",
                                    }
                                }
                            },
                            {
                                "variants": {
                                    "$elemMatch": {
                                        "size": {
                                            "$regex": (
                                                "^"
                                                + re.escape(
                                                    size_value
                                                )
                                                + "$"
                                            ),
                                            "$options": "i",
                                        }
                                    }
                                }
                            },
                        ]
                    }
                )

                if size_condition:
                    conditions.remove(
                        size_condition
                    )

        # --------------------------------------------------
        # TAGS
        # --------------------------------------------------

        if filters.tags:
            normalized_tags = [
                tag.strip()
                for tag in filters.tags
                if isinstance(tag, str)
                and tag.strip()
            ]

            if normalized_tags:
                conditions.append(
                    {
                        "tags": {
                            "$all": normalized_tags
                        }
                    }
                )

        # --------------------------------------------------
        # PRICE
        # --------------------------------------------------

        price_condition: Dict[str, Any] = {}

        if filters.min_price is not None:
            price_condition["$gte"] = (
                filters.min_price
            )

        if filters.max_price is not None:
            price_condition["$lte"] = (
                filters.max_price
            )

        if price_condition:
            conditions.append(
                {
                    "price": price_condition
                }
            )

        # --------------------------------------------------
        # STOCK
        # --------------------------------------------------

        if filters.in_stock_only:
            conditions.append(
                {
                    "$or": [
                        {
                            "stock": {
                                "$gt": 0
                            }
                        },
                        {
                            "variants": {
                                "$elemMatch": {
                                    "stock": {
                                        "$gt": 0
                                    }
                                }
                            }
                        },
                    ]
                }
            )

        # --------------------------------------------------
        # APPLY ALL CONDITIONS
        # --------------------------------------------------

        if conditions:
            query["$and"] = conditions

        # --------------------------------------------------
        # SORT
        # --------------------------------------------------

        cursor = collections.products(
            tenant_id
        ).find(query)

        sort_map = {
            "price_asc": [
                ("price", 1),
                ("_id", 1),
            ],
            "price_desc": [
                ("price", -1),
                ("_id", 1),
            ],
            "newest": [
                ("created_at", -1),
                ("_id", 1),
            ],
        }

        sort_spec = sort_map.get(
            filters.sort_by
        )

        if sort_spec:
            cursor = cursor.sort(
                sort_spec
            )

        # --------------------------------------------------
        # PAGINATION
        # --------------------------------------------------

        offset = max(
            0,
            int(filters.offset),
        )

        limit = max(
            1,
            min(
                int(filters.limit),
                100,
            ),
        )

        cursor = (
            cursor
            .skip(offset)
            .limit(limit)
        )

        # --------------------------------------------------
        # RESULT CONVERSION
        # --------------------------------------------------

        products: List[Product] = []

        async for document in cursor:
            try:
                product = Product(
                    **normalize_mongo_doc(
                        document
                    )
                )

                products.append(product)

            except Exception:
                logger.exception(
                    "Invalid product document "
                    "skipped: %s",
                    document.get("_id"),
                )

        logger.info(
            "Product search returned %s results "
            "for tenant %s",
            len(products),
            tenant_id,
        )

        return products


product_repository = ProductRepository()