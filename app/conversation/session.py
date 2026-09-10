from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.conversation.context import ConversationContextManager
from app.models.schemas import (
    ConversationContext,
    EntityType,
    ExtractedEntity,
    IntentType,
    MessageDirection,
    MessageType,
    MessageUnderstanding,
)


MAX_MESSAGE_HISTORY = 20
DEFAULT_PAGE_SIZE = 3


@dataclass
class ConversationSession:
    """
    In-memory representation of a conversation session.

    The conversation manager is responsible for persistence. This class
    owns the session state and provides safe helpers for updating search,
    clarification, and message-history state.
    """

    conversation_id: str
    tenant_id: str
    customer_id: str

    context: ConversationContext = field(
        default_factory=ConversationContext
    )

    message_history: List[Dict[str, Any]] = field(
        default_factory=list
    )

    is_active: bool = True

    last_updated: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    search_cache: Dict[str, Dict[str, Any]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        """
        Keep the private context history synchronized after construction.
        """

        self._synchronize_history()

    # ============================================================
    # MESSAGE HISTORY
    # ============================================================

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
        Add a message to the bounded conversation history.
        """

        serialized_entities: List[Dict[str, Any]] = []

        for entity in entities or []:
            if hasattr(entity, "model_dump"):
                serialized_entities.append(
                    entity.model_dump()
                )
            elif isinstance(entity, dict):
                serialized_entities.append(
                    dict(entity)
                )

        message = {
            "message_id": message_id,
            "direction": direction.value,
            "text": text or "",
            "message_type": message_type.value,
            "intent": (
                intent.value
                if isinstance(intent, IntentType)
                else intent
            ),
            "intent_confidence": intent_confidence,
            "entities": serialized_entities,
            "is_from_bot": is_from_bot,
            "bot_response_type": bot_response_type,
            "metadata": metadata or {},
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        self.message_history.append(message)

        if len(self.message_history) > MAX_MESSAGE_HISTORY:
            self.message_history = self.message_history[
                -MAX_MESSAGE_HISTORY:
            ]

        self.context.message_count += 1
        self.last_updated = datetime.now(timezone.utc)

        self._synchronize_history()

    def _synchronize_history(self) -> None:
        """
        Synchronize the private context history with the bounded session
        history.

        ConversationContext intentionally keeps this as a PrivateAttr, so
        it is never persisted directly as part of the Pydantic model.
        """

        self.context._message_history = self.message_history

    # ============================================================
    # UNDERSTANDING / CONTEXT
    # ============================================================

    def update_context_from_understanding(
        self,
        understanding: MessageUnderstanding,
    ) -> None:
        """
        Update conversation context from message understanding.

        Search filters are merged rather than replaced so a follow-up such
        as "M" can refine an earlier "black shirt" search.
        """

        ConversationContextManager.update_from_understanding(
            self.context,
            understanding,
        )

        if understanding.intent == IntentType.PRODUCT_SEARCH:
            new_filters = (
                ConversationContextManager.entities_to_filters(
                    understanding.entities
                )
            )

            self.context.last_search_filters = (
                ConversationContextManager.merge_filters(
                    self.context.last_search_filters,
                    new_filters,
                )
            )

        self.last_updated = datetime.now(timezone.utc)

    # Backwards-compatible helper retained for callers that used the
    # previous private conversion method.
    @staticmethod
    def _entities_to_filters(
        entities: List[ExtractedEntity],
    ) -> Dict[str, Any]:
        return ConversationContextManager.entities_to_filters(
            entities
        )

    # ============================================================
    # ACTIVE SEARCH
    # ============================================================

    def store_active_search(
        self,
        search_key: str,
        query: Optional[str],
        filters: Optional[Dict[str, Any]],
        result_ids: List[str],
        offset: int = 0,
        total: Optional[int] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Dict[str, Any]:
        """
        Store the current search state.

        The result list is bounded to avoid accidentally creating a very
        large conversation document.
        """

        safe_page_size = max(
            1,
            int(page_size or DEFAULT_PAGE_SIZE),
        )

        safe_offset = max(
            0,
            int(offset or 0),
        )

        safe_result_ids = [
            str(result_id)
            for result_id in (result_ids or [])
            if result_id is not None
        ]

        safe_total = (
            int(total)
            if total is not None
            else len(safe_result_ids)
        )

        safe_total = max(
            0,
            safe_total,
        )

        page = (
            safe_offset // safe_page_size
        ) + 1

        page_state = {
            "search_key": search_key,
            "query": query,
            "filters": dict(filters or {}),
            "result_ids": safe_result_ids,
            "offset": safe_offset,
            "total": safe_total,
            "page": page,
            "page_size": safe_page_size,
        }

        self.search_cache[search_key] = page_state

        # Keep only the current active search in the cache. Old search
        # states are stale and can otherwise grow indefinitely.
        for key in list(self.search_cache.keys()):
            if key != search_key:
                del self.search_cache[key]

        self.context.active_search_key = search_key
        self.context.active_search_offset = safe_offset
        self.context.active_search_total = safe_total
        self.context.active_search_query = query
        self.context.active_search_filters = dict(
            filters or {}
        )
        self.context.active_search_results = safe_result_ids
        self.context.active_search_page = page
        self.context.active_search_page_size = safe_page_size

        self.last_updated = datetime.now(timezone.utc)

        return page_state

    def get_active_search(self) -> Optional[Dict[str, Any]]:
        """
        Return the currently active search state.
        """

        search_key = self.context.active_search_key

        if not search_key:
            return None

        return self.search_cache.get(search_key)

    def advance_active_search(
        self,
        page_size: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Advance the active search by one page.

        Does not move beyond the end of the result set.
        """

        active = self.get_active_search()

        if not active:
            return None

        safe_page_size = max(
            1,
            int(
                page_size
                or self.context.active_search_page_size
                or active.get(
                    "page_size",
                    DEFAULT_PAGE_SIZE,
                )
            ),
        )

        total = max(
            0,
            int(active.get("total", 0)),
        )

        current_offset = max(
            0,
            int(active.get("offset", 0)),
        )

        next_offset = min(
            current_offset + safe_page_size,
            total,
        )

        active["offset"] = next_offset
        active["page_size"] = safe_page_size
        active["page"] = (
            next_offset // safe_page_size
        ) + 1

        self.context.active_search_offset = next_offset
        self.context.active_search_page = active["page"]
        self.context.active_search_page_size = safe_page_size

        self.last_updated = datetime.now(timezone.utc)

        return active

    def clear_active_search(self) -> None:
        """
        Clear the active pagination/search state.
        """

        self.search_cache.clear()

        self.context.active_search_key = None
        self.context.active_search_offset = 0
        self.context.active_search_total = 0
        self.context.active_search_query = None
        self.context.active_search_filters = {}
        self.context.active_search_results = []
        self.context.active_search_page = 1
        self.context.active_search_page_size = DEFAULT_PAGE_SIZE

        self.last_updated = datetime.now(timezone.utc)

    # ============================================================
    # PRODUCT REPLY CONTEXT
    # ============================================================

    def resolve_reply_context(
        self,
        incoming_text: str,
    ) -> Optional[str]:
        """
        Resolve a lightweight product-selection reference.

        This intentionally only resolves unambiguous first-result references
        such as "this", "that", "this one", and "that one".

        It does not claim that an arbitrary product in a list was selected.
        """

        text_lower = (
            incoming_text or ""
        ).strip().lower()

        selection_patterns = (
            r"\bthis\b",
            r"\bthat\b",
            r"\bthis\s+one\b",
            r"\bthat\s+one\b",
        )

        if not any(
            re.search(
                pattern,
                text_lower,
            )
            for pattern in selection_patterns
        ):
            return None

        for message in reversed(
            self.message_history
        ):
            if (
                message.get("direction")
                != MessageDirection.OUTBOUND.value
            ):
                continue

            bot_type = message.get(
                "bot_response_type"
            )

            metadata = (
                message.get("metadata")
                or {}
            )

            if bot_type not in {
                "product_list",
                "product_card",
            }:
                continue

            product_ids = metadata.get(
                "product_ids"
            ) or []

            if product_ids:
                selected_product = str(
                    product_ids[0]
                )

                self.context.current_product = (
                    selected_product
                )

                self.context.last_search_results = [
                    str(product_id)
                    for product_id in product_ids
                ]

                self.last_updated = datetime.now(
                    timezone.utc
                )

                return selected_product

            selected_product = metadata.get(
                "selected_product_id"
            )

            if selected_product:
                selected_product = str(
                    selected_product
                )

                self.context.current_product = (
                    selected_product
                )

                self.last_updated = datetime.now(
                    timezone.utc
                )

                return selected_product

        return None

    # ============================================================
    # RESPONSE CONTEXT
    # ============================================================

    def get_context_for_response(
        self,
    ) -> Dict[str, Any]:
        """
        Return a serializable context summary for response generation.
        """

        return {
            "current_intent": (
                self.context.current_intent.value
                if self.context.current_intent
                else None
            ),
            "current_product": (
                self.context.current_product
            ),
            "current_category": (
                self.context.current_category
            ),
            "last_search_filters": dict(
                self.context.last_search_filters
            ),
            "last_search_results": list(
                self.context.last_search_results
            ),
            "last_order_id": (
                self.context.last_order_id
            ),
            "awaiting_entity": (
                self.context.awaiting_entity.value
                if self.context.awaiting_entity
                else None
            ),
            "awaiting_confirmation": (
                self.context.awaiting_confirmation
            ),
            "confirmation_context": dict(
                self.context.confirmation_context
            ),
            "language": self.context.language,
            "message_count": self.context.message_count,
            "active_search_key": (
                self.context.active_search_key
            ),
            "active_search_query": (
                self.context.active_search_query
            ),
            "active_search_offset": (
                self.context.active_search_offset
            ),
            "active_search_total": (
                self.context.active_search_total
            ),
            "active_search_filters": dict(
                self.context.active_search_filters
            ),
            "active_search_results": list(
                self.context.active_search_results
            ),
            "active_search_page": (
                self.context.active_search_page
            ),
            "active_search_page_size": (
                self.context.active_search_page_size
            ),
        }

    # ============================================================
    # CLARIFICATION / CONFIRMATION STATE
    # ============================================================

    def set_awaiting_entity(
        self,
        entity_type: EntityType,
        *,
        requirement: Optional[Dict[str, Any]] = None,
        intent: IntentType = IntentType.PRODUCT_SEARCH,
    ) -> None:
        """
        Mark the session as waiting for a specific entity.
        """

        self.context.awaiting_entity = entity_type
        self.context.awaiting_confirmation = False

        confirmation_context = dict(
            self.context.confirmation_context
        )

        confirmation_context["intent"] = (
            intent.value
        )

        if requirement:
            confirmation_context[
                "requirement"
            ] = dict(requirement)

        self.context.confirmation_context = (
            confirmation_context
        )

        self.last_updated = datetime.now(
            timezone.utc
        )

    def clear_awaiting_entity(self) -> None:
        """
        Clear pending entity collection state.
        """

        self.context.awaiting_entity = None

        if (
            self.context.confirmation_context
        ):
            self.context.confirmation_context.pop(
                "requirement",
                None,
            )
            self.context.confirmation_context.pop(
                "missing_entities",
                None,
            )

        self.last_updated = datetime.now(
            timezone.utc
        )

    def set_awaiting_confirmation(
        self,
        context: Dict[str, Any],
    ) -> None:
        """
        Mark that the session is waiting for confirmation.
        """

        self.context.awaiting_confirmation = True
        self.context.confirmation_context = dict(
            context or {}
        )

        self.last_updated = datetime.now(
            timezone.utc
        )

    def clear_awaiting_confirmation(self) -> None:
        """
        Clear confirmation state.
        """

        self.context.awaiting_confirmation = False
        self.context.confirmation_context = {}

        self.last_updated = datetime.now(
            timezone.utc
        )

    def clear_pending_state(self) -> None:
        """
        Clear both clarification and confirmation state.
        """

        self.context.awaiting_entity = None
        self.context.awaiting_confirmation = False
        self.context.confirmation_context = {}

        self.last_updated = datetime.now(
            timezone.utc
        )

    # ============================================================
    # SERIALIZATION
    # ============================================================

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the session for MongoDB persistence.
        """

        context_data = (
            self.context.model_dump()
            if hasattr(
                self.context,
                "model_dump",
            )
            else self.context.__dict__.copy()
        )

        return {
            "conversation_id": self.conversation_id,
            "tenant_id": self.tenant_id,
            "customer_id": self.customer_id,
            "context": context_data,
            "message_history": list(
                self.message_history
            ),
            "search_cache": dict(
                self.search_cache
            ),
            "is_active": self.is_active,
            "last_updated": self.last_updated.isoformat(),
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
    ) -> "ConversationSession":
        """
        Deserialize a persisted session.

        Invalid/missing optional state is normalized rather than allowed to
        corrupt the in-memory session.
        """

        context_data = data.get(
            "context"
        ) or {}

        context = (
            ConversationContext(
                **context_data
            )
            if context_data
            else ConversationContext()
        )

        last_updated_raw = data.get(
            "last_updated"
        )

        if isinstance(
            last_updated_raw,
            str,
        ):
            try:
                last_updated = (
                    datetime.fromisoformat(
                        last_updated_raw
                    )
                )
            except ValueError:
                last_updated = datetime.now(
                    timezone.utc
                )
        elif isinstance(
            last_updated_raw,
            datetime,
        ):
            last_updated = last_updated_raw
        else:
            last_updated = datetime.now(
                timezone.utc
            )

        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(
                tzinfo=timezone.utc
            )

        message_history = list(
            data.get(
                "message_history",
                [],
            )
            or []
        )

        message_history = message_history[
            -MAX_MESSAGE_HISTORY:
        ]

        search_cache = dict(
            data.get(
                "search_cache",
                {},
            )
            or {}
        )

        session = cls(
            conversation_id=str(
                data["conversation_id"]
            ),
            tenant_id=str(
                data["tenant_id"]
            ),
            customer_id=str(
                data["customer_id"]
            ),
            context=context,
            message_history=message_history,
            search_cache=search_cache,
            is_active=bool(
                data.get(
                    "is_active",
                    True,
                )
            ),
            last_updated=last_updated,
        )

        session._synchronize_history()

        return session