"""
Product service.

Responsibilities:

- tenant-scoped product search
- product retrieval
- product availability
- entity -> product filter conversion
- candidate ranking
- variant-aware inventory summaries
- WhatsApp response conversion

MongoDB access belongs exclusively to ProductRepository.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.models.schemas import (
    EntityType,
    ExtractedEntity,
    Product,
    ProductSearchFilters,
    ResponseProduct,
)
from app.repositories.product_repository import (
    product_repository,
)
from app.services.catalog_metadata_service import (
    catalog_metadata_service,
)
from app.utils.logger import logger


class ProductService:
    """
    Business layer for product operations.

    Search workflow:

        MongoDB candidate search
                ↓
        deterministic relevance ranking
                ↓
        top ranked products
    """

    def __init__(
        self,
        product_repository_instance=product_repository,
    ) -> None:
        self.product_repository = (
            product_repository_instance
        )

    # =========================================================
    # SEARCH
    # =========================================================

    async def search_products(
        self,
        tenant_id: str,
        filters: ProductSearchFilters,
    ) -> List[Product]:
        """
        Search and rank products.

        MongoDB performs the hard filtering.

        Ranking is deliberately performed in Python after the
        candidate query because MongoDB should not be responsible
        for conversational relevance scoring.
        """

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if filters is None:
            raise ValueError(
                "filters are required"
            )

        products = await self.product_repository.search(
            tenant_id=tenant_id,
            filters=filters,
        )

        if not products:
            return []

        for product in products:
            await self._enrich_product_metadata(
                product,
                tenant_id,
            )

        ranked = self.rank_products(
            products=products,
            filters=filters,
        )

        return ranked

    # =========================================================
    # RANKING
    # =========================================================

    @classmethod
    def rank_products(
        cls,
        products: List[Product],
        filters: ProductSearchFilters,
    ) -> List[Product]:
        """
        Rank already-filtered candidates.

        Higher score means stronger relevance.

        Ranking priorities:

        1. exact category
        2. exact type
        3. exact color
        4. exact size
        5. exact brand
        6. material
        7. fit
        8. gender / department
        9. text/title relevance
        10. stock
        11. featured products

        Canonical catalogue IDs are preferred when available.
        Text fields remain as fallback for legacy documents.
        """

        scored: List[
            Tuple[float, int, Product]
        ] = []

        query = (
            filters.query.strip().lower()
            if filters.query
            else ""
        )

        category = (
            filters.category.strip().lower()
            if filters.category
            else ""
        )

        product_type = (
            filters.type.strip().lower()
            if filters.type
            else ""
        )

        color = (
            filters.color.strip().lower()
            if filters.color
            else ""
        )

        size = (
            filters.size.strip().lower()
            if filters.size
            else ""
        )

        brand = (
            filters.brand.strip().lower()
            if filters.brand
            else ""
        )

        material = (
            filters.material.strip().lower()
            if filters.material
            else ""
        )

        fit = (
            filters.fit.strip().lower()
            if filters.fit
            else ""
        )

        gender = (
            filters.gender.strip().lower()
            if filters.gender
            else ""
        )

        department_id = getattr(
            filters,
            "department_id",
            None,
        )

        category_id = getattr(
            filters,
            "category_id",
            None,
        )

        color_id = getattr(
            filters,
            "color_id",
            None,
        )

        size_id = getattr(
            filters,
            "size_id",
            None,
        )

        for index, product in enumerate(products):
            score = 0.0

            title = (
                product.title or ""
            ).strip().lower()

            description = (
                product.description or ""
            ).strip().lower()

            product_category = (
                product.category or ""
            ).strip().lower()

            product_type_value = (
                product.type or ""
            ).strip().lower()

            product_brand = (
                product.brand or ""
            ).strip().lower()

            product_material = (
                product.material or ""
            ).strip().lower()

            product_fit = (
                product.fit or ""
            ).strip().lower()

            product_gender = (
                product.gender or ""
            ).strip().lower()

            # -------------------------------------------------
            # CANONICAL IDS
            # -------------------------------------------------

            product_department_id = getattr(
                product,
                "department_id",
                None,
            )

            product_category_id = getattr(
                product,
                "category_id",
                None,
            )

            raw_color_ids = getattr(
                product,
                "color_ids",
                [],
            ) or []

            raw_size_ids = getattr(
                product,
                "size_ids",
                [],
            ) or []

            product_color_ids = set()

            for value in raw_color_ids:
                try:
                    product_color_ids.add(
                        int(value)
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    continue

            product_size_ids = set()

            for value in raw_size_ids:
                try:
                    product_size_ids.add(
                        int(value)
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    continue

            # -------------------------------------------------
            # LEGACY TEXT VALUES
            # -------------------------------------------------

            product_colors = {
                str(value).strip().lower()
                for value in (
                    product.color or []
                )
                if str(value).strip()
            }

            product_sizes = {
                str(value).strip().lower()
                for value in (
                    product.size or []
                )
                if str(value).strip()
            }

            # -------------------------------------------------
            # CATEGORY
            # -------------------------------------------------

            if category_id is not None:
                try:
                    if (
                        product_category_id
                        is not None
                        and int(
                            product_category_id
                        )
                        == int(category_id)
                    ):
                        score += 100
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

            elif category:
                if product_category == category:
                    score += 100

                elif category in product_category:
                    score += 60

            # -------------------------------------------------
            # TYPE
            # -------------------------------------------------

            if product_type:
                if product_type_value == product_type:
                    score += 90

                elif product_type in product_type_value:
                    score += 50

            # -------------------------------------------------
            # COLOR
            # -------------------------------------------------

            if color_id is not None:
                try:
                    if int(color_id) in product_color_ids:
                        score += 90
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

            elif color:
                if color in product_colors:
                    score += 90

            # -------------------------------------------------
            # SIZE
            # -------------------------------------------------

            if size_id is not None:
                try:
                    if int(size_id) in product_size_ids:
                        score += 90
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

            elif size:
                if size in product_sizes:
                    score += 90

            # -------------------------------------------------
            # BRAND
            # -------------------------------------------------

            if brand:
                if product_brand == brand:
                    score += 70

                elif brand in product_brand:
                    score += 35

            # -------------------------------------------------
            # MATERIAL
            # -------------------------------------------------

            if material:
                if product_material == material:
                    score += 50

                elif material in product_material:
                    score += 25

            # -------------------------------------------------
            # FIT
            # -------------------------------------------------

            if fit:
                if product_fit == fit:
                    score += 45

            # -------------------------------------------------
            # GENDER / DEPARTMENT
            # -------------------------------------------------

            if department_id is not None:
                try:
                    if (
                        product_department_id
                        is not None
                        and int(
                            product_department_id
                        )
                        == int(department_id)
                    ):
                        score += 40
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

            elif gender:
                if product_gender == gender:
                    score += 40

            # -------------------------------------------------
            # FREE TEXT / PRODUCT QUERY
            # -------------------------------------------------

            if query:
                query_tokens = {
                    token
                    for token in query.split()
                    if token
                }

                for token in query_tokens:
                    if token in title:
                        score += 30

                    elif token in description:
                        score += 10

                    elif token in product_category:
                        score += 20

                    elif token in product_type_value:
                        score += 20

                    elif token in product_brand:
                        score += 15

            # -------------------------------------------------
            # METADATA-DEFINED ATTRIBUTES
            # -------------------------------------------------

            for attribute_key, requested_value in (
                (getattr(filters, "attributes", {}) or {}).items()
            ):
                if requested_value is None:
                    continue
                product_attributes = getattr(product, "attributes", {}) or {}
                actual_value = product_attributes.get(attribute_key)
                if actual_value is None:
                    actual_value = getattr(product, attribute_key, None)
                if actual_value is not None and str(actual_value).strip().lower() == str(requested_value).strip().lower():
                    score += 80

            # -------------------------------------------------
            # STOCK
            # -------------------------------------------------

            stock = cls._variant_inventory_summary(
                product
            )["stock"]

            if stock > 0:
                score += 10

                score += min(
                    stock,
                    10,
                ) * 0.5

            # -------------------------------------------------
            # FEATURED
            # -------------------------------------------------

            if product.is_featured:
                score += 5

            scored.append(
                (
                    score,
                    index,
                    product,
                )
            )

        scored.sort(
            key=lambda item: (
                -item[0],
                item[1],
            )
        )

        ranked = [
            item[2]
            for item in scored
        ]

        logger.info(
            "Ranked %s product candidates "
            "for query=%s category=%s "
            "color=%s size=%s "
            "department_id=%s category_id=%s "
            "color_id=%s size_id=%s",
            len(ranked),
            filters.query,
            filters.category,
            filters.color,
            filters.size,
            department_id,
            category_id,
            color_id,
            size_id,
        )

        return ranked

    # =========================================================
    # RETRIEVAL
    # =========================================================

    async def get_product_by_id(
        self,
        tenant_id: str,
        product_id: str,
    ) -> Optional[Product]:

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if not product_id:
            return None

        product = await (
            self.product_repository.find_by_id(
                tenant_id=tenant_id,
                product_id=product_id,
            )
        )

        if product:
            await self._enrich_product_metadata(
                product,
                tenant_id,
            )

        return product

    async def get_products_by_ids(
        self,
        tenant_id: str,
        product_ids: List[str],
    ) -> List[Product]:

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if not product_ids:
            return []

        valid_ids = [
            product_id.strip()
            for product_id in product_ids
            if isinstance(product_id, str)
            and product_id.strip()
        ]

        if not valid_ids:
            return []

        products = await (
            self.product_repository.find_by_ids(
                tenant_id=tenant_id,
                product_ids=valid_ids,
            )
        )

        for product in products:
            await self._enrich_product_metadata(
                product,
                tenant_id,
            )

        return products

    async def get_product_by_reference(
        self,
        tenant_id: str,
        reference: str,
    ) -> Optional[Product]:

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if not reference or not reference.strip():
            return None

        reference = reference.strip()

        product = await self.get_product_by_id(
            tenant_id=tenant_id,
            product_id=reference,
        )

        if product:
            return product

        product = await (
            self.product_repository.find_by_title(
                tenant_id=tenant_id,
                title=reference,
            )
        )

        if product:
            await self._enrich_product_metadata(
                product,
                tenant_id,
            )

        return product

    # =========================================================
    # METADATA DISPLAY ENRICHMENT
    # =========================================================

    @staticmethod
    async def _enrich_product_metadata(
        product: Product,
        tenant_id: str,
    ) -> Product:
        """
        Resolve canonical metadata IDs into human-readable product values.

        Inventory documents may intentionally store only numeric IDs for
        colors and sizes. Search can use those IDs directly, but the
        WhatsApp response needs the corresponding names. This enrichment
        happens after repository retrieval so the repository remains
        responsible only for persistence/querying.
        """

        metadata = await catalog_metadata_service.get_metadata(
            tenant_id
        )

        if not metadata:
            return product

        # -----------------------------------------------------
        # COLOR ID -> COLOR NAME
        # -----------------------------------------------------

        color_map = metadata.get("color_map") or {}
        color_by_id: Dict[int, str] = {}

        if isinstance(color_map, dict):
            for name, raw_id in color_map.items():
                try:
                    color_by_id[int(raw_id)] = str(name).strip()
                except (TypeError, ValueError):
                    continue

        existing_colors = [
            str(value).strip()
            for value in (product.color or [])
            if str(value).strip()
        ]

        if not existing_colors and product.color_ids:
            for raw_id in product.color_ids:
                try:
                    name = color_by_id.get(int(raw_id))
                except (TypeError, ValueError):
                    name = None
                if name:
                    existing_colors.append(name)

        product.color = list(dict.fromkeys(existing_colors))

        # -----------------------------------------------------
        # SIZE ID -> SIZE NAME
        # -----------------------------------------------------

        size_groups = metadata.get("size_groups") or {}
        size_group_name = product.size_group

        if not size_group_name:
            size_group_name = (
                catalog_metadata_service
                .resolve_size_group_from_category_id(
                    metadata,
                    getattr(product, "department_id", None),
                    getattr(product, "category_id", None),
                )
            )

        # Final fallback for legacy products that still have only textual
        # category data. New ID-only inventory does not depend on this.
        if not size_group_name:
            size_group_name = catalog_metadata_service._resolve_size_group(
                metadata,
                product.category,
            )

        size_by_id: Dict[int, str] = {}
        if isinstance(size_groups, dict) and size_group_name:
            group = size_groups.get(size_group_name)
            if isinstance(group, dict):
                for name, raw_id in group.items():
                    try:
                        size_by_id[int(raw_id)] = str(name).strip()
                    except (TypeError, ValueError):
                        continue

        existing_sizes = [
            str(value).strip()
            for value in (product.size or [])
            if str(value).strip()
        ]

        if not existing_sizes and product.size_ids:
            for raw_id in product.size_ids:
                try:
                    name = size_by_id.get(int(raw_id))
                except (TypeError, ValueError):
                    name = None
                if name:
                    existing_sizes.append(name)

        product.size = list(dict.fromkeys(existing_sizes))
        if size_group_name:
            product.size_group = str(size_group_name)

        # -----------------------------------------------------
        # VARIANT ID -> NAME ENRICHMENT
        # -----------------------------------------------------

        enriched_variants: List[Dict[str, Any]] = []

        for raw_variant in product.variants or []:
            variant = dict(raw_variant) if isinstance(raw_variant, dict) else {}
            if not variant:
                continue

            if not str(variant.get("color") or "").strip():
                try:
                    color_name = color_by_id.get(int(variant.get("color_id")))
                except (TypeError, ValueError):
                    color_name = None
                if color_name:
                    variant["color"] = color_name

            if not str(variant.get("size") or "").strip():
                try:
                    size_name = size_by_id.get(int(variant.get("size_id")))
                except (TypeError, ValueError):
                    size_name = None
                if size_name:
                    variant["size"] = size_name

            enriched_variants.append(variant)

        product.variants = enriched_variants

        return product

    # =========================================================
    # VARIANT HELPERS
    # =========================================================

    @staticmethod
    def _variant_values(
        variant: Any,
    ) -> Dict[str, Any]:
        """
        Normalize a variant document without assuming
        one specific storage shape.
        """

        if hasattr(
            variant,
            "model_dump",
        ):
            data = variant.model_dump()

        elif isinstance(
            variant,
            dict,
        ):
            data = dict(variant)

        else:
            return {}

        return data

    @classmethod
    def _matching_variants(
        cls,
        product: Product,
        *,
        size: Optional[str] = None,
        color: Optional[str] = None,
        in_stock_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Return variants matching all supplied attributes
        on the SAME variant.
        """

        variants = [
            cls._variant_values(variant)
            for variant in (
                product.variants or []
            )
        ]

        variants = [
            variant
            for variant in variants
            if variant
        ]

        if not variants:
            return []

        normalized_size = (
            size.strip().lower()
            if size
            else None
        )

        normalized_color = (
            color.strip().lower()
            if color
            else None
        )

        matches: List[
            Dict[str, Any]
        ] = []

        for variant in variants:
            variant_size = str(
                variant.get(
                    "size",
                    "",
                )
            ).strip().lower()

            variant_color = str(
                variant.get(
                    "color",
                    "",
                )
            ).strip().lower()

            if (
                normalized_size is not None
                and variant_size
                != normalized_size
            ):
                continue

            if (
                normalized_color is not None
                and variant_color
                != normalized_color
            ):
                continue

            try:
                stock = int(
                    variant.get(
                        "stock",
                        0,
                    )
                    or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                stock = 0

            if (
                in_stock_only
                and stock <= 0
            ):
                continue

            matches.append(
                variant
            )

        return matches

    @classmethod
    def _variant_inventory_summary(
        cls,
        product: Product,
    ) -> Dict[str, Any]:
        """
        Build stock, size, color and price information
        from variants.
        """

        variants = [
            cls._variant_values(variant)
            for variant in (
                product.variants or []
            )
        ]

        variants = [
            variant
            for variant in variants
            if variant
        ]

        if not variants:
            return {
                "stock": int(
                    product.stock or 0
                ),
                "available_sizes": sorted(
                    {
                        str(value).strip()
                        for value in product.size
                        if value
                        and str(value).strip()
                    }
                ),
                "available_colors": sorted(
                    {
                        str(value).strip()
                        for value in product.color
                        if value
                        and str(value).strip()
                    }
                ),
                "sale_price": None,
            }

        total_stock = 0

        available_sizes = set()

        available_colors = set()

        sale_prices: List[float] = []

        for variant in variants:
            try:
                stock = int(
                    variant.get(
                        "stock",
                        0,
                    )
                    or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                stock = 0

            if stock > 0:
                total_stock += stock

                size_value = str(
                    variant.get(
                        "size",
                        "",
                    )
                ).strip()

                color_value = str(
                    variant.get(
                        "color",
                        "",
                    )
                ).strip()

                if size_value:
                    available_sizes.add(
                        size_value
                    )

                if color_value:
                    available_colors.add(
                        color_value
                    )

            sale_price = variant.get(
                "sale_price"
            )

            if sale_price is not None:
                try:
                    sale_prices.append(
                        float(
                            sale_price
                        )
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

        return {
            "stock": total_stock,
            "available_sizes": sorted(
                available_sizes
            ),
            "available_colors": sorted(
                available_colors
            ),
            "sale_price": (
                min(sale_prices)
                if sale_prices
                else None
            ),
        }

    # =========================================================
    # AVAILABILITY
    # =========================================================

    async def check_availability(
        self,
        tenant_id: str,
        product_id: str,
        size: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check product availability with variant-aware
        stock semantics.
        """

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        product = await (
            self.get_product_by_reference(
                tenant_id=tenant_id,
                reference=product_id,
            )
        )

        if not product:
            return {
                "available": False,
                "reason": "product_not_found",
                "product_name": product_id,
            }

        variants = [
            self._variant_values(variant)
            for variant in (
                product.variants or []
            )
        ]

        variants = [
            variant
            for variant in variants
            if variant
        ]

        if variants:
            matching = (
                self._matching_variants(
                    product,
                    size=size,
                    color=color,
                    in_stock_only=True,
                )
            )

            all_size_matches = (
                self._matching_variants(
                    product,
                    size=size,
                    color=None,
                    in_stock_only=False,
                )
                if size
                else variants
            )

            all_color_matches = (
                self._matching_variants(
                    product,
                    size=None,
                    color=color,
                    in_stock_only=False,
                )
                if color
                else variants
            )

            summary = (
                self._variant_inventory_summary(
                    product
                )
            )

            if not matching:
                if (
                    size
                    and not all_size_matches
                ):
                    reason = (
                        "size_not_available"
                    )

                elif (
                    color
                    and not all_color_matches
                ):
                    reason = (
                        "color_not_available"
                    )

                else:
                    reason = (
                        "variant_not_found"
                        if (
                            size
                            or color
                        )
                        else "out_of_stock"
                    )

                return {
                    "available": False,
                    "reason": reason,
                    "product_name": product.title,
                    "requested_size": size,
                    "requested_color": color,
                    "stock": summary["stock"],
                    "available_sizes": (
                        summary[
                            "available_sizes"
                        ]
                    ),
                    "available_colors": (
                        summary[
                            "available_colors"
                        ]
                    ),
                }

            matching_stock = 0

            matching_prices: List[
                float
            ] = []

            matching_sale_prices: List[
                float
            ] = []

            for variant in matching:
                try:
                    matching_stock += int(
                        variant.get(
                            "stock",
                            0,
                        )
                        or 0
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

                if (
                    variant.get(
                        "price"
                    )
                    is not None
                ):
                    try:
                        matching_prices.append(
                            float(
                                variant[
                                    "price"
                                ]
                            )
                        )
                    except (
                        TypeError,
                        ValueError,
                    ):
                        pass

                if (
                    variant.get(
                        "sale_price"
                    )
                    is not None
                ):
                    try:
                        matching_sale_prices.append(
                            float(
                                variant[
                                    "sale_price"
                                ]
                            )
                        )
                    except (
                        TypeError,
                        ValueError,
                    ):
                        pass

            return {
                "available": (
                    matching_stock > 0
                ),
                "reason": (
                    "available"
                    if matching_stock > 0
                    else "out_of_stock"
                ),
                "product_name": product.title,
                "product_id": product.id,
                "stock": matching_stock,
                "requested_size": size,
                "requested_color": color,
                "available_sizes": (
                    summary[
                        "available_sizes"
                    ]
                ),
                "available_colors": (
                    summary[
                        "available_colors"
                    ]
                ),
                "price": (
                    min(matching_prices)
                    if matching_prices
                    else product.price
                ),
                "sale_price": (
                    min(
                        matching_sale_prices
                    )
                    if matching_sale_prices
                    else summary[
                        "sale_price"
                    ]
                ),
                "variant_skus": [
                    str(v["sku"])
                    for v in matching
                    if v.get("sku")
                ],
            }

        # -----------------------------------------------------
        # LEGACY PRODUCT-LEVEL INVENTORY
        # -----------------------------------------------------

        requested_size = (
            size.strip().lower()
            if size
            else None
        )

        requested_color = (
            color.strip().lower()
            if color
            else None
        )

        available_sizes = [
            str(value).strip()
            for value in product.size
            if value
            and str(value).strip()
        ]

        available_colors = [
            str(value).strip()
            for value in product.color
            if value
            and str(value).strip()
        ]

        size_matches = (
            requested_size is None
            or any(
                value.lower()
                == requested_size
                for value in available_sizes
            )
        )

        color_matches = (
            requested_color is None
            or any(
                value.lower()
                == requested_color
                for value in available_colors
            )
        )

        if not size_matches:
            return {
                "available": False,
                "reason": (
                    "size_not_available"
                ),
                "product_name": product.title,
                "requested_size": size,
                "available_sizes": sorted(
                    available_sizes
                ),
                "available_colors": sorted(
                    available_colors
                ),
                "stock": product.stock,
            }

        if not color_matches:
            return {
                "available": False,
                "reason": (
                    "color_not_available"
                ),
                "product_name": product.title,
                "requested_color": color,
                "available_sizes": sorted(
                    available_sizes
                ),
                "available_colors": sorted(
                    available_colors
                ),
                "stock": product.stock,
            }

        if product.stock <= 0:
            return {
                "available": False,
                "reason": "out_of_stock",
                "product_name": product.title,
                "stock": 0,
                "available_sizes": sorted(
                    available_sizes
                ),
                "available_colors": sorted(
                    available_colors
                ),
            }

        return {
            "available": True,
            "reason": "available",
            "product_name": product.title,
            "product_id": product.id,
            "stock": product.stock,
            "requested_size": size,
            "requested_color": color,
            "available_sizes": sorted(
                available_sizes
            ),
            "available_colors": sorted(
                available_colors
            ),
            "price": product.price,
            "sale_price": None,
        }

    # =========================================================
    # PRODUCT INQUIRY
    # =========================================================

    async def get_product_inquiry(
        self,
        tenant_id: str,
        product_id: str,
    ) -> Optional[Product]:
        """
        Retrieve a full product for product inquiry.
        """

        return await self.get_product_by_id(
            tenant_id=tenant_id,
            product_id=product_id,
        )

    # =========================================================
    # ENTITY -> FILTERS
    # =========================================================

    def entities_to_filters(
        self,
        entities: List[ExtractedEntity],
    ) -> ProductSearchFilters:
        """
        Convert extracted entities into product search
        filters.

        The entity extractor may provide canonical metadata
        such as:

            department_id
            category_id
            color_id
            size_id
            size_group

        When present, these IDs are stored in the filters.

        Text values are also retained so that the system can
        continue supporting legacy inventory documents.
        """

        filters = ProductSearchFilters()

        for entity in entities:
            value = (
                entity.normalized_value
                or entity.value
            )

            if not value:
                continue

            value = value.strip()

            if not value:
                continue

            entity_type = entity.entity_type

            metadata = (
                entity.metadata or {}
            )

            if entity_type == EntityType.PRODUCT:
                filters.query = value.lower()

            elif entity_type == EntityType.CATEGORY:
                filters.category = value.lower()

                category_id = metadata.get(
                    "category_id"
                )

                if category_id is not None:
                    try:
                        filters.category_id = int(
                            category_id
                        )
                    except (
                        TypeError,
                        ValueError,
                    ):
                        logger.warning(
                            "Invalid category_id "
                            "metadata: %s",
                            category_id,
                        )

            elif entity_type == EntityType.COLOR:
                filters.color = value.lower()

                color_id = metadata.get(
                    "color_id"
                )

                if color_id is not None:
                    try:
                        filters.color_id = int(
                            color_id
                        )
                    except (
                        TypeError,
                        ValueError,
                    ):
                        logger.warning(
                            "Invalid color_id "
                            "metadata: %s",
                            color_id,
                        )

            elif entity_type == EntityType.SIZE:
                filters.size = value.upper()

                size_id = metadata.get(
                    "size_id"
                )

                if size_id is not None:
                    try:
                        filters.size_id = int(
                            size_id
                        )
                    except (
                        TypeError,
                        ValueError,
                    ):
                        logger.warning(
                            "Invalid size_id "
                            "metadata: %s",
                            size_id,
                        )

                size_group = metadata.get(
                    "size_group"
                )

                if size_group:
                    filters.size_group = str(
                        size_group
                    ).strip().lower()

            elif entity_type == EntityType.STYLE:
                # Style is a metadata-defined attribute (for example
                # dress_style=maxi), not the product type.
                filters.style = value.lower()
                filters.attributes["style"] = value.lower()

            elif entity_type in {
                EntityType.PATTERN,
                EntityType.OCCASION,
                EntityType.SEASON,
                EntityType.SLEEVE,
                EntityType.NECK,
            }:
                key = entity_type.value
                filters.attributes[key] = value.lower()
                setattr(filters, key, value.lower())

            elif entity_type == EntityType.BRAND:
                filters.brand = value.lower()

            elif entity_type == EntityType.MATERIAL:
                filters.material = value.lower()

            elif entity_type == EntityType.FIT:
                filters.fit = value.lower()

            elif entity_type == EntityType.GENDER:
                filters.gender = value.lower()

                department_id = metadata.get(
                    "department_id"
                )

                if department_id is not None:
                    try:
                        filters.department_id = int(
                            department_id
                        )
                    except (
                        TypeError,
                        ValueError,
                    ):
                        logger.warning(
                            "Invalid department_id "
                            "metadata: %s",
                            department_id,
                        )

            elif entity_type == EntityType.PRICE:
                self._apply_price_entity(
                    filters=filters,
                    entity=entity,
                    value=value,
                )

        return filters

    # =========================================================
    # PRICE
    # =========================================================

    @staticmethod
    def _apply_price_entity(
        filters: ProductSearchFilters,
        entity: ExtractedEntity,
        value: str,
    ) -> None:
        """
        Convert a PRICE entity to price filters.
        """

        try:
            price = float(value)

        except (
            ValueError,
            TypeError,
        ):
            logger.warning(
                "Unable to parse price entity: %s",
                value,
            )

            return

        metadata = entity.metadata or {}

        operator = metadata.get(
            "operator",
            "max",
        )

        if operator == "max":
            filters.max_price = price

        elif operator == "min":
            filters.min_price = price

        elif operator == "exact":
            filters.min_price = price
            filters.max_price = price

        else:
            filters.max_price = price

    # =========================================================
    # RESPONSE CONVERSION
    # =========================================================

    @classmethod
    def product_to_response(
        cls,
        product: Product,
    ) -> ResponseProduct:
        """
        Convert a product to a WhatsApp-safe response model.
        """

        summary = (
            cls._variant_inventory_summary(
                product
            )
        )

        image = (
            product.media[0]
            if product.media
            else None
        )

        if not image:
            for raw_variant in (
                product.variants
            ):
                variant = cls._variant_values(
                    raw_variant
                )

                images = (
                    variant.get(
                        "images"
                    )
                    or variant.get(
                        "media"
                    )
                    or []
                )

                if images:
                    image = str(
                        images[0]
                    )
                    break

        return ResponseProduct(
            product_id=product.id,
            name=product.title,
            price=product.price,
            sale_price=summary[
                "sale_price"
            ],
            currency="INR",
            image=image,
            stock=summary["stock"],
            category=product.category,
            product_type=product.type,
            description=product.description,
            sizes_available=summary[
                "available_sizes"
            ],
            colors_available=summary[
                "available_colors"
            ],
            in_stock=(
                summary["stock"] > 0
            ),
        )


product_service = ProductService()