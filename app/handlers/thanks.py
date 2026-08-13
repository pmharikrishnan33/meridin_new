"""
Thanks handler - responds to thank-you messages.
"""

from typing import Dict, Any, Optional

from app.database.collections import collections
from app.handlers.base_handler import BaseHandler
from app.models.schemas import (
    MessageUnderstanding,
    ConversationContext,
    BotResponse,
)
from app.utils.logger import logger


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

        template = None
        try:
            template = await collections.templates.find_one({
                "tenant_id": tenant_id,
                "name": "thanks",
                "is_active": True,
            })
        except Exception as exc:
            logger.warning(f"Unable to load thanks template from MongoDB: {exc}")

        # Pick a response — deterministic based on confidence for variety
        idx = int(understanding.intent_confidence * len(self.RESPONSES)) % len(self.RESPONSES)
        response_text = self.RESPONSES[idx]
        if template and template.get("body_text"):
            response_text = template["body_text"]

        return BotResponse(
            response_type="text",
            text=response_text,
            metadata={
                "thanks_handled": True,
                "template_source": "db" if template else "fallback",
            },
        )
