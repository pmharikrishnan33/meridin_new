"""
OpenRouter LLM client.

Provides an async interface to the OpenRouter chat completions API.
Used for AI-powered fallback responses and human-handoff escalation.
"""

from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.utils.logger import logger
from app.ai.prompts import build_fallback_messages


class OpenRouterClient:
    """
    Async client for the OpenRouter API.

    Usage::

        client = OpenRouterClient()
        reply = await client.chat(
            messages=[{"role": "user", "content": "Hello!"}],
        )
    """

    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        app_name: str = "Meridin",
        site_url: str = "https://meridin.ai",
        timeout: float = 30.0,
    ):
        self._api_key = api_key or settings.OPENROUTER_API_KEY
        self._model = model or settings.OPENROUTER_MODEL
        self._app_name = app_name
        self._site_url = site_url
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        """Whether the client has an API key and model configured."""
        return bool(self._api_key) and bool(self._model)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._site_url,
            "X-Title": self._app_name,
        }
        return headers

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 500,
        **extra: Any,
    ) -> str:
        """
        Send a chat completion request and return the assistant's reply text.

        Args:
            messages: List of message dicts with "role" and "content" keys.
            temperature: Sampling temperature (0 = deterministic, 1 = creative).
            max_tokens: Maximum tokens to generate.
            **extra: Additional parameters forwarded to the API.

        Returns:
            The assistant's reply as a string.
        """
        if not self.is_configured:
            raise RuntimeError(
                "OpenRouter client is not configured. "
                "Set OPENROUTER_API_KEY and OPENROUTER_MODEL in your environment."
            )

        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **extra,
        }

        client = self._get_client()
        try:
            response = await client.post(
                self.API_URL,
                headers=self._build_headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter API error: {e.response.status_code} {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"OpenRouter request failed: {e}")
            raise

        choices = data.get("choices", [])
        if not choices:
            logger.warning("OpenRouter returned no choices in the response.")
            return ""

        return choices[0].get("message", {}).get("content", "")

    async def generate_fallback_response(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        tenant_settings: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Generate a tenant-aware contextual fallback response."""
        from app.models.schemas import IntentType, MessageUnderstanding

        understanding = MessageUnderstanding(
            original_text=user_message,
            normalized_text=user_message,
            intent=IntentType.UNKNOWN,
            intent_confidence=0.0,
        )
        messages = build_fallback_messages(
            user_message,
            tenant_settings=tenant_settings,
            conversation_history=conversation_history,
        )
        return await self.chat(messages, temperature=0.7, max_tokens=300)


# Module-level singleton for convenient imports
openrouter_client = OpenRouterClient()
