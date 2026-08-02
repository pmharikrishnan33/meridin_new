"""
Fallback handler - used when intent is unknown or routing fails.
"""

from typing import Dict, Any, Optional, List

from app.handlers.base_handler import BaseHandler
from app.models.schemas import (
    MessageUnderstanding,
    ConversationContext,
    BotResponse,
)
from app.ai.fallback import ai_fallback
from app.utils.logger import logger


class FallbackHandler(BaseHandler):
    """
    Handles UNKNOWN intents and routing failures.

    When the tenant has ``enable_ai_responses`` enabled and the OpenRouter
    client is configured, delegates to the LLM for a contextual reply.
    Otherwise returns a static fallback message with helpful quick-reply
    options.
    """

    QUICK_REPLIES = [
        {"label": "Browse Products", "value": "browse_products"},
        {"label": "Track Order", "value": "track_order"},
        {"label": "Contact Support", "value": "contact_support"},
    ]

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:

        fallback_msg = tenant_settings.get(
            "fallback_message",
            "I didn't understand that. Could you please rephrase?",
        )

        # Try AI-powered fallback when the feature flag is on and the
        # OpenRouter client is configured.
        feature_flags = tenant_settings.get("feature_flags", {})
        if feature_flags.get("enable_ai_responses", False) and ai_fallback.is_available:
            try:
                history = self._build_history_from_context(conversation_context)
                ai_response = await ai_fallback.generate(
                    understanding=understanding,
                    tenant_settings=tenant_settings,
                    conversation_history=history,
                )
                ai_response.quick_replies = self.QUICK_REPLIES
                logger.info("AI fallback response generated successfully.")
                return ai_response
            except Exception as exc:
                logger.warning(f"AI fallback failed, using static response: {exc}")

        # Static fallback
        return BotResponse(
            response_type="text",
            text=fallback_msg,
            quick_replies=self.QUICK_REPLIES,
            metadata={
                "fallback": True,
            },
        )

    @staticmethod
    def _build_history_from_context(
        conversation_context: Optional[ConversationContext],
    ) -> Optional[List[Dict[str, str]]]:
        """
        Convert the conversation context's message history (if available)
        into the OpenRouter chat message format.

        The session stores messages as dicts with ``direction`` and ``text``
        keys; we map inbound → user, outbound → assistant.
        """
        if conversation_context is None:
            return None

        # ConversationContext itself doesn't carry message_history; that
        # lives on ConversationSession.  When a session is available the
        # router passes its context by reference, so we attempt to read
        # ``_message_history`` from the context object (set by the router
        # when a session exists).
        history = getattr(conversation_context, "_message_history", None)
        if not history:
            return None

        messages: List[Dict[str, str]] = []
        for msg in history[-10:]:
            direction = msg.get("direction", "")
            text = msg.get("text", "")
            if not text:
                continue
            role = "assistant" if direction == "outbound" else "user"
            messages.append({"role": role, "content": text})

        return messages if messages else None
