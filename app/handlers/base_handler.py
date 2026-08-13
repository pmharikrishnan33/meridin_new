"""
Base handler - abstract interface for all intent handlers.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from app.models.schemas import (
    MessageUnderstanding,
    ConversationContext,
    BotResponse,
)


class BaseHandler(ABC):
    """
    Abstract base class for all intent handlers.

    Each handler receives the full message understanding (intent, entities,
    confidence, sentiment, etc.) plus tenant settings and conversation
    context, and returns a structured BotResponse ready for WhatsApp
    formatting.
    """

    @abstractmethod
    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:
        """
        Process the understood message and return a bot response.

        Args:
            understanding: The full ML output (intent, entities, confidence, ...).
            tenant_id: The tenant identifier.
            tenant_settings: Tenant-specific settings dict (includes feature_flags).
            conversation_context: Current conversation context (may be None).

        Returns:
            BotResponse ready to be sent to the customer.
        """
        ...
