"""
Tenant-scoped catalog metadata service.

inventory_metadata is the source of truth for:
- departments
- categories
- aliases
- colors
- sizes
- types
- category requirements
- category-specific attributes

No clothing category or question is hardcoded here.
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
        if not tenant_id:
            return {}

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
            str(value).strip().lower()
        )

        if not normalized:
            return normalized

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

            candidate_values = {
                str(candidate).strip().lower()
                for candidate in candidates
                if str(candidate).strip()
            }

            if (
                normalized
                == str(canonical).strip().lower()
                or normalized in candidate_values
            ):
                return str(
                    canonical
                ).strip().lower()

        return normalized

    @staticmethod
    def _find_alias_in_text(
        text: str,
        aliases: Dict[str, Any],
    ) -> Optional[str]:
        if not text:
            return None

        lowered = str(text).lower()

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

            all_candidates = [
                str(canonical)
            ]

            all_candidates.extend(
                str(value)
                for value in candidates
            )

            ordered.append(
                (
                    str(canonical),
                    all_candidates,
                )
            )

        ordered.sort(
            key=lambda item: max(
                (
                    len(candidate)
                    for candidate in item[1]
                ),
                default=0,
            ),
            reverse=True,
        )

        for canonical, candidates in ordered:
            for candidate in candidates:
                candidate = candidate.strip()

                if not candidate:
                    continue

                pattern = (
                    rf"(?<!\w)"
                    rf"{re.escape(candidate.lower())}"
                    rf"(?!\w)"
                )

                if re.search(
                    pattern,
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

        found_ids: List[int] = []

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

            if value is None:
                continue

            try:
                category_id = int(value)
            except (
                TypeError,
                ValueError,
            ):
                continue

            if category_id not in found_ids:
                found_ids.append(
                    category_id
                )

        # If the same category exists in multiple departments,
        # do not guess. The department must disambiguate it.
        if len(found_ids) != 1:
            return None

        return found_ids[0]

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
            str(value).strip().lower()
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
                str(raw_size).strip().upper()
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

    @staticmethod
    def _type_aliases(
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Support both:

            type_aliases

        and the existing:

            types

        metadata structures.
        """

        return (
            metadata.get(
                "type_aliases"
            )
            or metadata.get(
                "types"
            )
            or {}
        )

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
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return metadata-defined requirements for a category.

        Primary lookup:

            category_requirements["201"]

        Optional fallback:

            category_requirements_by_name["shirts"]
        """

        metadata = await self.get_metadata(
            tenant_id
        )

        requirements = (
            metadata.get(
                "category_requirements"
            )
            or {}
        )

        value = None

        if category_id is not None:
            value = requirements.get(
                str(category_id)
            )

            if value is None:
                value = requirements.get(
                    category_id
                )

        if value is None and category:
            by_name = (
                metadata.get(
                    "category_requirements_by_name"
                )
                or {}
            )

            value = by_name.get(
                category.lower()
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
        """

        metadata = await self.get_metadata(
            tenant_id
        )

        key = (
            str(key)
            .strip()
            .lower()
        )

        if not key:
            return None

        if key == "color":
            canonical = self._canonical(
                str(value),
                metadata.get(
                    "color_aliases",
                    {},
                ),
            )

            color_id = self._color_id(
                metadata,
                canonical,
            )

            if color_id is None:
                return None

            return {
                "key": key,
                "value": canonical,
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

                for (
                    department,
                    categories,
                ) in category_ids.items():

                    if not isinstance(
                        categories,
                        dict,
                    ):
                        continue

                    for (
                        name,
                        raw_id,
                    ) in categories.items():

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
                "value": str(
                    value
                ).upper(),
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

        normalized = (
            str(value)
            .strip()
            .lower()
        )

        for canonical, raw_id in (
            values.items()
        ):
            if normalized == str(
                canonical
            ).strip().lower():

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
                    ).strip().lower(),
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

        This function does NOT decide which attributes are required.
        That decision belongs to ConversationRequirementEngine and
        inventory_metadata.category_requirements.
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

        types = self._type_aliases(
            metadata
        )

        # ---------------------------------------------------------
        # DEPARTMENT / GENDER
        # ---------------------------------------------------------

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

        # ---------------------------------------------------------
        # CATEGORY
        # ---------------------------------------------------------

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

        # ---------------------------------------------------------
        # TYPE / STYLE
        # ---------------------------------------------------------

        if filters.type:
            filters.type = self._canonical(
                filters.type,
                types,
            )

        elif source_text:
            detected_type = (
                self._find_alias_in_text(
                    source_text,
                    types,
                )
            )

            if detected_type:
                filters.type = (
                    detected_type
                )

        # ---------------------------------------------------------
        # COLOR
        # ---------------------------------------------------------

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

        elif source_text:
            detected_color = (
                self._find_alias_in_text(
                    source_text,
                    colors,
                )
            )

            if detected_color:
                filters.color = (
                    detected_color
                )

                filters.color_id = (
                    self._color_id(
                        metadata,
                        detected_color,
                    )
                )

        # ---------------------------------------------------------
        # SIZE
        # ---------------------------------------------------------

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