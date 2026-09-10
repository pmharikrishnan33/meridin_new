"""
Conversation context management utilities.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models.schemas import (
    ConversationContext,
    EntityType,
    ExtractedEntity,
    IntentType,
    MessageUnderstanding,
)


class ConversationContextManager:
    """
    Stateless helpers for updating and reading conversation context.

    Product-search requirement decisions belong to ProductSearchHandler and
    the metadata requirement engine. This class only performs generic state
    transformations.
    """

    @staticmethod
    def update_from_understanding(
        context: ConversationContext,
        understanding: MessageUnderstanding,
    ) -> ConversationContext:
        """
        Update generic conversation context from message understanding.
        """

        context.current_intent = (
            understanding.intent
        )

        for entity in understanding.entities:
            ConversationContextManager._apply_entity(
                context,
                entity,
            )

        if (
            understanding.intent
            == IntentType.PRODUCT_SEARCH
        ):
            new_filters = (
                ConversationContextManager.entities_to_filters(
                    understanding.entities
                )
            )

            context.last_search_filters = (
                ConversationContextManager.merge_filters(
                    context.last_search_filters,
                    new_filters,
                )
            )

        return context

    @staticmethod
    def _apply_entity(
        context: ConversationContext,
        entity: ExtractedEntity,
    ) -> None:
        """
        Apply one extracted entity to generic context.

        PRODUCT is not treated as a confirmed product selection here.
        Entity extraction cannot know whether "shirt" refers to a product,
        category-like search term, or actual catalog ID. The product search
        workflow owns that interpretation.
        """

        value = (
            entity.normalized_value
            or entity.value
        )

        if value is None:
            return

        value = str(value).strip()

        if not value:
            return

        if (
            entity.entity_type
            == EntityType.CATEGORY
        ):
            context.current_category = value

        elif (
            entity.entity_type
            == EntityType.ORDER_ID
        ):
            context.last_order_id = value

    @staticmethod
    def entities_to_filters(
        entities: List[ExtractedEntity],
    ) -> Dict[str, Any]:
        """
        Convert extracted entities into ProductSearchFilters-compatible
        dictionary fields.

        Multiple entities of the same type use the highest-confidence entity
        rather than depending on extractor ordering.
        """

        filters: Dict[str, Any] = {}

        best_entities: Dict[
            EntityType,
            ExtractedEntity,
        ] = {}

        for entity in entities or []:
            value = (
                entity.normalized_value
                or entity.value
            )

            if value is None:
                continue

            value = str(value).strip()

            if not value:
                continue

            previous = best_entities.get(
                entity.entity_type
            )

            if (
                previous is None
                or entity.confidence
                > previous.confidence
            ):
                best_entities[
                    entity.entity_type
                ] = entity

        for entity_type, entity in (
            best_entities.items()
        ):
            value = (
                entity.normalized_value
                or entity.value
            )

            if value is None:
                continue

            value = str(value).strip()

            if not value:
                continue

            if (
                entity_type
                == EntityType.CATEGORY
            ):
                filters["category"] = value

            elif (
                entity_type
                == EntityType.PRODUCT
            ):
                filters["query"] = value

            elif (
                entity_type
                == EntityType.COLOR
            ):
                filters["color"] = value

            elif (
                entity_type
                == EntityType.SIZE
            ):
                filters["size"] = value

            elif (
                entity_type
                == EntityType.FIT
            ):
                filters["fit"] = value

            elif (
                entity_type
                == EntityType.PRICE
            ):
                ConversationContextManager._apply_price_filter(
                    filters,
                    entity,
                    value,
                )

            elif (
                entity_type
                == EntityType.BRAND
            ):
                filters["brand"] = value

            elif (
                entity_type
                == EntityType.MATERIAL
            ):
                filters["material"] = value

            elif (
                entity_type
                == EntityType.GENDER
            ):
                filters["gender"] = value

            elif (
                entity_type
                == EntityType.PATTERN
            ):
                filters["pattern"] = value

            elif (
                entity_type
                == EntityType.STYLE
            ):
                filters["style"] = value

            elif (
                entity_type
                == EntityType.OCCASION
            ):
                filters["occasion"] = value

            elif (
                entity_type
                == EntityType.SEASON
            ):
                filters["season"] = value

            elif (
                entity_type
                == EntityType.SLEEVE
            ):
                filters["sleeve"] = value

            elif (
                entity_type
                == EntityType.NECK
            ):
                filters["neck"] = value

        return filters

    @staticmethod
    def _apply_price_filter(
        filters: Dict[str, Any],
        entity: ExtractedEntity,
        value: str,
    ) -> None:
        """
        Convert a price entity into a deterministic price filter.

        Exact price means min_price == max_price. It must not silently become
        only a maximum-price filter.
        """

        try:
            price = float(value)
        except (
            ValueError,
            TypeError,
        ):
            return

        if price < 0:
            return

        operator = str(
            (entity.metadata or {}).get(
                "operator",
                "exact",
            )
        ).strip().lower()

        if operator in {
            "max",
            "lte",
            "less_than",
            "less_than_or_equal",
            "under",
            "below",
        }:
            filters["max_price"] = price

        elif operator in {
            "min",
            "gte",
            "greater_than",
            "greater_than_or_equal",
            "above",
            "over",
        }:
            filters["min_price"] = price

        else:
            filters["min_price"] = price
            filters["max_price"] = price

    @staticmethod
    def merge_filters(
        existing: Dict[str, Any],
        new: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge search filters.

        New meaningful values replace old values. Empty values never erase
        an already-known filter.
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
                isinstance(
                    value,
                    str,
                )
                and not value.strip()
            ):
                continue

            if (
                isinstance(
                    value,
                    list,
                )
                and not value
            ):
                continue

            merged[key] = value

        return merged

    @staticmethod
    def should_ask_clarification(
        context: ConversationContext,
        intent: IntentType,
        entities: List[ExtractedEntity],
    ) -> tuple[
        bool,
        Optional[str],
    ]:
        """
        Determine whether generic intent handling is missing information.

        Product-search category requirements are deliberately excluded from
        this method because ProductSearchHandler owns metadata-driven
        requirements.
        """

        if context.awaiting_entity:
            return (
                True,
                (
                    "Please provide the "
                    f"{context.awaiting_entity.value}."
                ),
            )

        required_entities = {
            IntentType.PRODUCT_INQUIRY: [
                EntityType.PRODUCT,
            ],
            IntentType.AVAILABILITY: [
                EntityType.PRODUCT,
            ],
        }

        required = required_entities.get(
            intent,
            [],
        )

        found_types = {
            entity.entity_type
            for entity in (
                entities or []
            )
        }

        if context.current_product:
            found_types.add(
                EntityType.PRODUCT
            )

        for required_entity in required:
            if (
                required_entity
                not in found_types
            ):
                return (
                    True,
                    (
                        "Could you please specify "
                        f"the {required_entity.value}?"
                    ),
                )

        return False, None
