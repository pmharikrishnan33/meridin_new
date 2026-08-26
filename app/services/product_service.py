"""
Product service.

Handles:
- product search
- product retrieval
- product availability
- entity -> product filter conversion
- response transformation
- bulk product retrieval for pagination

Database access belongs to ProductRepository.
"""

from typing import Any, Dict, List, Optional

from app.models.schemas import (
    Product,
    ProductSearchFilters,
    ResponseProduct,
    ExtractedEntity,
    EntityType,
)
from app.repositories.product_repository import (
    product_repository,
)
from app.utils.logger import logger


class ProductService:
    """Business logic for product-related operations."""

    def __init__(
        self,
        product_repository_instance=product_repository,
    ):
        self.product_repository = (
            product_repository_instance
        )

    async def search_products(
        self,
        tenant_id: str,
        filters: ProductSearchFilters,
    ) -> List[Product]:
        """
        Search products for a tenant.

        MongoDB access is handled exclusively
        by ProductRepository.
        """

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        return await self.product_repository.search(
            tenant_id=tenant_id,
            filters=filters,
        )

    async def get_product_by_id(
        self,
        tenant_id: str,
        product_id: str,
    ) -> Optional[Product]:
        """
        Retrieve a product by MongoDB ID.
        """

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if not product_id:
            return None

        return await self.product_repository.find_by_id(
            tenant_id=tenant_id,
            product_id=product_id,
        )

    async def get_products_by_ids(
        self,
        tenant_id: str,
        product_ids: List[str],
    ) -> List[Product]:
        """
        Retrieve multiple products by their IDs.

        Used by pagination so that the next three products
        can be fetched in a single database operation.

        IMPORTANT:
        ProductRepository may not return products in the
        same order as product_ids. The caller must restore
        the original ranking/order when necessary.
        """

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if not product_ids:
            return []

        # Remove invalid IDs while preserving order.
        valid_product_ids = [
            product_id
            for product_id in product_ids
            if product_id
            and isinstance(product_id, str)
            and product_id.strip()
        ]

        if not valid_product_ids:
            return []

        return await self.product_repository.find_by_ids(
            tenant_id=tenant_id,
            product_ids=valid_product_ids,
        )

    async def get_product_by_reference(
        self,
        tenant_id: str,
        reference: str,
    ) -> Optional[Product]:
        """
        Find a product using:
        1. product ID
        2. exact title match
        """

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if not reference or not reference.strip():
            return None

        reference = reference.strip()

        # First try the stable product ID.
        product = await self.get_product_by_id(
            tenant_id=tenant_id,
            product_id=reference,
        )

        if product:
            return product

        # Then let the repository perform
        # the exact title lookup.
        return await self.product_repository.find_by_title(
            tenant_id=tenant_id,
            title=reference,
        )

    @staticmethod
    def _variant_values(variant: Any) -> Dict[str, Any]:
        """Normalize a variant document without assuming one storage shape."""
        if hasattr(variant, "model_dump"):
            data = variant.model_dump()
        elif isinstance(variant, dict):
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
        """Return variants matching all supplied attributes on the SAME variant."""
        variants = [
            cls._variant_values(variant)
            for variant in (product.variants or [])
        ]
        variants = [variant for variant in variants if variant]

        if not variants:
            return []

        normalized_size = size.strip().lower() if size else None
        normalized_color = color.strip().lower() if color else None

        matches: List[Dict[str, Any]] = []

        for variant in variants:
            variant_size = str(variant.get("size", "")).strip().lower()
            variant_color = str(variant.get("color", "")).strip().lower()

            if normalized_size is not None and variant_size != normalized_size:
                continue

            if normalized_color is not None and variant_color != normalized_color:
                continue

            try:
                stock = int(variant.get("stock", 0) or 0)
            except (TypeError, ValueError):
                stock = 0

            if in_stock_only and stock <= 0:
                continue

            matches.append(variant)

        return matches

    @classmethod
    def _variant_inventory_summary(
        cls,
        product: Product,
    ) -> Dict[str, Any]:
        """Build stock, size, color and price information from variants."""
        variants = [
            cls._variant_values(variant)
            for variant in (product.variants or [])
        ]
        variants = [variant for variant in variants if variant]

        if not variants:
            return {
                "stock": int(product.stock or 0),
                "available_sizes": sorted({
                    str(value).strip()
                    for value in product.size
                    if value and str(value).strip()
                }),
                "available_colors": sorted({
                    str(value).strip()
                    for value in product.color
                    if value and str(value).strip()
                }),
                "sale_price": None,
            }

        total_stock = 0
        available_sizes = set()
        available_colors = set()
        sale_prices: List[float] = []

        for variant in variants:
            try:
                stock = int(variant.get("stock", 0) or 0)
            except (TypeError, ValueError):
                stock = 0

            if stock > 0:
                total_stock += stock

                size_value = str(variant.get("size", "")).strip()
                color_value = str(variant.get("color", "")).strip()

                if size_value:
                    available_sizes.add(size_value)
                if color_value:
                    available_colors.add(color_value)

            sale_price = variant.get("sale_price")
            if sale_price is not None:
                try:
                    sale_prices.append(float(sale_price))
                except (TypeError, ValueError):
                    pass

        return {
            "stock": total_stock,
            "available_sizes": sorted(available_sizes),
            "available_colors": sorted(available_colors),
            "sale_price": min(sale_prices) if sale_prices else None,
        }

    async def check_availability(
        self,
        tenant_id: str,
        product_id: str,
        size: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Check product availability with variant-aware stock semantics."""

        if not tenant_id:
            raise ValueError("tenant_id is required")

        product = await self.get_product_by_reference(
            tenant_id=tenant_id,
            reference=product_id,
        )

        if not product:
            return {
                "available": False,
                "reason": "product_not_found",
                "product_name": product_id,
            }

        variants = [
            self._variant_values(variant)
            for variant in (product.variants or [])
        ]
        variants = [variant for variant in variants if variant]

        # Variant documents are authoritative when present. This prevents
        # a request for size M + color Red from accidentally matching a red
        # L variant and an M blue variant independently.
        if variants:
            matching = self._matching_variants(
                product,
                size=size,
                color=color,
                in_stock_only=True,
            )

            all_size_matches = self._matching_variants(
                product,
                size=size,
                color=None,
                in_stock_only=False,
            ) if size else variants

            all_color_matches = self._matching_variants(
                product,
                size=None,
                color=color,
                in_stock_only=False,
            ) if color else variants

            summary = self._variant_inventory_summary(product)

            if not matching:
                if size and not all_size_matches:
                    reason = "size_not_available"
                elif color and not all_color_matches:
                    reason = "color_not_available"
                else:
                    reason = "variant_not_found" if (size or color) else "out_of_stock"

                return {
                    "available": False,
                    "reason": reason,
                    "product_name": product.title,
                    "requested_size": size,
                    "requested_color": color,
                    "stock": summary["stock"],
                    "available_sizes": summary["available_sizes"],
                    "available_colors": summary["available_colors"],
                }

            matching_stock = 0
            matching_prices: List[float] = []
            matching_sale_prices: List[float] = []
            for variant in matching:
                try:
                    matching_stock += int(variant.get("stock", 0) or 0)
                except (TypeError, ValueError):
                    pass
                if variant.get("price") is not None:
                    try:
                        matching_prices.append(float(variant["price"]))
                    except (TypeError, ValueError):
                        pass
                if variant.get("sale_price") is not None:
                    try:
                        matching_sale_prices.append(float(variant["sale_price"]))
                    except (TypeError, ValueError):
                        pass

            return {
                "available": matching_stock > 0,
                "reason": "available" if matching_stock > 0 else "out_of_stock",
                "product_name": product.title,
                "product_id": product.id,
                "stock": matching_stock,
                "requested_size": size,
                "requested_color": color,
                "available_sizes": summary["available_sizes"],
                "available_colors": summary["available_colors"],
                "price": min(matching_prices) if matching_prices else product.price,
                "sale_price": min(matching_sale_prices) if matching_sale_prices else summary["sale_price"],
                "variant_skus": [str(v["sku"]) for v in matching if v.get("sku")],
            }

        # Legacy product-level inventory fallback.
        requested_size = size.strip().lower() if size else None
        requested_color = color.strip().lower() if color else None
        available_sizes = [str(value).strip() for value in product.size if value and str(value).strip()]
        available_colors = [str(value).strip() for value in product.color if value and str(value).strip()]

        size_matches = requested_size is None or any(value.lower() == requested_size for value in available_sizes)
        color_matches = requested_color is None or any(value.lower() == requested_color for value in available_colors)

        if not size_matches:
            return {
                "available": False,
                "reason": "size_not_available",
                "product_name": product.title,
                "requested_size": size,
                "available_sizes": sorted(available_sizes),
                "available_colors": sorted(available_colors),
                "stock": product.stock,
            }

        if not color_matches:
            return {
                "available": False,
                "reason": "color_not_available",
                "product_name": product.title,
                "requested_color": color,
                "available_sizes": sorted(available_sizes),
                "available_colors": sorted(available_colors),
                "stock": product.stock,
            }

        if product.stock <= 0:
            return {
                "available": False,
                "reason": "out_of_stock",
                "product_name": product.title,
                "stock": 0,
                "available_sizes": sorted(available_sizes),
                "available_colors": sorted(available_colors),
            }

        return {
            "available": True,
            "reason": "available",
            "product_name": product.title,
            "product_id": product.id,
            "stock": product.stock,
            "requested_size": size,
            "requested_color": color,
            "available_sizes": sorted(available_sizes),
            "available_colors": sorted(available_colors),
            "price": product.price,
            "sale_price": None,
        }

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

    def entities_to_filters(
        self,
        entities: List[ExtractedEntity],
    ) -> ProductSearchFilters:
        """
        Convert extracted entities into product
        search filters.
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

            if entity_type == EntityType.PRODUCT:
                filters.query = value.lower()

            elif entity_type == EntityType.CATEGORY:
                filters.category = value.lower()

            elif entity_type == EntityType.COLOR:
                filters.color = value.lower()

            elif entity_type == EntityType.SIZE:
                filters.size = value.upper()

            elif entity_type == EntityType.STYLE:
                filters.type = value.lower()

            elif entity_type == EntityType.BRAND:
                filters.brand = value.lower()

            elif entity_type == EntityType.MATERIAL:
                filters.material = value.lower()

            elif entity_type == EntityType.FIT:
                filters.fit = value.lower()

            elif entity_type == EntityType.GENDER:
                filters.gender = value.lower()

            elif entity_type == EntityType.PRICE:

                self._apply_price_entity(
                    filters=filters,
                    entity=entity,
                    value=value,
                )

        return filters

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

        except (ValueError, TypeError):

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

            # Safe default for phrases such as:
            # "under 1500"
            filters.max_price = price

    @classmethod
    def product_to_response(
        cls,
        product: Product,
    ) -> ResponseProduct:
        """Convert a product to a WhatsApp-safe response model."""
        summary = cls._variant_inventory_summary(product)

        image = product.media[0] if product.media else None
        if not image:
            for raw_variant in product.variants:
                variant = cls._variant_values(raw_variant)
                images = variant.get("images") or variant.get("media") or []
                if images:
                    image = str(images[0])
                    break

        return ResponseProduct(
            product_id=product.id,
            name=product.title,
            price=product.price,
            sale_price=summary["sale_price"],
            currency="INR",
            image=image,
            stock=summary["stock"],
            category=product.category,
            product_type=product.type,
            description=product.description,
            sizes_available=summary["available_sizes"],
            colors_available=summary["available_colors"],
            in_stock=summary["stock"] > 0,
        )



product_service = ProductService()
