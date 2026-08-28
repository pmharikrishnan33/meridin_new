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
    def _build_id_condition(
        field: str,
        value: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        """Build an exact integer ID condition for canonical catalog fields."""
        if value is None:
            return None

        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return None

        return {field: normalized}

    @staticmethod
    def _build_id_array_condition(
        field: str,
        value: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        """Match a canonical integer ID inside a MongoDB array field."""
        if value is None:
            return None

        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return None

        return {field: normalized}

    @staticmethod
    def _or_condition(
        *conditions: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Combine non-empty conditions without losing existing filters."""
        valid = [condition for condition in conditions if condition]

        if not valid:
            return None

        if len(valid) == 1:
            return valid[0]

        return {"$or": valid}

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
            "type": filters.type,
            "brand": filters.brand,
            "material": filters.material,
            "fit": filters.fit,
            "gender": filters.gender,
            "age_group": filters.age_group,
        }

        for field, value in exact_filters.items():
            condition = self._build_exact_text_condition(
                field,
                value,
            )

            if condition:
                conditions.append(condition)

        # Canonical department/category IDs are authoritative for the
        # new inventory schema. Legacy text fields remain as a fallback
        # during migration so existing products continue to work.
        department_id_condition = self._build_id_condition(
            "department_id",
            filters.department_id,
        )
        department_text_condition = self._build_exact_text_condition(
            "gender",
            filters.gender,
        )

        if department_id_condition:
            conditions.append(
                self._or_condition(
                    department_id_condition,
                    department_text_condition,
                )
            )
        elif department_text_condition:
            conditions.append(department_text_condition)

        category_id_condition = self._build_id_condition(
            "category_id",
            filters.category_id,
        )
        category_text_condition = self._build_exact_text_condition(
            "category",
            filters.category,
        )

        if category_id_condition:
            conditions.append(
                self._or_condition(
                    category_id_condition,
                    category_text_condition,
                )
            )
        elif category_text_condition:
            conditions.append(category_text_condition)

        # --------------------------------------------------
        # CANONICAL COLOR / SIZE + VARIANT FALLBACK
        # --------------------------------------------------
        # New documents use integer IDs. Older documents may still use
        # text arrays or variant-level text values. Build one OR group
        # so migration does not break existing inventory.

        color_value = (
            filters.color.strip()
            if filters.color
            else ""
        )
        size_value = (
            filters.size.strip()
            if filters.size
            else ""
        )

        color_id_condition = self._build_id_array_condition(
            "color_ids",
            filters.color_id,
        )
        size_id_condition = self._build_id_array_condition(
            "size_ids",
            filters.size_id,
        )

        color_text_condition = self._build_array_condition(
            "color",
            color_value,
        )
        size_text_condition = self._build_array_condition(
            "size",
            size_value,
        )

        color_size_conditions: List[Dict[str, Any]] = []

        if color_id_condition and size_id_condition:
            color_size_conditions.append(
                {
                    "$and": [
                        color_id_condition,
                        size_id_condition,
                    ]
                }
            )
        elif color_id_condition:
            color_size_conditions.append(
                color_id_condition
            )
        elif size_id_condition:
            color_size_conditions.append(
                size_id_condition
            )

        if color_text_condition and size_text_condition:
            color_size_conditions.append(
                {
                    "$and": [
                        color_text_condition,
                        size_text_condition,
                    ]
                }
            )
        elif color_text_condition:
            color_size_conditions.append(
                color_text_condition
            )
        elif size_text_condition:
            color_size_conditions.append(
                size_text_condition
            )

        # Variant fallback. This intentionally uses the legacy textual
        # representation because the current variant schema is textual.
        if color_value and size_value:
            color_size_conditions.append(
                {
                    "variants": {
                        "$elemMatch": {
                            "color": {
                                "$regex": "^" + re.escape(color_value) + "$",
                                "$options": "i",
                            },
                            "size": {
                                "$regex": "^" + re.escape(size_value) + "$",
                                "$options": "i",
                            },
                        }
                    }
                }
            )
        elif color_value:
            color_size_conditions.append(
                {
                    "variants": {
                        "$elemMatch": {
                            "color": {
                                "$regex": "^" + re.escape(color_value) + "$",
                                "$options": "i",
                            }
                        }
                    }
                }
            )
        elif size_value:
            color_size_conditions.append(
                {
                    "variants": {
                        "$elemMatch": {
                            "size": {
                                "$regex": "^" + re.escape(size_value) + "$",
                                "$options": "i",
                            }
                        }
                    }
                }
            )

        if color_size_conditions:
            conditions.append(
                {
                    "$or": color_size_conditions
                }
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