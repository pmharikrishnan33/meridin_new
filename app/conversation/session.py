import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.conversation.context import ConversationContextManager
from app.models.schemas import (
    ConversationContext,
    IntentType,
    EntityType,
    ExtractedEntity,
    MessageUnderstanding,
    MessageDirection,
    MessageType
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
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    search_cache: Dict[str, Dict[str, Any]] = field(default_factory=dict)

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
        bot_response_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
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
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        self.message_history.append(msg)
        self.context.message_count += 1
        self.last_updated = datetime.now(timezone.utc)

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
            if entity.entity_type == EntityType.CATEGORY:
                self.context.current_category = entity.normalized_value or entity.value

        # Store last search if this was a product search. Merge with any
        # previously captured filters so follow-up messages can refine the
        # set instead of dropping the earlier context.
        if understanding.intent == IntentType.PRODUCT_SEARCH:
            merged_filters = ConversationContextManager.merge_filters(
                self.context.last_search_filters,
                self._entities_to_filters(understanding.entities),
            )
            self.context.last_search_filters = merged_filters

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
                    operator = (entity.metadata or {}).get("operator", "exact")
                    if operator == "max":
                        filters["max_price"] = price
                    elif operator == "min":
                        filters["min_price"] = price
                    elif operator == "exact":
                        filters["max_price"] = price
                except (ValueError, TypeError):
                    pass

        return filters

    def store_active_search(
        self,
        search_key: str,
        query: Optional[str],
        filters: Optional[Dict[str, Any]],
        result_ids: List[str],
        offset: int = 0,
        total: Optional[int] = None,
        page_size: int = 10,
    ) -> Dict[str, Any]:
        """
        Persist the most recent active search state in the session cache.
        """

        total = total if total is not None else len(result_ids)
        page = max(1, (offset // page_size) + 1) if page_size > 0 else 1
        page_state = {
            "search_key": search_key,
            "query": query,
            "filters": filters or {},
            "result_ids": result_ids,
            "offset": offset,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

        self.search_cache[search_key] = page_state
        self.context.active_search_key = search_key
        self.context.active_search_offset = offset
        self.context.active_search_total = total
        self.context.active_search_query = query
        self.context.active_search_filters = filters or {}
        self.context.active_search_results = result_ids
        self.context.active_search_page = page
        self.context.active_search_page_size = page_size
        return page_state

    def get_active_search(self) -> Optional[Dict[str, Any]]:
        """
        Return the currently tracked active search state.
        """

        search_key = self.context.active_search_key
        if not search_key:
            return None
        return self.search_cache.get(search_key)

    def advance_active_search(self, page_size: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Advance the stored active search by one page using the cached result list.
        """

        active = self.get_active_search()
        if not active:
            return None

        page_size = page_size or self.context.active_search_page_size or active.get("page_size", 10)
        page = active.get("page", 1)
        next_offset = min(active.get("offset", 0) + page_size, active.get("total", 0))
        if next_offset < 0:
            next_offset = 0

        active["offset"] = next_offset
        active["page"] = max(1, (next_offset // page_size) + 1) if page_size > 0 else 1
        active["page_size"] = page_size

        self.context.active_search_offset = active["offset"]
        self.context.active_search_page = active["page"]
        self.context.active_search_page_size = page_size
        return active

    def resolve_reply_context(self, incoming_text: str) -> Optional[str]:
        """
        Resolve a lightweight follow-up product-selection context from the
        most recent outbound product-list response.

        This is the minimal notebook-style reply-linking step: when the user
        follows up with a selection phrase such as "this", "that", or "one",
        the session reuses the most recent product list response as the
        selected context.
        """

        text_lower = (incoming_text or "").lower()
        selection_markers = {"this", "that", "this one", "that one"}
        if not any(
            re.search(rf"\b{re.escape(marker)}\b", text_lower)
            for marker in selection_markers
        ):
            return None

        for message in reversed(self.message_history):
            if message.get("direction") != "outbound":
                continue
            bot_type = message.get("bot_response_type")
            metadata = message.get("metadata") or {}
            product_ids = metadata.get("product_ids") or []
            if bot_type in {"product_list", "product_card"} and product_ids:
                selected_product = product_ids[0]
                self.context.current_product = selected_product
                self.context.last_search_results = product_ids
                return selected_product

            selected_product = metadata.get("selected_product_id")
            if selected_product:
                self.context.current_product = selected_product
                return selected_product

        return None

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
            "message_count": self.context.message_count,
            "active_search_key": self.context.active_search_key,
            "active_search_query": self.context.active_search_query,
            "active_search_offset": self.context.active_search_offset,
            "active_search_total": self.context.active_search_total,
            "active_search_results": self.context.active_search_results,
            "active_search_page": self.context.active_search_page,
            "active_search_page_size": self.context.active_search_page_size,
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
            "search_cache": self.search_cache,
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
            search_cache=data.get("search_cache", {}),
            is_active=data.get("is_active", True),
            last_updated=datetime.fromisoformat(data["last_updated"]) if isinstance(data.get("last_updated"), str) else data.get("last_updated", datetime.now(timezone.utc))
        )

        return session
