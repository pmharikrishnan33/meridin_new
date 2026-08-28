"""
Tenant-scoped catalog metadata service.

inventory_metadata is the source of truth for:
- departments
- categories
- aliases
- colors
- sizes
- category requirements
- category-specific attributes
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.models.schemas import ProductSearchFilters


class CatalogMetadataService:
    """
    Resolve natural-language catalog values into canonical metadata values.
    """

    async def get_metadata(
        self,
        tenant_id: str,
    ) -> Dict[str, Any]:
        if not mongodb.is_connected:
            return {}

        document = await (
            collections.inventory_metadata.find_one(
                {
                    "tenant_id": tenant_id,
                }
            )
        )

        if not document:
            document = await (
                collections.inventory_metadata.find_one(
                    {
                        "tenant_id": {
                            "$exists": False
                        }
                    }
                )
            )

        return (
            dict(document)
            if document
            else {}
        )

    @staticmethod
    def _canonical(
        value: str,
        aliases: Dict[str, Any],
    ) -> str:
        normalized = (
            value.strip().lower()
        )

        for canonical, values in (
            aliases or {}
        ).items():

            candidates = (
                values
                if isinstance(
                    values,
                    list,
                )
                else [values]
            )

            if (
                normalized
                == str(canonical).lower()
                or normalized
                in {
                    str(candidate).lower()
                    for candidate in candidates
                }
            ):
                return str(
                    canonical
                ).lower()

        return normalized

    @staticmethod
    def _find_alias_in_text(
        text: str,
        aliases: Dict[str, Any],
    ) -> Optional[str]:
        lowered = text.lower()

        ordered = []

        for canonical, values in (
            aliases or {}
        ).items():

            candidates = (
                values
                if isinstance(
                    values,
                    list,
                )
                else [values]
            )

            ordered.append(
                (
                    str(canonical),
                    candidates,
                )
            )

        # Longest aliases first prevents
        # "shirt" from winning over "t-shirt".
        ordered.sort(
            key=lambda item: max(
                [
                    len(str(item[0])),
                    *[
                        len(str(value))
                        for value in item[1]
                    ],
                ]
            ),
            reverse=True,
        )

        for canonical, values in ordered:

            candidates = [
                canonical,
                *[
                    str(value)
                    for value in values
                ],
            ]

            for candidate in candidates:
                if re.search(
                    rf"\b{re.escape(candidate.lower())}\b",
                    lowered,
                ):
                    return canonical.lower()

        return None

    @staticmethod
    def _department_id(
        metadata: Dict[str, Any],
        department: Optional[str],
    ) -> Optional[int]:
        if not department:
            return None

        mapping = (
            metadata.get(
                "department_ids"
            )
            or {}
        )

        value = mapping.get(
            department.lower()
        )

        if value is None:
            return None

        try:
            return int(value)
        except (
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def _category_id(
        metadata: Dict[str, Any],
        department: Optional[str],
        category: Optional[str],
    ) -> Optional[int]:
        if not category:
            return None

        mapping = (
            metadata.get(
                "category_ids"
            )
            or {}
        )

        canonical_category = (
            category.lower()
        )

        if department:
            department_mapping = (
                mapping.get(
                    department.lower()
                )
                or {}
            )

            value = department_mapping.get(
                canonical_category
            )

            if value is not None:
                try:
                    return int(value)
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

        for department_mapping in (
            mapping.values()
        ):
            if not isinstance(
                department_mapping,
                dict,
            ):
                continue

            value = department_mapping.get(
                canonical_category
            )

            if value is not None:
                try:
                    return int(value)
                except (
                    TypeError,
                    ValueError,
                ):
                    continue

        return None

    @staticmethod
    def _color_id(
        metadata: Dict[str, Any],
        color: Optional[str],
    ) -> Optional[int]:
        if not color:
            return None

        mapping = (
            metadata.get(
                "color_map"
            )
            or {}
        )

        value = mapping.get(
            color.lower()
        )

        if value is None:
            return None

        try:
            return int(value)
        except (
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def _size_group(
        metadata: Dict[str, Any],
        category: Optional[str],
    ) -> Optional[str]:
        if not category:
            return None

        mapping = (
            metadata.get(
                "category_size_map"
            )
            or {}
        )

        canonical = (
            category.lower()
        )

        value = mapping.get(
            canonical
        )

        return (
            str(value)
            if value
            else None
        )

    @staticmethod
    def _size_id(
        metadata: Dict[str, Any],
        size_group: Optional[str],
        size: Optional[str],
    ) -> Optional[int]:
        if not size_group or not size:
            return None

        groups = (
            metadata.get(
                "size_groups"
            )
            or {}
        )

        group = (
            groups.get(
                size_group
            )
            or {}
        )

        requested = (
            size.strip().upper()
        )

        for raw_size, raw_id in (
            group.items()
        ):
            if (
                str(raw_size).upper()
                == requested
            ):
                try:
                    return int(raw_id)
                except (
                    TypeError,
                    ValueError,
                ):
                    return None

        return None

    async def resolve_department(
        self,
        tenant_id: str,
        value: str,
    ) -> Optional[Dict[str, Any]]:
        metadata = await self.get_metadata(
            tenant_id
        )

        canonical = self._canonical(
            value,
            metadata.get(
                "department_aliases",
                {},
            ),
        )

        department_id = (
            self._department_id(
                metadata,
                canonical,
            )
        )

        if department_id is None:
            return None

        return {
            "canonical": canonical,
            "department_id": department_id,
        }

    async def resolve_category(
        self,
        tenant_id: str,
        value: str,
        department: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        metadata = await self.get_metadata(
            tenant_id
        )

        canonical = self._canonical(
            value,
            metadata.get(
                "category_aliases",
                {},
            ),
        )

        category_id = (
            self._category_id(
                metadata,
                department,
                canonical,
            )
        )

        if category_id is None:
            return None

        return {
            "canonical": canonical,
            "category_id": category_id,
            "department": department,
            "department_id": (
                self._department_id(
                    metadata,
                    department,
                )
            ),
        }

    async def get_category_requirements(
        self,
        tenant_id: str,
        category_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        if category_id is None:
            return []

        metadata = await self.get_metadata(
            tenant_id
        )

        requirements = (
            metadata.get(
                "category_requirements"
            )
            or {}
        )

        value = requirements.get(
            str(category_id)
        )

        if value is None:
            value = requirements.get(
                category_id
            )

        if isinstance(
            value,
            dict,
        ):
            value = value.get(
                "attributes",
                [],
            )

        if not isinstance(
            value,
            list,
        ):
            return []

        return [
            dict(item)
            for item in value
            if isinstance(
                item,
                dict,
            )
        ]

    async def resolve_attribute(
        self,
        tenant_id: str,
        key: str,
        value: Any,
        *,
        category_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve a generic metadata-defined attribute.

        Built-in catalog attributes receive IDs.
        Custom attributes can receive metadata-defined IDs.
        """

        metadata = await self.get_metadata(
            tenant_id
        )

        key = key.strip().lower()

        if not key:
            return None

        if key == "color":
            color_id = self._color_id(
                metadata,
                str(value),
            )

            if color_id is None:
                return None

            return {
                "key": key,
                "value": str(value).lower(),
                "id": color_id,
            }

        if key == "size":
            category_name = None

            if category_id is not None:
                category_ids = (
                    metadata.get(
                        "category_ids"
                    )
                    or {}
                )

                for department, categories in (
                    category_ids.items()
                ):
                    if not isinstance(
                        categories,
                        dict,
                    ):
                        continue

                    for name, raw_id in (
                        categories.items()
                    ):
                        try:
                            if int(raw_id) == int(
                                category_id
                            ):
                                category_name = (
                                    name
                                )
                                break
                        except (
                            TypeError,
                            ValueError,
                        ):
                            continue

                    if category_name:
                        break

            size_group = (
                self._size_group(
                    metadata,
                    category_name,
                )
            )

            size_id = (
                self._size_id(
                    metadata,
                    size_group,
                    str(value),
                )
            )

            if size_id is None:
                return None

            return {
                "key": key,
                "value": str(value).upper(),
                "id": size_id,
                "size_group": size_group,
            }

        definitions = (
            metadata.get(
                "attribute_definitions"
            )
            or {}
        )

        definition = definitions.get(
            key
        )

        if not isinstance(
            definition,
            dict,
        ):
            return {
                "key": key,
                "value": value,
                "id": None,
            }

        values = (
            definition.get(
                "values"
            )
            or {}
        )

        normalized = str(
            value
        ).strip().lower()

        for canonical, raw_id in (
            values.items()
        ):
            if normalized == str(
                canonical
            ).lower():
                try:
                    resolved_id = int(
                        raw_id
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    resolved_id = None

                return {
                    "key": key,
                    "value": str(
                        canonical
                    ).lower(),
                    "id": resolved_id,
                }

        return None

    async def normalize_filters(
        self,
        tenant_id: str,
        filters: ProductSearchFilters,
        source_text: str,
    ) -> Tuple[
        ProductSearchFilters,
        Optional[str],
    ]:
        """
        Normalize aliases and resolve catalog IDs.
        """

        metadata = await self.get_metadata(
            tenant_id
        )

        if not metadata:
            return filters, None

        categories = (
            metadata.get(
                "category_aliases"
            )
            or metadata.get(
                "categories"
            )
            or {}
        )

        departments = (
            metadata.get(
                "department_aliases"
            )
            or {}
        )

        colors = (
            metadata.get(
                "color_aliases"
            )
            or {}
        )

        if filters.gender:
            filters.gender = self._canonical(
                filters.gender,
                departments,
            )

            filters.department_id = (
                self._department_id(
                    metadata,
                    filters.gender,
                )
            )

        if not filters.gender:
            detected_department = (
                self._find_alias_in_text(
                    source_text,
                    departments,
                )
            )

            if detected_department:
                filters.gender = (
                    detected_department
                )

                filters.department_id = (
                    self._department_id(
                        metadata,
                        detected_department,
                    )
                )

        if filters.category:
            filters.category = self._canonical(
                filters.category,
                categories,
            )

        elif filters.query:
            detected_category = (
                self._find_alias_in_text(
                    str(filters.query),
                    categories,
                )
            )

            if detected_category:
                filters.category = (
                    detected_category
                )

        if not filters.category:
            detected_category = (
                self._find_alias_in_text(
                    source_text,
                    categories,
                )
            )

            if detected_category:
                filters.category = (
                    detected_category
                )

        if filters.category:
            filters.category_id = (
                self._category_id(
                    metadata,
                    filters.gender,
                    filters.category,
                )
            )

            filters.size_group = (
                self._size_group(
                    metadata,
                    filters.category,
                )
            )

        if filters.color:
            filters.color = self._canonical(
                filters.color,
                colors,
            )

            filters.color_id = (
                self._color_id(
                    metadata,
                    filters.color,
                )
            )

        if filters.size:
            filters.size = (
                filters.size.upper()
            )

            filters.size_id = (
                self._size_id(
                    metadata,
                    filters.size_group,
                    filters.size,
                )
            )

        return filters, None


catalog_metadata_service = (
    CatalogMetadataService()
)