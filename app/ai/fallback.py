"""
AI-powered fallback response generation.

When the keyword-based intent classifier is uncertain (confidence below
threshold) or the intent is UNKNOWN, this module delegates to the
OpenRouter LLM to generate a contextual response.  It is used by the
FallbackHandler when the ``enable_ai_responses`` feature flag is on.
"""

from typing import Dict, Any, Optional

from app.ai.openrouter import openrouter_client
from app.ai.prompts import build_fallback_messages, RESPONSE_TEMPLATES
from app.models.schemas import BotResponse, MessageUnderstanding, IntentType
from app.utils.logger import logger


class AIFallbackGenerator:
    """
    Generates LLM-powered fallback responses.

    Falls back to a static template if the OpenRouter client is not
    configured or the API call fails.
    """

    def __init__(self):
        self._client = openrouter_client

    @property
    def is_available(self) -> bool:
        """Whether the AI fallback can actually reach the LLM."""
        return self._client.is_configured

    async def generate(
        self,
        understanding: MessageUnderstanding,
        tenant_settings: Dict[str, Any],
        conversation_history: Optional[list[Dict[str, str]]] = None,
    ) -> BotResponse:
        """
        Generate a fallback response.

        Tries the LLM first; if unavailable or the call fails, falls back
        to a static template message.
        """
        if not self.is_available:
            logger.info("AI fallback unavailable; using static template.")
            return self._static_fallback(tenant_settings)

        try:
            messages = build_fallback_messages(
                understanding.original_text,
                tenant_settings=tenant_settings,
                conversation_history=conversation_history,
            )
            text = await self._client.chat(messages, temperature=0.7, max_tokens=300)
        except Exception as e:
            logger.warning(f"AI fallback generation failed: {e}")
            return self._static_fallback(tenant_settings)

        return BotResponse(
            response_type="ai",
            text=text or tenant_settings.get("fallback_message", RESPONSE_TEMPLATES["fallback"]),
            metadata={"ai_generated": True, "intent": understanding.intent.value},
        )

    def _static_fallback(self, tenant_settings: Dict[str, Any]) -> BotResponse:
        """Return a static fallback response."""
        fallback_msg = tenant_settings.get(
            "fallback_message",
            RESPONSE_TEMPLATES["fallback"],
        )
        return BotResponse(
            response_type="text",
            text=fallback_msg,
            metadata={"ai_generated": False, "fallback": True},
        )


ai_fallback = AIFallbackGenerator()
