"""
WhatsApp outbound messaging service.

Sends bot replies back to Meta's WhatsApp Cloud API so that customers
receive messages on their devices.  Each tenant supplies its own
``phone_number_id`` and ``access_token`` (stored in MongoDB or passed
through the request).
"""

from typing import Any, Dict, List, Optional, Union

import httpx

from app.models.schemas import BotResponse, ResponseProduct
from app.utils.logger import logger


class WhatsAppSender:
    """
    Sends messages to WhatsApp users via the Meta Graph API.

    The Graph API base URL is::

        https://graph.facebook.com/v18.0/{phone_number_id}/messages

    A successful response returns ``{"messages": [{"id": "..."}]}``.
    """

    GRAPH_API_BASE = "https://graph.facebook.com/v18.0"

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _build_headers(access_token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    async def send_text(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        text: str,
        preview_url: bool = False,
    ) -> Dict[str, Any]:
        """
        Send a plain-text message to a WhatsApp user.

        Args:
            phone_number_id: The WhatsApp Business Account phone number ID.
            access_token: A valid Meta access token.
            to: The recipient's phone number (country code + number, no ``+``).
            text: The message body (max 4096 characters).
            preview_url: Whether to render URLs as clickable previews.

        Returns:
            The parsed JSON response from Meta.
        """
        url = f"{self.GRAPH_API_BASE}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": preview_url,
                "body": text,
            },
        }

        return await self._send(url, access_token, payload)

    async def send_reaction(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        message_id: str,
        emoji: str,
    ) -> Dict[str, Any]:
        """Send a reaction emoji to a specific message."""
        url = f"{self.GRAPH_API_BASE}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "reaction",
            "reaction": {
                "message_id": message_id,
                "emoji": emoji,
            },
        }
        return await self._send(url, access_token, payload)

    async def send_image(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        image_url: str,
        caption: str,
    ) -> Dict[str, Any]:
        """Send an image message with a short product caption."""
        url = f"{self.GRAPH_API_BASE}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {
                "link": image_url,
                "caption": caption,
            },
        }
        return await self._send(url, access_token, payload)

    async def send_interactive(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        body_text: str,
        buttons: List[Dict[str, str]],
        button_type: str = "reply",
    ) -> Dict[str, Any]:
        """
        Send an interactive message with quick-reply buttons.

        Args:
            buttons: List of ``{"id": "...", "title": "..."}`` dicts.
        """
        url = f"{self.GRAPH_API_BASE}/{phone_number_id}/messages"
        interactive: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "body": {"text": body_text},
                "action": {},
            },
        }

        if button_type == "reply":
            interactive["interactive"]["action"] = {
                "button": "Choose an option",
                "sections": [
                    {
                        "rows": [
                            {"id": b.get("id", b["title"]), "title": b["title"]}
                            for b in buttons
                        ]
                    }
                ],
            }
            interactive["interactive"]["type"] = "list"
        else:
            interactive["interactive"]["action"] = {
                "button": body_text,
                "sections": [],
            }
            interactive["interactive"]["type"] = "button"
            interactive["interactive"]["action"]["buttons"] = [
                {"type": "reply", "reply": {"id": b.get("id", b["title"]), "title": b["title"]}}
                for b in buttons
            ]

        return await self._send(url, access_token, interactive)

    async def send_bot_response(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        response: BotResponse,
    ) -> Dict[str, Any]:
        """
        Convert a :class:`~app.models.schemas.BotResponse` into the appropriate
        WhatsApp API call(s).

        - ``text`` / ``order_status`` → plain text message
        - ``product_list`` / ``product_card`` → image caption for the first card
          plus a follow-up text response with remaining details/replies
        - ``template`` → text message referencing a template name (if available)
        """
        if not response.text and not response.products:
            return {"status": "skipped", "reason": "empty response"}

        if response.response_type in {"product_list", "product_card"} and response.products:
            for product in response.products:
                caption_lines = [
                    product.name,
                    f"Price: ₹{product.price:,.0f}",
                    f"Stock: {product.stock}",
                ]
                if product.colors_available:
                    caption_lines.append(f"Colors: {', '.join(product.colors_available)}")
                if product.sizes_available:
                    caption_lines.append(f"Sizes: {', '.join(product.sizes_available)}")
                if product.description:
                    caption_lines.append(product.description[:200])

                if product.image:
                    await self.send_image(
                        phone_number_id,
                        access_token,
                        to,
                        product.image,
                        "\n".join(caption_lines),
                    )
                else:
                    await self.send_text(
                        phone_number_id,
                        access_token,
                        to,
                        "\n".join(caption_lines),
                    )
            if response.quick_replies:
                buttons = [
                    {"id": r.get("value", r["label"]), "title": r["label"]}
                    for r in response.quick_replies
                ]
                return await self.send_interactive(
                    phone_number_id,
                    access_token,
                    to,
                    response.text or "What would you like to do?",
                    buttons,
                )

            return await self.send_text(
                phone_number_id,
                access_token,
                to,
                response.text or "Here are the products I found.",
            )

        # Build the text payload
        text = response.text or ""

        # Append quick-reply buttons if present
        if response.quick_replies:
            buttons = [
                {"id": r.get("value", r["label"]), "title": r["label"]}
                for r in response.quick_replies
            ]
            return await self.send_interactive(
                phone_number_id,
                access_token,
                to,
                text,
                buttons,
            )

        return await self.send_text(
            phone_number_id,
            access_token,
            to,
            text,
        )

    async def _send(
        self,
        url: str,
        access_token: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Internal helper: POST to the Graph API and return parsed JSON."""
        client = self._get_client()
        try:
            response = await client.post(
                url,
                headers=self._build_headers(access_token),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            logger.info(f"WhatsApp message sent successfully: {data}")
            return data
        except httpx.HTTPStatusError as e:
            logger.error(
                f"WhatsApp API error: {e.response.status_code} {e.response.text}"
            )
            return {"error": True, "status_code": e.response.status_code, "detail": e.response.text}
        except httpx.RequestError as e:
            logger.error(f"WhatsApp request failed: {e}")
            return {"error": True, "detail": str(e)}


# Module-level singleton
whatsapp_sender = WhatsAppSender()
