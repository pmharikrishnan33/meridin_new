"""Tenant-scoped catalog metadata lookup and search-filter normalization."""

import re
from typing import Any, Dict, Optional, Tuple

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.models.schemas import ProductSearchFilters


class CatalogMetadataService:
    """Uses ``inventory_metadata`` as the catalog vocabulary source of truth."""

    async def get_metadata(self, tenant_id: str) -> Dict[str, Any]:
        if not mongodb.is_connected:
            return {}
        document = await collections.inventory_metadata.find_one({"tenant_id": tenant_id})
        return dict(document) if document else {}

    @staticmethod
    def _canonical(value: str, aliases: Dict[str, Any]) -> str:
        normalized = value.strip().lower()
        for canonical, values in aliases.items():
            candidates = values if isinstance(values, list) else [values]
            if normalized == str(canonical).lower() or normalized in {
                str(candidate).lower() for candidate in candidates
            }:
                return str(canonical).lower()
        return normalized

    @staticmethod
    def _find_alias_in_text(text: str, aliases: Dict[str, Any]) -> Optional[str]:
        lowered = text.lower()
        for canonical, values in aliases.items():
            candidates = [canonical] + (values if isinstance(values, list) else [values])
            for candidate in candidates:
                if re.search(rf"\b{re.escape(str(candidate).lower())}\b", lowered):
                    return str(canonical).lower()
        return None

    async def normalize_filters(
        self,
        tenant_id: str,
        filters: ProductSearchFilters,
        source_text: str,
    ) -> Tuple[ProductSearchFilters, Optional[str]]:
        """Normalize aliases and report category-invalid sizes before search."""
        metadata = await self.get_metadata(tenant_id)
        if not metadata:
            return filters, None

        categories = metadata.get("categories") or {}
        types = metadata.get("types") or {}
        color_map = metadata.get("color_map") or {}

        if filters.category:
            filters.category = self._canonical(filters.category, categories)
        else:
            filters.category = self._find_alias_in_text(source_text, categories)

        if filters.type:
            filters.type = self._canonical(filters.type, types)
        else:
            filters.type = self._find_alias_in_text(source_text, types)

        if filters.color:
            filters.color = self._canonical(filters.color, color_map)

        if filters.category and filters.size:
            size_group_name = (metadata.get("category_size_map") or {}).get(filters.category)
            size_group = (metadata.get("size_groups") or {}).get(size_group_name, {})
            canonical_sizes = {str(size).upper(): str(size) for size in size_group}
            requested_size = filters.size.upper()
            if size_group and requested_size not in canonical_sizes:
                choices = ", ".join(str(size) for size in size_group)
                return filters, (
                    f"For {filters.category}s, available sizes are {choices}. "
                    "Which size would you like?"
                )
            if requested_size in canonical_sizes:
                filters.size = canonical_sizes[requested_size]

        return filters, None


catalog_metadata_service = CatalogMetadataService()
