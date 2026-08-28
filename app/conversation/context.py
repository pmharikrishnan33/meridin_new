"""
Conversation context management utilities.
"""

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
    Manages conversation context updates based on message understanding.
    """

    @staticmethod
    def update_from_understanding(
        context: ConversationContext,
        understanding: MessageUnderstanding,
    ) -> ConversationContext:
        """
        Update context from message understanding.
        """

        context.current_intent = understanding.intent

        for entity in understanding.entities:
            ConversationContextManager._apply_entity(
                context,
                entity,
            )

        return context

    @staticmethod
    def _apply_entity(
        context: ConversationContext,
        entity: ExtractedEntity,
    ) -> None:
        """
        Apply a single entity to context.
        """

        value = (
            entity.normalized_value
            or entity.value
        )

        if not value:
            return

        if entity.entity_type == EntityType.CATEGORY:
            context.current_category = value

        elif entity.entity_type == EntityType.PRODUCT:
            # Product-category keywords such as "shirt" may currently
            # arrive as PRODUCT from the extractor. Preserve them as
            # current_product while also allowing search filters to use
            # them as query terms.
            context.current_product = value

        elif entity.entity_type == EntityType.ORDER_ID:
            context.last_order_id = value

    @staticmethod
    def entities_to_filters(
        entities: List[ExtractedEntity],
    ) -> Dict[str, Any]:
        """
        Convert extracted entities to search filters.
        """

        filters: Dict[str, Any] = {}

        for entity in entities:
            value = (
                entity.normalized_value
                or entity.value
            )

            if not value:
                continue

            if entity.entity_type == EntityType.CATEGORY:
                filters["category"] = value

            elif entity.entity_type == EntityType.PRODUCT:
                filters["query"] = value

            elif entity.entity_type == EntityType.COLOR:
                filters["color"] = value

            elif entity.entity_type == EntityType.SIZE:
                filters["size"] = value

            elif entity.entity_type == EntityType.FIT:
                filters["fit"] = value

            elif entity.entity_type == EntityType.PRICE:
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

                except (ValueError, TypeError):
                    pass

            elif entity.entity_type == EntityType.BRAND:
                filters["brand"] = value

            elif entity.entity_type == EntityType.MATERIAL:
                filters["material"] = value

            elif entity.entity_type == EntityType.GENDER:
                filters["gender"] = value

            elif entity.entity_type == EntityType.PATTERN:
                filters["pattern"] = value

            elif entity.entity_type == EntityType.STYLE:
                filters["style"] = value

            elif entity.entity_type == EntityType.OCCASION:
                filters["occasion"] = value

            elif entity.entity_type == EntityType.SEASON:
                filters["season"] = value

            elif entity.entity_type == EntityType.SLEEVE:
                filters["sleeve"] = value

            elif entity.entity_type == EntityType.NECK:
                filters["neck"] = value

        return filters

    @staticmethod
    def merge_filters(
        existing: Dict[str, Any],
        new: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge new filters with existing filters.

        New non-empty values take precedence.
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
    def should_ask_clarification(
        context: ConversationContext,
        intent: IntentType,
        entities: List[ExtractedEntity],
    ) -> tuple[bool, Optional[str]]:
        """
        Determine whether the conversation is missing information.

        Product search requirements are intentionally handled by the
        dedicated requirement engine. This method remains for compatibility
        with existing callers and handles generic intent requirements.
        """

        if context.awaiting_entity:
            return (
                True,
                f"Please provide the "
                f"{context.awaiting_entity.value}.",
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
            for entity in entities
        }

        if context.current_product:
            found_types.add(
                EntityType.PRODUCT
            )

        for required_entity in required:
            if required_entity not in found_types:
                return (
                    True,
                    f"Could you please specify "
                    f"the {required_entity.value}?",
                )

        return False, None