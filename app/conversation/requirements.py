"""
Metadata-driven conversation requirement engine.

This module does not hardcode clothing-category requirements.

The inventory_metadata document is the source of truth for:
- required attributes
- question text
- option lists
- category-specific conversational requirements
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.models.schemas import (
    ConversationContext,
    EntityType,
    ExtractedEntity,
)


class ConversationRequirementEngine:
    """
    Determines which attributes are still required before product search.

    Category-specific requirements come from inventory_metadata.

    The engine itself does NOT know that:
        dresses need dress_style
        shirts need size
        tops need color

    Those rules belong to metadata.
    """

    FILTER_ENTITY_MAP = {
        EntityType.CATEGORY: "category",
        EntityType.PRODUCT: "query",
        EntityType.COLOR: "color",
        EntityType.SIZE: "size",
        EntityType.FIT: "fit",
        EntityType.PRICE: "price",
        EntityType.BRAND: "brand",
        EntityType.MATERIAL: "material",
        EntityType.GENDER: "gender",
        EntityType.PATTERN: "pattern",
        EntityType.STYLE: "style",
        EntityType.OCCASION: "occasion",
        EntityType.SEASON: "season",
        EntityType.SLEEVE: "sleeve",
        EntityType.NECK: "neck",
    }

    DEFAULT_QUESTION_TEXT = {
        "color": "What color would you like?",
        "size": "What size would you like?",
        "gender": "Who are you shopping for?",
        "brand": "Do you have a preferred brand?",
        "material": "Do you have a preferred material?",
        "fit": "What fit would you prefer?",
        "price": "What price range would you prefer?",
        "category": "What type of clothing are you looking for?",
        "query": "What type of clothing are you looking for?",
    }

    def entity_to_filters(
        self,
        entities: List[ExtractedEntity],
    ) -> Dict[str, Any]:
        """
        Convert extracted entities into generic filters.

        Metadata resolution happens later.
        """

        filters: Dict[str, Any] = {}

        for entity in entities:
            field = self.FILTER_ENTITY_MAP.get(
                entity.entity_type
            )

            if field is None:
                continue

            value = (
                entity.normalized_value
                or entity.value
            )

            if value is None:
                continue

            if isinstance(value, str):
                value = value.strip()

            if not value:
                continue

            if entity.entity_type == EntityType.PRICE:
                try:
                    price = float(value)
                except (
                    TypeError,
                    ValueError,
                ):
                    continue

                operator = (
                    entity.metadata or {}
                ).get(
                    "operator",
                    "exact",
                )

                if operator == "max":
                    filters["max_price"] = price

                elif operator == "min":
                    filters["min_price"] = price

                else:
                    filters["min_price"] = price
                    filters["max_price"] = price

                continue

            filters[field] = value

        return filters

    @staticmethod
    def merge_filters(
        existing: Dict[str, Any],
        new: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge new filters into existing conversation state.
        """

        merged = dict(
            existing or {}
        )

        for key, value in (
            new or {}
        ).items():

            if value is None:
                continue

            if (
                isinstance(value, str)
                and not value.strip()
            ):
                continue

            merged[key] = value

        return merged

    @staticmethod
    def has_value(
        filters: Dict[str, Any],
        key: str,
    ) -> bool:
        """
        Determine whether a filter contains a usable value.
        """

        value = filters.get(key)

        if value is None:
            return False

        if isinstance(value, str):
            return bool(
                value.strip()
            )

        if isinstance(
            value,
            (list, tuple, set),
        ):
            return bool(value)

        return True

    def missing_metadata_requirements(
        self,
        filters: Dict[str, Any],
        requirements: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Return required metadata attributes that are missing.
        """

        missing: List[
            Dict[str, Any]
        ] = []

        for requirement in requirements:
            if not requirement.get(
                "required",
                False,
            ):
                continue

            key = str(
                requirement.get(
                    "key",
                    "",
                )
            ).strip()

            if not key:
                continue

            if not self.has_value(
                filters,
                key,
            ):
                missing.append(
                    requirement
                )

        return missing

    def next_metadata_requirement(
        self,
        filters: Dict[str, Any],
        requirements: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Return the first missing required metadata attribute.
        """

        missing = (
            self.missing_metadata_requirements(
                filters,
                requirements,
            )
        )

        return (
            missing[0]
            if missing
            else None
        )

    def question_for_requirement(
        self,
        requirement: Dict[str, Any],
    ) -> str:
        """
        Build a customer-facing question from metadata.

        Question text is preferably stored in metadata.
        """

        question = requirement.get(
            "question"
        )

        if (
            isinstance(question, str)
            and question.strip()
        ):
            return question.strip()

        label = str(
            requirement.get(
                "label",
                requirement.get(
                    "key",
                    "attribute",
                ),
            )
        ).strip()

        return (
            self.DEFAULT_QUESTION_TEXT.get(
                label.lower(),
                f"What {label} would you like?",
            )
        )

    def add_requirement_value(
        self,
        filters: Dict[str, Any],
        requirement: Dict[str, Any],
        value: Any,
    ) -> Dict[str, Any]:
        """
        Store a value against a metadata requirement.

        This method intentionally does not hardcode attribute names.
        """

        updated = dict(
            filters or {}
        )

        key = str(
            requirement.get(
                "key",
                "",
            )
        ).strip()

        if not key:
            return updated

        if isinstance(
            value,
            str,
        ):
            value = value.strip()

        if value is not None:
            updated[key] = value

        return updated

    def evaluate(
        self,
        *,
        current_filters: Dict[str, Any],
        requirements: Optional[
            List[Dict[str, Any]]
        ] = None,
        context: Optional[
            ConversationContext
        ] = None,
    ) -> Tuple[
        bool,
        Optional[Dict[str, Any]],
        Optional[str],
    ]:
        """
        Determine whether search can proceed.

        Returns:

            ready_to_search
            missing_requirement
            question
        """

        metadata_requirements = (
            requirements or []
        )

        missing = (
            self.missing_metadata_requirements(
                current_filters,
                metadata_requirements,
            )
        )

        if not missing:
            return (
                True,
                None,
                None,
            )

        requirement = missing[0]

        return (
            False,
            requirement,
            self.question_for_requirement(
                requirement
            ),
        )

    def build_filters_from_context(
        self,
        context: ConversationContext,
    ) -> Dict[str, Any]:
        """
        Restore the previous conversational search state.
        """

        filters = dict(
            context.last_search_filters
            or {}
        )

        if context.current_product:
            filters.setdefault(
                "query",
                context.current_product,
            )

        if context.current_category:
            filters.setdefault(
                "category",
                context.current_category,
            )

        return filters

    def reset_search_context(
        self,
        context: ConversationContext,
    ) -> None:
        """
        Clear active search state.
        """

        context.current_product = None
        context.current_category = None

        context.last_search_filters = {}
        context.last_search_results = []

        context.active_search_key = None
        context.active_search_offset = 0
        context.active_search_total = 0
        context.active_search_query = None
        context.active_search_filters = {}
        context.active_search_results = []
        context.active_search_page = 1
        context.active_search_page_size = 10

        context.awaiting_entity = None
        context.awaiting_confirmation = False
        context.confirmation_context = {}


conversation_requirement_engine = (
    ConversationRequirementEngine()
)