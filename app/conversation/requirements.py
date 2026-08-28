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

    Example metadata:

        "category_requirements": {
            "101": [
                {
                    "key": "type",
                    "required": true,
                    "entity_type": "style",
                    "question": "What type of dress are you looking for?",
                    "options": ["mini", "midi", "maxi"]
                }
            ],
            "201": [
                {
                    "key": "size",
                    "required": true,
                    "entity_type": "size",
                    "question": "What size shirt would you like?"
                }
            ]
        }

    The engine itself does not know what a particular category requires.
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
        # STYLE is mapped to "type" because the existing Product model
        # stores product-specific type values in the "type" field.
        EntityType.STYLE: "type",
        EntityType.OCCASION: "occasion",
        EntityType.SEASON: "season",
        EntityType.SLEEVE: "sleeve",
        EntityType.NECK: "neck",
    }

    REQUIREMENT_ENTITY_MAP = {
        "category": EntityType.CATEGORY,
        "query": EntityType.PRODUCT,
        "color": EntityType.COLOR,
        "size": EntityType.SIZE,
        "fit": EntityType.FIT,
        "price": EntityType.PRICE,
        "brand": EntityType.BRAND,
        "material": EntityType.MATERIAL,
        "gender": EntityType.GENDER,
        "type": EntityType.STYLE,
        "style": EntityType.STYLE,
        "pattern": EntityType.PATTERN,
        "occasion": EntityType.OCCASION,
        "season": EntityType.SEASON,
        "sleeve": EntityType.SLEEVE,
        "neck": EntityType.NECK,
        "age_group": None,
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
        "type": "What type would you prefer?",
        "style": "What style would you prefer?",
        "pattern": "What pattern would you prefer?",
        "occasion": "What occasion are you shopping for?",
        "season": "Which season are you shopping for?",
        "sleeve": "What sleeve style would you prefer?",
        "neck": "What neck style would you prefer?",
        "age_group": "Which age group are you shopping for?",
    }

    def entity_to_filters(
        self,
        entities: List[ExtractedEntity],
    ) -> Dict[str, Any]:
        """
        Convert extracted entities into generic search filters.

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

        New non-empty values take precedence.
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

    @classmethod
    def entity_type_for_requirement(
        cls,
        requirement: Dict[str, Any],
    ) -> Optional[EntityType]:
        """
        Resolve the EntityType used to collect a requirement.

        Metadata may explicitly specify entity_type.

        Example:

            {
                "key": "type",
                "entity_type": "style"
            }

        If metadata does not specify it, the requirement key is used.
        """

        raw_entity_type = requirement.get(
            "entity_type"
        )

        if raw_entity_type:
            try:
                return EntityType(
                    str(raw_entity_type).strip().lower()
                )
            except ValueError:
                pass

        key = str(
            requirement.get(
                "key",
                "",
            )
        ).strip().lower()

        return cls.REQUIREMENT_ENTITY_MAP.get(
            key
        )

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

        If metadata provides options, they are appended automatically.
        """

        question = requirement.get(
            "question"
        )

        if (
            isinstance(question, str)
            and question.strip()
        ):
            question_text = question.strip()
        else:
            label = str(
                requirement.get(
                    "label",
                    requirement.get(
                        "key",
                        "attribute",
                    ),
                )
            ).strip()

            question_text = (
                self.DEFAULT_QUESTION_TEXT.get(
                    label.lower(),
                    f"What {label} would you like?",
                )
            )

        options = requirement.get(
            "options"
        )

        if (
            isinstance(options, list)
            and options
        ):
            cleaned_options = [
                str(option).strip()
                for option in options
                if str(option).strip()
            ]

            if cleaned_options:
                option_text = ", ".join(
                    cleaned_options
                )

                if option_text.lower() not in question_text.lower():
                    question_text = (
                        f"{question_text} "
                        f"Options: {option_text}."
                    )

        return question_text

    def question_for(
        self,
        entity_type: EntityType,
    ) -> str:
        """
        Compatibility helper used by intent_router.py.

        This fixes the previous mismatch where intent_router called
        question_for() but the requirement engine only implemented
        question_for_requirement().
        """

        if not isinstance(
            entity_type,
            EntityType,
        ):
            try:
                entity_type = EntityType(
                    str(entity_type).strip().lower()
                )
            except ValueError:
                return (
                    "Could you please provide "
                    "the requested information?"
                )

        field = self.FILTER_ENTITY_MAP.get(
            entity_type,
            entity_type.value,
        )

        return self.DEFAULT_QUESTION_TEXT.get(
            field,
            f"Could you please provide "
            f"the {field}?",
        )

    def add_requirement_value(
        self,
        filters: Dict[str, Any],
        requirement: Dict[str, Any],
        value: Any,
    ) -> Dict[str, Any]:
        """
        Store a value against a metadata requirement.

        This method intentionally does not hardcode clothing
        categories or product types.
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