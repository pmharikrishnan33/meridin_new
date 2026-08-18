"""
Product service.

Handles:
- product search
- product retrieval
- product availability
- entity -> product filter conversion
- response transformation

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

    async def check_availability(
        self,
        tenant_id: str,
        product_id: str,
        size: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check availability using the current flat inventory model.

        Current database contract:
        - stock is product-level
        - size is an available size list
        - color is an available color list

        Size/color do not represent independent stock variants yet.
        """

        product = await self.get_product_by_reference(
            tenant_id=tenant_id,
            reference=product_id,
        )

        if not product:
            return {
                "available": False,
                "reason": "product_not_found",
            }

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
            value.strip()
            for value in product.size
        ]

        available_colors = [
            value.strip()
            for value in product.color
        ]

        size_matches = (
            True
            if requested_size is None
            else any(
                value.lower()
                == requested_size
                for value in available_sizes
            )
        )

        color_matches = (
            True
            if requested_color is None
            else any(
                value.lower()
                == requested_color
                for value in available_colors
            )
        )

        if not size_matches:
            return {
                "available": False,
                "reason": "size_not_available",
                "product_name": product.title,
                "requested_size": size,
                "available_sizes": sorted(
                    available_sizes
                ),
                "stock": product.stock,
            }

        if not color_matches:
            return {
                "available": False,
                "reason": "color_not_available",
                "product_name": product.title,
                "requested_color": color,
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
        Convert extracted entities into product filters.

        Supported with the current inventory schema:

        PRODUCT  -> query
        CATEGORY -> category
        COLOR    -> color
        SIZE     -> size
        STYLE    -> type
        PRICE    -> min/max price
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

            if entity.entity_type == EntityType.PRODUCT:
                filters.query = value.lower()

            elif entity.entity_type == EntityType.CATEGORY:
                filters.category = value.lower()

            elif entity.entity_type == EntityType.COLOR:
                filters.color = value.lower()

            elif entity.entity_type == EntityType.SIZE:
                filters.size = value.upper()

            elif entity.entity_type == EntityType.STYLE:
                filters.type = value.lower()

            elif entity.entity_type == EntityType.PRICE:
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

    @staticmethod
    def product_to_response(
        product: Product,
    ) -> ResponseProduct:
        """
        Convert the actual inventory Product model
        into a WhatsApp response product.
        """

        sizes = sorted(
            product.size
        )

        colors = sorted(
            product.color
        )

        in_stock = (
            product.stock > 0
        )

        image = (
            product.media[0]
            if product.media
            else None
        )

        return ResponseProduct(
            product_id=product.id,
            name=product.title,
            price=product.price,
            sale_price=None,
            currency="INR",
            image=image,
            stock=product.stock,
            category=product.category,
            product_type=product.type,
            description=product.description,
            sizes_available=sizes,
            colors_available=colors,
            in_stock=in_stock,
        )


product_service = ProductService()