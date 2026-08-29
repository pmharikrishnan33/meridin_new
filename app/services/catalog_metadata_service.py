"""Tenant-scoped catalog metadata lookup and search-filter normalization."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.models.schemas import ProductSearchFilters


class CatalogMetadataService:
    """
    Centralized access to the tenant catalog metadata.

    The inventory_metadata document is the source of truth for:

    - colors
    - sizes
    - category aliases
    - department aliases
    - product types
    - category hierarchy
    - category IDs
    - category requirements
    """

    async def get_metadata(
        self,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """
        Return catalog metadata.

        Metadata may be shared across tenants or explicitly tenant-scoped.
        Shared metadata is preferred when present.
        """

        if not mongodb.is_connected:
            return {}

        document = await collections.inventory_metadata.find_one(
            {
                "tenant_id": {
                    "$exists": False,
                }
            }
        )

        if not document:
            document = await collections.inventory_metadata.find_one(
                {
                    "tenant_id": tenant_id,
                }
            )

        return dict(document) if document else {}

    # =========================================================
    # GENERAL CANONICALIZATION
    # =========================================================

    @staticmethod
    def _canonical(
        value: str,
        aliases: Dict[str, Any],
    ) -> str:
        """
        Resolve a value against a metadata mapping.

        Supports both:

            {
                "shirts": ["shirt", "shirts"]
            }

        and:

            {
                "black": 1,
                "white": 2
            }

        For mappings whose values are numeric IDs, the key is returned.
        """

        if not value:
            return value

        normalized = value.strip().lower()

        for canonical, values in aliases.items():
            canonical_normalized = (
                str(canonical).strip().lower()
            )

            if normalized == canonical_normalized:
                return canonical_normalized

            if isinstance(values, list):
                candidates = values
            else:
                candidates = [values]

            for candidate in candidates:
                if (
                    normalized
                    == str(candidate).strip().lower()
                ):
                    return canonical_normalized

        return normalized

    @staticmethod
    def _find_alias_in_text(
        text: str,
        aliases: Dict[str, Any],
    ) -> Optional[str]:
        """
        Find the first canonical metadata value appearing in text.

        Longer aliases are checked first so that:

            "t-shirt"

        wins over a shorter overlapping term.
        """

        if not text or not aliases:
            return None

        lowered = text.lower()

        candidates: List[Tuple[int, str, str]] = []

        for canonical, values in aliases.items():
            canonical_value = str(canonical).strip().lower()

            candidates.append(
                (
                    len(canonical_value),
                    canonical_value,
                    canonical_value,
                )
            )

            if isinstance(values, list):
                aliases_for_value = values
            else:
                aliases_for_value = [values]

            for alias in aliases_for_value:
                alias_value = (
                    str(alias)
                    .strip()
                    .lower()
                )

                if alias_value:
                    candidates.append(
                        (
                            len(alias_value),
                            alias_value,
                            canonical_value,
                        )
                    )

        candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        for _, candidate, canonical_value in candidates:
            pattern = (
                rf"(?<!\w)"
                rf"{re.escape(candidate)}"
                rf"(?!\w)"
            )

            if re.search(
                pattern,
                lowered,
            ):
                return canonical_value

        return None

    # =========================================================
    # CATEGORY RESOLUTION
    # =========================================================

    @staticmethod
    def _build_category_aliases(
        metadata: Dict[str, Any],
    ) -> Dict[str, List[str]]:
        """
        Build one normalized category alias map.

        The new metadata stores categories inside:

            category_aliases

        while older deployments may have:

            categories

        The hierarchy is also used as a fallback.
        """

        result: Dict[str, List[str]] = {}

        explicit_aliases = (
            metadata.get("category_aliases")
            or {}
        )

        if isinstance(
            explicit_aliases,
            dict,
        ):
            for canonical, aliases in explicit_aliases.items():
                canonical_value = (
                    str(canonical)
                    .strip()
                    .lower()
                )

                if isinstance(
                    aliases,
                    list,
                ):
                    result[canonical_value] = [
                        str(value)
                        .strip()
                        .lower()
                        for value in aliases
                        if value
                    ]
                else:
                    result[canonical_value] = [
                        str(aliases)
                        .strip()
                        .lower()
                    ]

        legacy_categories = (
            metadata.get("categories")
            or {}
        )

        if isinstance(
            legacy_categories,
            dict,
        ):
            for canonical, aliases in legacy_categories.items():
                canonical_value = (
                    str(canonical)
                    .strip()
                    .lower()
                )

                existing = result.setdefault(
                    canonical_value,
                    [],
                )

                if isinstance(
                    aliases,
                    list,
                ):
                    existing.extend(
                        str(value)
                        .strip()
                        .lower()
                        for value in aliases
                        if value
                    )
                elif aliases:
                    existing.append(
                        str(aliases)
                        .strip()
                        .lower()
                    )

        hierarchy = (
            metadata.get("category_hierarchy")
            or {}
        )

        clothing = hierarchy.get(
            "clothing",
            {},
        )

        departments = (
            clothing.get(
                "departments",
                {},
            )
            if isinstance(
                clothing,
                dict,
            )
            else {}
        )

        if isinstance(
            departments,
            dict,
        ):
            for department in departments.values():
                if not isinstance(
                    department,
                    dict,
                ):
                    continue

                categories = (
                    department.get(
                        "categories",
                        {},
                    )
                )

                if not isinstance(
                    categories,
                    dict,
                ):
                    continue

                for category_key in categories:
                    canonical_value = (
                        str(category_key)
                        .strip()
                        .lower()
                    )

                    existing = result.setdefault(
                        canonical_value,
                        [],
                    )

                    singular = (
                        canonical_value[:-1]
                        if canonical_value.endswith("s")
                        else canonical_value
                    )

                    if singular:
                        existing.append(
                            singular
                        )

        for canonical, aliases in list(
            result.items()
        ):
            unique_aliases = sorted(
                {
                    str(alias).strip().lower()
                    for alias in aliases
                    if alias
                }
            )

            result[canonical] = unique_aliases

        return result

    @staticmethod
    def _get_matching_category_ids(
        metadata: Dict[str, Any],
        category: Optional[str],
    ) -> List[int]:
        """
        Return every category ID matching the canonical category.

        A category can legitimately exist under multiple departments.

        Example:

            shirts:
                women -> 103
                men   -> 201
                boys  -> 401

        We must not arbitrarily select the first one because category
        requirements can exist for a different department.
        """

        if not category:
            return []

        normalized_category = (
            category.strip().lower()
        )

        category_ids = (
            metadata.get("category_ids")
            or {}
        )

        if not isinstance(
            category_ids,
            dict,
        ):
            return []

        result: List[int] = []

        for department_map in category_ids.values():
            if not isinstance(
                department_map,
                dict,
            ):
                continue

            for key, value in department_map.items():
                if (
                    str(key).strip().lower()
                    != normalized_category
                ):
                    continue

                try:
                    category_id = int(value)
                except (
                    TypeError,
                    ValueError,
                ):
                    continue

                if category_id not in result:
                    result.append(category_id)

        return result

    @staticmethod
    def _resolve_category_id(
        metadata: Dict[str, Any],
        category: Optional[str],
    ) -> Optional[int]:
        """
        Resolve a category to a numeric ID only when exactly one
        category ID exists.

        If a category belongs to multiple departments, returning an
        arbitrary department's ID is unsafe. In that situation this
        method returns None.

        Requirement lookup uses _get_matching_category_ids() instead.
        """

        matching_ids = (
            CatalogMetadataService
            ._get_matching_category_ids(
                metadata,
                category,
            )
        )

        if len(matching_ids) == 1:
            return matching_ids[0]

        return None

    # =========================================================
    # COLOR RESOLUTION
    # =========================================================

    @staticmethod
    def _build_color_aliases(
        metadata: Dict[str, Any],
    ) -> Dict[str, List[str]]:
        """
        Convert the canonical color_map into aliases.
        """

        color_map = (
            metadata.get("color_map")
            or {}
        )

        aliases: Dict[str, List[str]] = {}

        if not isinstance(
            color_map,
            dict,
        ):
            return aliases

        known_aliases = {
            "navy blue": [
                "navy",
            ],
            "olive green": [
                "olive",
            ],
            "baby blue": [
                "babyblue",
            ],
            "baby pink": [
                "babypink",
            ],
            "mustard yellow": [
                "mustard",
            ],
            "charcoal grey": [
                "charcoal",
                "charcoal gray",
            ],
            "chocolate brown": [
                "chocolate",
            ],
            "sky blue": [
                "skyblue",
            ],
            "emerald green": [
                "emerald",
            ],
            "burgundy": [
                "wine",
            ],
            "maroon": [
                "dark red",
            ],
            "teal": [
                "blue green",
            ],
            "beige": [
                "cream beige",
            ],
        }

        for canonical in color_map:
            canonical_value = (
                str(canonical)
                .strip()
                .lower()
            )

            aliases[canonical_value] = list(
                known_aliases.get(
                    canonical_value,
                    [],
                )
            )

        return aliases

    # =========================================================
    # TYPE RESOLUTION
    # =========================================================

    @staticmethod
    def _build_type_aliases(
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Return metadata type aliases.
        """

        types = (
            metadata.get("types")
            or {}
        )

        return (
            types
            if isinstance(
                types,
                dict,
            )
            else {}
        )

    # =========================================================
    # SIZE RESOLUTION
    # =========================================================

    @staticmethod
    def _resolve_size_group(
        metadata: Dict[str, Any],
        category: Optional[str],
    ) -> Optional[str]:
        """
        Resolve the size group for a category.

        Handles singular/plural mismatches.
        """

        if not category:
            return None

        category_size_map = (
            metadata.get(
                "category_size_map"
            )
            or {}
        )

        if not isinstance(
            category_size_map,
            dict,
        ):
            return None

        normalized_category = (
            category.strip().lower()
        )

        candidates = [
            normalized_category,
        ]

        if normalized_category.endswith("s"):
            candidates.append(
                normalized_category[:-1]
            )
        else:
            candidates.append(
                normalized_category + "s"
            )

        aliases = (
            CatalogMetadataService
            ._build_category_aliases(
                metadata
            )
        )

        for canonical, values in aliases.items():
            if (
                normalized_category
                == canonical
                or normalized_category
                in values
            ):
                candidates.append(
                    canonical
                )
                candidates.extend(values)

        for candidate in candidates:
            if candidate in category_size_map:
                return str(
                    category_size_map[
                        candidate
                    ]
                )

        return None

    @staticmethod
    def _normalize_size(
        metadata: Dict[str, Any],
        category: Optional[str],
        size: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Normalize a size according to the category size group.

        Returns:

            (normalized_size, clarification_message)
        """

        if not size:
            return None, None

        requested_size = size.strip()

        if not requested_size:
            return None, None

        size_group_name = (
            CatalogMetadataService
            ._resolve_size_group(
                metadata,
                category,
            )
        )

        if not size_group_name:
            return (
                requested_size.upper(),
                None,
            )

        size_groups = (
            metadata.get(
                "size_groups"
            )
            or {}
        )

        size_group = (
            size_groups.get(
                size_group_name,
                {},
            )
            if isinstance(
                size_groups,
                dict,
            )
            else {}
        )

        if not isinstance(
            size_group,
            dict,
        ):
            return (
                requested_size.upper(),
                None,
            )

        canonical_by_upper = {
            str(key).upper(): str(key)
            for key in size_group.keys()
        }

        normalized_upper = (
            requested_size.upper()
        )

        if normalized_upper not in canonical_by_upper:
            choices = ", ".join(
                str(key)
                for key in size_group.keys()
            )

            category_label = (
                category or "this category"
            )

            return (
                None,
                (
                    f"For {category_label}, "
                    f"available sizes are {choices}. "
                    "Which size would you like?"
                ),
            )

        return (
            canonical_by_upper[
                normalized_upper
            ],
            None,
        )

    # =========================================================
    # CATEGORY REQUIREMENTS
    # =========================================================

    @staticmethod
    def _category_requirements_for_id(
        metadata: Dict[str, Any],
        category_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        """
        Return requirements for a numeric category ID.

        Supports:

            "201": {
                "attributes": [...]
            }

        and the older direct-list format.
        """

        if category_id is None:
            return []

        requirements = (
            metadata.get(
                "category_requirements"
            )
            or {}
        )

        if not isinstance(
            requirements,
            dict,
        ):
            return []

        value = requirements.get(
            str(category_id)
        )

        if isinstance(
            value,
            dict,
        ):
            attributes = value.get(
                "attributes",
                [],
            )

            if isinstance(
                attributes,
                list,
            ):
                return [
                    item
                    for item in attributes
                    if isinstance(
                        item,
                        dict,
                    )
                ]

        if isinstance(
            value,
            list,
        ):
            return [
                item
                for item in value
                if isinstance(
                    item,
                    dict,
                )
            ]

        return []

    @staticmethod
    def _merge_category_requirements(
        requirement_lists: List[
            List[Dict[str, Any]]
        ],
    ) -> List[Dict[str, Any]]:
        """
        Merge requirements from multiple department-specific category IDs.

        This is important when the user says only:

            "I need a black shirt"

        because "shirts" exists under multiple departments.

        If any matching category definition requires an attribute, that
        attribute is treated as required until the department is known.
        """

        merged: Dict[str, Dict[str, Any]] = {}

        for requirements in requirement_lists:
            for requirement in requirements:
                if not isinstance(
                    requirement,
                    dict,
                ):
                    continue

                key = str(
                    requirement.get(
                        "key",
                        ""
                    )
                ).strip().lower()

                if not key:
                    continue

                existing = merged.get(key)

                if existing is None:
                    merged[key] = dict(
                        requirement
                    )
                    continue

                # Preserve the existing definition while making the
                # attribute required if any department requires it.
                if requirement.get(
                    "required",
                    False,
                ):
                    existing["required"] = True

                if not existing.get("label") and requirement.get(
                    "label"
                ):
                    existing["label"] = requirement["label"]

                if not existing.get("question") and requirement.get(
                    "question"
                ):
                    existing["question"] = requirement["question"]

                if not existing.get("value_type") and requirement.get(
                    "value_type"
                ):
                    existing["value_type"] = requirement["value_type"]

                if not existing.get("options") and requirement.get(
                    "options"
                ):
                    existing["options"] = requirement["options"]

        return list(
            merged.values()
        )

    async def get_category_requirements(
        self,
        tenant_id: str,
        category: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Get metadata-driven requirements for a category.

        IMPORTANT:

        A category may appear under multiple departments.

        Example:

            shirts:
                women -> 103
                men   -> 201
                boys  -> 401

        We therefore inspect every matching category ID instead of
        arbitrarily selecting the first department.

        This prevents:

            "black shirt"

        from accidentally selecting women's category 103 when the
        available requirement definition exists under men's category 201.
        """

        if not category:
            return []

        metadata = await self.get_metadata(
            tenant_id
        )

        if not metadata:
            return []

        aliases = (
            self._build_category_aliases(
                metadata
            )
        )

        canonical_category = self._canonical(
            category,
            aliases,
        )

        matching_category_ids = (
            self._get_matching_category_ids(
                metadata,
                canonical_category,
            )
        )

        if not matching_category_ids:
            return []

        requirement_lists: List[
            List[Dict[str, Any]]
        ] = []

        for category_id in matching_category_ids:
            requirements = (
                self._category_requirements_for_id(
                    metadata,
                    category_id,
                )
            )

            if requirements:
                requirement_lists.append(
                    requirements
                )

        if not requirement_lists:
            return []

        return self._merge_category_requirements(
            requirement_lists
        )

    async def get_required_category_attributes(
        self,
        tenant_id: str,
        category: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Return only required category attributes.
        """

        requirements = (
            await self.get_category_requirements(
                tenant_id,
                category,
            )
        )

        return [
            requirement
            for requirement in requirements
            if bool(
                requirement.get(
                    "required",
                    False,
                )
            )
        ]

    # =========================================================
    # FILTER NORMALIZATION
    # =========================================================

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
        Normalize filters against catalog metadata.

        Returns:

            (normalized_filters, clarification_message)
        """

        metadata = await self.get_metadata(
            tenant_id
        )

        if not metadata:
            return filters, None

        # -----------------------------------------------------
        # CATEGORY
        # -----------------------------------------------------

        category_aliases = (
            self._build_category_aliases(
                metadata
            )
        )

        if filters.category:
            filters.category = self._canonical(
                filters.category,
                category_aliases,
            )
        else:
            filters.category = (
                self._find_alias_in_text(
                    source_text,
                    category_aliases,
                )
            )

        # -----------------------------------------------------
        # COLOR
        # -----------------------------------------------------

        color_aliases = (
            self._build_color_aliases(
                metadata
            )
        )

        if filters.color:
            filters.color = self._canonical(
                filters.color,
                color_aliases,
            )
        else:
            filters.color = (
                self._find_alias_in_text(
                    source_text,
                    color_aliases,
                )
            )

        # -----------------------------------------------------
        # TYPE
        # -----------------------------------------------------

        type_aliases = (
            self._build_type_aliases(
                metadata
            )
        )

        if filters.type:
            filters.type = self._canonical(
                filters.type,
                type_aliases,
            )
        else:
            filters.type = (
                self._find_alias_in_text(
                    source_text,
                    type_aliases,
                )
            )

        # -----------------------------------------------------
        # SIZE
        # -----------------------------------------------------

        normalized_size, clarification = (
            self._normalize_size(
                metadata,
                filters.category,
                filters.size,
            )
        )

        if clarification:
            return (
                filters,
                clarification,
            )

        if normalized_size:
            filters.size = normalized_size

        return filters, None


catalog_metadata_service = CatalogMetadataService()