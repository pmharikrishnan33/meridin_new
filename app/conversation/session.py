from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional

from app.models.schemas import (
    ConversationContext,
    IntentType,
    EntityType,
    ExtractedEntity,
    MessageUnderstanding,
    MessageDirection,
    MessageType,
    ConversationStatus,
)


@dataclass
class ConversationSession:
    """
    In-memory conversation session with context management.
    Persisted to MongoDB periodically and on important events.
    """

    conversation_id: str
    tenant_id: str
    customer_id: str
    context: ConversationContext = field(default_factory=ConversationContext)
    message_history: List[Dict[str, Any]] = field(default_factory=list)
    is_active: bool = True
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def add_message(
        self,
        message_id: str,
        direction: MessageDirection,
        text: str,
        message_type: MessageType = MessageType.TEXT,
        intent: Optional[IntentType] = None,
        intent_confidence: Optional[float] = None,
        entities: Optional[List[ExtractedEntity]] = None,
        is_from_bot: bool = False,
        bot_response_type: Optional[str] = None
    ) -> None:
        """
        Add message to history and update context.
        """

        msg = {
            "message_id": message_id,
            "direction": direction.value,
            "text": text,
            "message_type": message_type.value,
            "intent": intent.value if intent else None,
            "intent_confidence": intent_confidence,
            "entities": [e.model_dump() if hasattr(e, 'model_dump') else e for e in entities] if entities else [],
            "is_from_bot": is_from_bot,
            "bot_response_type": bot_response_type,
            "timestamp": datetime.utcnow().isoformat()
        }

        self.message_history.append(msg)
        self.context.message_count += 1
        self.last_updated = datetime.utcnow()

        # Keep only last 20 messages in memory
        if len(self.message_history) > 20:
            self.message_history = self.message_history[-20:]

    def update_context_from_understanding(
        self,
        understanding: MessageUnderstanding
    ) -> None:
        """
        Update conversation context from ML understanding.
        """

        self.context.current_intent = understanding.intent

        # Update entities in context
        for entity in understanding.entities:
            if entity.entity_type == EntityType.PRODUCT:
                self.context.current_product = entity.normalized_value or entity.value
            elif entity.entity_type == EntityType.CATEGORY:
                self.context.current_category = entity.normalized_value or entity.value

        # Store last search if this was a product search
        if understanding.intent == IntentType.PRODUCT_SEARCH:
            self.context.last_search_filters = self._entities_to_filters(understanding.entities)

    def _entities_to_filters(self, entities: List[ExtractedEntity]) -> Dict[str, Any]:
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
                    if "under" in str(entity.value).lower() or "below" in str(entity.value).lower():
                        filters["max_price"] = price
                    elif "above" in str(entity.value).lower() or "over" in str(entity.value).lower():
                        filters["min_price"] = price
                    else:
                        filters["price"] = price
                except ValueError:
                    pass

        return filters

    def get_context_for_response(self) -> Dict[str, Any]:
        """
        Get context summary for response generation.
        """

        return {
            "current_intent": self.context.current_intent.value if self.context.current_intent else None,
            "current_product": self.context.current_product,
            "current_category": self.context.current_category,
            "last_search_filters": self.context.last_search_filters,
            "last_search_results": self.context.last_search_results,
            "last_order_id": self.context.last_order_id,
            "awaiting_entity": self.context.awaiting_entity.value if self.context.awaiting_entity else None,
            "awaiting_confirmation": self.context.awaiting_confirmation,
            "confirmation_context": self.context.confirmation_context,
            "language": self.context.language,
            "message_count": self.context.message_count
        }

    def set_awaiting_entity(self, entity_type: EntityType) -> None:
        """
        Mark that we're waiting for a specific entity from user.
        """

        self.context.awaiting_entity = entity_type

    def clear_awaiting_entity(self) -> None:
        """
        Clear awaiting entity state.
        """

        self.context.awaiting_entity = None

    def set_awaiting_confirmation(self, context: Dict[str, Any]) -> None:
        """
        Mark that we're waiting for user confirmation.
        """

        self.context.awaiting_confirmation = True
        self.context.confirmation_context = context

    def clear_awaiting_confirmation(self) -> None:
        """
        Clear awaiting confirmation state.
        """

        self.context.awaiting_confirmation = False
        self.context.confirmation_context = {}

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize session for MongoDB storage.
        """

        return {
            "conversation_id": self.conversation_id,
            "tenant_id": self.tenant_id,
            "customer_id": self.customer_id,
            "context": self.context.model_dump() if hasattr(self.context, 'model_dump') else self.context.__dict__,
            "message_history": self.message_history,
            "is_active": self.is_active,
            "last_updated": self.last_updated.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationSession":
        """
        Deserialize session from MongoDB.
        """

        context_data = data.get("context", {})
        context = ConversationContext(**context_data) if context_data else ConversationContext()

        session = cls(
            conversation_id=data["conversation_id"],
            tenant_id=data["tenant_id"],
            customer_id=data["customer_id"],
            context=context,
            message_history=data.get("message_history", []),
            is_active=data.get("is_active", True),
            last_updated=datetime.fromisoformat(data["last_updated"]) if isinstance(data.get("last_updated"), str) else data.get("last_updated", datetime.utcnow())
        )

        return session