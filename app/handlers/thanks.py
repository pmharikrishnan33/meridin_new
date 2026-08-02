"""
Thanks handler - responds to thank-you messages.
"""

from typing import Dict, Any, Optional

from app.handlers.base_handler import BaseHandler
from app.models.schemas import (
    MessageUnderstanding,
    ConversationContext,
    BotResponse,
)


class ThanksHandler(BaseHandler):
    """
    Handles thank-you intents.
    Returns a polite acknowledgment.
    """

    RESPONSES = [
        "You're welcome! Is there anything else I can help with?",
        "My pleasure! Let me know if you need anything else.",
        "Happy to help! What else can I do for you today?",
    ]

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:

        # Pick a response — deterministic based on confidence for variety
        idx = int(understanding.intent_confidence * len(self.RESPONSES)) % len(self.RESPONSES)
        response_text = self.RESPONSES[idx]

        return BotResponse(
            response_type="text",
            text=response_text,
            metadata={
                "thanks_handled": True,
            },
        )
