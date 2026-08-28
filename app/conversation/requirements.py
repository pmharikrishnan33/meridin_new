"""
Conversation requirement engine.

Determines whether a product-search conversation has enough
information to perform an inventory search.

The requirement engine is intentionally separate from the
product-search handler so conversational logic does not become
coupled to inventory logic.
"""

from typing import Any, Dict, List, Optional, Tuple

from app.models.schemas import (
    ConversationContext,
    EntityType,
    ExtractedEntity,
    ProductSearchFilters,
)


class ConversationRequirementEngine:
    """
    Determines which product-search information is still required.
    """

    DEFAULT_REQUIRED_FIELDS = (
        EntityType.CATEGORY,
        EntityType.SIZE,
    )

    QUESTION_TEXT = {
        EntityType.CATEGORY: (
            "What type of clothing are you looking for? "
            "For example: shirt, jeans, hoodie, or dress."
        ),
        EntityType.COLOR: (
            "What color would you like?"
        ),
        EntityType.SIZE: (
            "What size would you like? "
            "For example: S, M, L, or XL."
        ),
        EntityType.BRAND: (
            "Do you have a preferred brand?"
        ),
        EntityType.MATERIAL: (
            "Do you have a preferred material?"
        ),
        EntityType.FIT: (
            "What fit would you prefer?"
        ),
        EntityType.PRICE: (
            "What price range would you prefer?"
        ),
    }

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

    def __init__(
        self,
        required_fields: Optional[List[EntityType]] = None,
    ) -> None:
        self.required_fields = tuple(
            required_fields or self.DEFAULT_REQUIRED_FIELDS
        )

    def entity_to_filters(
        self,
        entities: List[ExtractedEntity],
    ) -> Dict[str, Any]:
        """
        Convert extracted entities into product-search filters.
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

            if not value:
                continue

            if entity.entity_type == EntityType.PRICE:
                try:
                    price = float(value)

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
                        filters["max_price"] = price

                except (TypeError, ValueError):
                    continue

                continue

            filters[field] = value

        return filters

    @staticmethod
    def merge_filters(
        existing: Dict[str, Any],
        new: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge new filters into existing filters.

        New values always take precedence.
        """

        merged = dict(existing or {})

        for key, value in (new or {}).items():
            if value is None:
                continue

            if isinstance(value, str) and not value.strip():
                continue

            merged[key] = value

        return merged

    @staticmethod
    def _has_value(
        filters: Dict[str, Any],
        key: str,
    ) -> bool:
        value = filters.get(key)

        if value is None:
            return False

        if isinstance(value, str):
            return bool(value.strip())

        if isinstance(value, (list, tuple, set)):
            return bool(value)

        return True

    def missing_requirements(
        self,
        filters: Dict[str, Any],
        *,
        required_fields: Optional[List[EntityType]] = None,
    ) -> List[EntityType]:
        """
        Return required fields that are still missing.

        The order is intentional: category first, then size.
        """

        fields = tuple(
            required_fields
            or self.required_fields
        )

        missing: List[EntityType] = []

        for entity_type in fields:
            filter_key = self.FILTER_ENTITY_MAP.get(
                entity_type
            )

            if filter_key is None:
                continue

            if not self._has_value(
                filters,
                filter_key,
            ):
                missing.append(entity_type)

        return missing

    def next_requirement(
        self,
        filters: Dict[str, Any],
        *,
        required_fields: Optional[List[EntityType]] = None,
    ) -> Optional[EntityType]:
        """
        Return the next missing required entity.
        """

        missing = self.missing_requirements(
            filters,
            required_fields=required_fields,
        )

        return missing[0] if missing else None

    def question_for(
        self,
        entity_type: EntityType,
    ) -> str:
        """
        Return the customer-facing question for an entity.
        """

        return self.QUESTION_TEXT.get(
            entity_type,
            f"Could you please provide the {entity_type.value}?",
        )

    def evaluate(
        self,
        *,
        current_filters: Dict[str, Any],
        context: Optional[ConversationContext] = None,
        required_fields: Optional[List[EntityType]] = None,
    ) -> Tuple[bool, Optional[EntityType], Optional[str]]:
        """
        Determine whether search can proceed.

        Returns:

        (
            ready_to_search,
            missing_entity,
            question,
        )
        """

        missing = self.missing_requirements(
            current_filters,
            required_fields=required_fields,
        )

        if not missing:
            return True, None, None

        next_entity = missing[0]

        return (
            False,
            next_entity,
            self.question_for(next_entity),
        )

    def build_filters_from_context(
        self,
        context: ConversationContext,
    ) -> Dict[str, Any]:
        """
        Convert stored conversational search state into filters.
        """

        filters = dict(
            context.last_search_filters or {}
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
        Clear active product-search requirements.
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