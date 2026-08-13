"""
Conversation context management utilities.
"""

from typing import Dict, Any, Optional, List

from app.models.schemas import (
    ConversationContext,
    IntentType,
    EntityType,
    ExtractedEntity,
    MessageUnderstanding,
)


class ConversationContextManager:
    """
    Manages conversation context updates based on message understanding.
    """

    @staticmethod
    def update_from_understanding(
        context: ConversationContext,
        understanding: MessageUnderstanding
    ) -> ConversationContext:
        """
        Update context from message understanding.
        """

        # Update current intent
        context.current_intent = understanding.intent

        # Update entities
        for entity in understanding.entities:
            ConversationContextManager._apply_entity(context, entity)

        return context

    @staticmethod
    def _apply_entity(context: ConversationContext, entity: ExtractedEntity) -> None:
        """
        Apply a single entity to context.
        """

        if entity.entity_type == EntityType.CATEGORY:
            context.current_category = entity.normalized_value or entity.value

        elif entity.entity_type == EntityType.ORDER_ID:
            context.last_order_id = entity.normalized_value or entity.value

    @staticmethod
    def entities_to_filters(entities: List[ExtractedEntity]) -> Dict[str, Any]:
        """
        Convert extracted entities to search filters.
        """

        filters = {}
        for entity in entities:
            if entity.entity_type == EntityType.CATEGORY:
                filters["category"] = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.PRODUCT:
                filters["query"] = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.COLOR:
                filters["color"] = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.SIZE:
                filters["size"] = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.FIT:
                filters["fit"] = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.PRICE:
                try:
                    price = float(entity.normalized_value or entity.value)
                    operator = (entity.metadata or {}).get("operator", "exact")
                    if operator == "max":
                        filters["max_price"] = price
                    elif operator == "min":
                        filters["min_price"] = price
                    elif operator == "exact":
                        filters["max_price"] = price
                except (ValueError, TypeError):
                    pass
            elif entity.entity_type == EntityType.BRAND:
                filters["brand"] = entity.normalized_value or entity.value

        return filters

    @staticmethod
    def merge_filters(existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge new filters with existing, new takes precedence.
        """

        merged = existing.copy()
        merged.update(new)
        return merged

    @staticmethod
    def should_ask_clarification(
        context: ConversationContext,
        intent: IntentType,
        entities: List[ExtractedEntity]
    ) -> tuple[bool, Optional[str]]:
        """
        Determine whether the conversation is missing information required
        for the current intent.
        """

        if context.awaiting_entity:
            return (
                True,
                f"Please provide the {context.awaiting_entity.value}.",
            )

        required_entities = {
            IntentType.PRODUCT_SEARCH: [EntityType.PRODUCT],
            IntentType.PRODUCT_INQUIRY: [EntityType.PRODUCT],
            IntentType.AVAILABILITY: [EntityType.PRODUCT],
        }

        required = required_entities.get(intent, [])
        found_types = {
            entity.entity_type
            for entity in entities
        }

        if context.current_product:
            found_types.add(EntityType.PRODUCT)

        for required_entity in required:
            if required_entity not in found_types:
                return (
                    True,
                    f"Could you please specify the {required_entity.value}?",
                )

        return False, None
