"""
Greeting handler - responds to greeting messages.
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


class GreetingHandler(BaseHandler):
    """
    Handles greeting intents (hi, hello, hey, etc.).
    Returns a warm welcome message as plain text without buttons.
    """
    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:
        # Prefer the tenant-scoped message template stored in MongoDB.
        template = None
        try:
            template = await collections.templates.find_one({
                "tenant_id": tenant_id,
                "name": "greeting",
                "is_active": True,
            })
        except Exception as exc:
            logger.warning(f"Unable to load greeting template from MongoDB: {exc}")

        welcome_msg = tenant_settings.get(
            "welcome_message",
            "Welcome! How can I help you today?",
        )

        if template and template.get("body_text"):
            welcome_msg = template["body_text"]

        # Set quick_replies to [] so no buttons or lists are sent
        return BotResponse(
            response_type="text",
            text=welcome_msg,
            quick_replies=[],
            metadata={
                "greeting_handled": True,
                "template_source": "db" if template else "fallback",
            },
        )
