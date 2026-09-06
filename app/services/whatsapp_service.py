from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.models.schemas import BotResponse, ResponseProduct
from app.utils.logger import logger


@dataclass
class WhatsAppSendResult:
    success: bool
    provider_message_id: Optional[str] = None
    provider_message_ids: List[str] = field(
        default_factory=list
    )
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None

    @property
    def sent_count(self) -> int:
        return len(self.provider_message_ids)


class WhatsAppSender:
    GRAPH_API_BASE = (
        "https://graph.facebook.com/"
        f"{settings.WHATSAPP_GRAPH_API_VERSION}"
    )

    def __init__(
        self,
        timeout: float = 30.0,
    ) -> None:
        self._timeout = timeout
        self._client: Optional[
            httpx.AsyncClient
        ] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout
            )

        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _validate_credentials(
        phone_number_id: str,
        access_token: str,
        to: str,
    ) -> None:

        if not phone_number_id:
            raise ValueError(
                "phone_number_id is required"
            )

        if not access_token:
            raise ValueError(
                "access_token is required"
            )

        if not to:
            raise ValueError(
                "recipient phone number is required"
            )

    @staticmethod
    def _build_headers(
        access_token: str,
    ) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_message_id(
        data: Dict[str, Any],
    ) -> Optional[str]:

        messages = data.get("messages")

        if not isinstance(messages, list):
            return None

        if not messages:
            return None

        first_message = messages[0]

        if not isinstance(first_message, dict):
            return None

        message_id = first_message.get("id")

        return str(message_id) if message_id else None

    async def send_text(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        text: str,
        preview_url: bool = False,
    ) -> WhatsAppSendResult:

        self._validate_credentials(
            phone_number_id,
            access_token,
            to,
        )

        if not text or not text.strip():
            raise ValueError(
                "text is required"
            )

        url = (
            f"{self.GRAPH_API_BASE}/"
            f"{phone_number_id}/messages"
        )

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": preview_url,
                "body": text[:4096],
            },
        }

        return await self._send(
            url=url,
            access_token=access_token,
            payload=payload,
        )

    async def send_reaction(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        message_id: str,
        emoji: str,
    ) -> WhatsAppSendResult:

        self._validate_credentials(
            phone_number_id,
            access_token,
            to,
        )

        if not message_id:
            raise ValueError(
                "message_id is required"
            )

        if not emoji:
            raise ValueError(
                "emoji is required"
            )

        url = (
            f"{self.GRAPH_API_BASE}/"
            f"{phone_number_id}/messages"
        )

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "reaction",
            "reaction": {
                "message_id": message_id,
                "emoji": emoji,
            },
        }

        return await self._send(
            url=url,
            access_token=access_token,
            payload=payload,
        )

    async def send_catalog_product(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        catalog_id: str,
        product_retailer_id: str,
        body_text: Optional[str] = None,
    ) -> WhatsAppSendResult:
        """Send one real WhatsApp Commerce catalog product message."""
        self._validate_credentials(phone_number_id, access_token, to)

        if not catalog_id:
            raise ValueError("catalog_id is required")
        if not product_retailer_id:
            raise ValueError("product_retailer_id is required")

        interactive: Dict[str, Any] = {
            "type": "product",
            "action": {
                "catalog_id": str(catalog_id),
                "product_retailer_id": str(product_retailer_id),
            },
        }

        if body_text:
            interactive["body"] = {"text": body_text[:1024]}

        url = f"{self.GRAPH_API_BASE}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }

        return await self._send(
            url=url,
            access_token=access_token,
            payload=payload,
        )

    async def send_catalog_product_list(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        catalog_id: str,
        products: List[Dict[str, str]],
        body_text: str = "Here are the products I found:",
        header_text: str = "Products",
    ) -> WhatsAppSendResult:
        """Send multiple real WhatsApp Commerce catalog products."""
        self._validate_credentials(phone_number_id, access_token, to)

        if not catalog_id:
            raise ValueError("catalog_id is required")
        if not products:
            raise ValueError("at least one catalog product is required")

        product_items = []
        for item in products[:10]:
            retailer_id = str(item.get("product_retailer_id") or "").strip()
            if retailer_id:
                product_items.append({"product_retailer_id": retailer_id})

        if not product_items:
            raise ValueError("no valid product_retailer_id values supplied")

        url = f"{self.GRAPH_API_BASE}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "product_list",
                "header": {"type": "text", "text": header_text[:60]},
                "body": {"text": body_text[:1024]},
                "action": {
                    "catalog_id": str(catalog_id),
                    "sections": [
                        {
                            "title": "Products",
                            "product_items": product_items,
                        }
                    ],
                },
            },
        }

        return await self._send(
            url=url,
            access_token=access_token,
            payload=payload,
        )

    async def send_image(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        image_url: str,
        caption: Optional[str] = None,
    ) -> WhatsAppSendResult:

        self._validate_credentials(
            phone_number_id,
            access_token,
            to,
        )

        if not image_url:
            raise ValueError(
                "image_url is required"
            )

        url = (
            f"{self.GRAPH_API_BASE}/"
            f"{phone_number_id}/messages"
        )

        image_payload: Dict[str, Any] = {
            "link": image_url,
        }

        if caption:
            image_payload["caption"] = caption[:1024]

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": image_payload,
        }

        return await self._send(
            url=url,
            access_token=access_token,
            payload=payload,
        )

    async def send_buttons(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        body_text: str,
        buttons: List[Dict[str, str]],
    ) -> WhatsAppSendResult:

        self._validate_credentials(
            phone_number_id,
            access_token,
            to,
        )

        if not body_text:
            raise ValueError(
                "body_text is required"
            )

        if not buttons:
            raise ValueError(
                "at least one button is required"
            )

        if len(buttons) > 3:
            raise ValueError(
                "WhatsApp reply buttons support a maximum of 3 buttons"
            )

        formatted_buttons = []

        for button in buttons:
            button_id = (
                button.get("id")
                or button.get("title")
            )

            title = button.get("title")

            if not title:
                raise ValueError(
                    "button title is required"
                )

            formatted_buttons.append(
                {
                    "type": "reply",
                    "reply": {
                        "id": button_id,
                        "title": title[:20],
                    },
                }
            )

        url = (
            f"{self.GRAPH_API_BASE}/"
            f"{phone_number_id}/messages"
        )

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": body_text[:1024],
                },
                "action": {
                    "buttons": formatted_buttons,
                },
            },
        }

        return await self._send(
            url=url,
            access_token=access_token,
            payload=payload,
        )

    async def send_list(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        body_text: str,
        button_text: str,
        rows: List[Dict[str, str]],
        section_title: Optional[str] = None,
    ) -> WhatsAppSendResult:

        self._validate_credentials(
            phone_number_id,
            access_token,
            to,
        )

        if not body_text:
            raise ValueError(
                "body_text is required"
            )

        if not rows:
            raise ValueError(
                "at least one row is required"
            )

        formatted_rows = []

        for row in rows:
            row_id = (
                row.get("id")
                or row.get("title")
            )

            title = row.get("title")

            if not title:
                raise ValueError(
                    "row title is required"
                )

            item: Dict[str, Any] = {
                "id": row_id,
                "title": title[:24],
            }

            description = row.get("description")

            if description:
                item["description"] = description[:72]

            formatted_rows.append(item)

        section: Dict[str, Any] = {
            "rows": formatted_rows,
        }

        if section_title:
            section["title"] = section_title[:24]

        url = (
            f"{self.GRAPH_API_BASE}/"
            f"{phone_number_id}/messages"
        )

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {
                    "text": body_text[:1024],
                },
                "action": {
                    "button": button_text[:20],
                    "sections": [section],
                },
            },
        }

        return await self._send(
            url=url,
            access_token=access_token,
            payload=payload,
        )

    async def send_bot_response(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        response: BotResponse,
    ) -> WhatsAppSendResult:

        if not response.text and not response.products:
            return WhatsAppSendResult(
                success=True
            )

        message_ids: List[str] = []

        try:
            if (
                response.response_type
                in {"product_list", "product_card"}
                and response.products
            ):
                catalog_id = str(
                    response.metadata.get("whatsapp_catalog_id") or ""
                ).strip()

                catalog_products = [
                    {
                        "product_retailer_id": (
                            product.whatsapp_retailer_id
                            or product.product_id
                        )
                    }
                    for product in response.products[:3]
                    if (
                        product.whatsapp_retailer_id
                        or product.product_id
                    )
                ]

                # A real Commerce message is used only when the tenant has
                # configured a Meta catalog. Otherwise retain the image/text
                # fallback so a product is still delivered.
                if catalog_id and catalog_products:
                    if len(catalog_products) == 1:
                        product = response.products[0]
                        result = await self.send_catalog_product(
                            phone_number_id=phone_number_id,
                            access_token=access_token,
                            to=to,
                            catalog_id=catalog_id,
                            product_retailer_id=(
                                product.whatsapp_retailer_id
                                or product.product_id
                            ),
                            body_text=response.text,
                        )
                    else:
                        result = await self.send_catalog_product_list(
                            phone_number_id=phone_number_id,
                            access_token=access_token,
                            to=to,
                            catalog_id=catalog_id,
                            products=catalog_products,
                            body_text=(
                                response.text
                                or "Here are the products I found:"
                            ),
                        )

                    if not result.success:
                        raise RuntimeError(
                            result.error_message
                            or "WhatsApp catalog message delivery failed."
                        )

                    if result.provider_message_id:
                        message_ids.append(result.provider_message_id)
                else:
                    for product in response.products[:3]:
                        caption = self._build_product_caption(product)
                        if product.image:
                            result = await self.send_image(
                                phone_number_id=phone_number_id,
                                access_token=access_token,
                                to=to,
                                image_url=product.image,
                                caption=caption,
                            )
                        else:
                            result = await self.send_text(
                                phone_number_id=phone_number_id,
                                access_token=access_token,
                                to=to,
                                text=caption,
                            )

                        if not result.success:
                            raise RuntimeError(
                                result.error_message
                                or "WhatsApp message delivery failed."
                            )

                        if result.provider_message_id:
                            message_ids.append(result.provider_message_id)

                if response.quick_replies:
                    buttons = [
                        {
                            "id": (reply.get("value") or reply["label"]),
                            "title": reply["label"],
                        }
                        for reply in response.quick_replies[:3]
                    ]

                    result = await self.send_buttons(
                        phone_number_id=phone_number_id,
                        access_token=access_token,
                        to=to,
                        body_text=(response.text or "What would you like to do?"),
                        buttons=buttons,
                    )

                    if not result.success:
                        raise RuntimeError(
                            result.error_message
                            or "WhatsApp quick reply delivery failed."
                        )

                    if result.provider_message_id:
                        message_ids.append(result.provider_message_id)

            elif response.quick_replies:
                buttons = [
                    {
                        "id": (
                            reply.get("value")
                            or reply["label"]
                        ),
                        "title": reply["label"],
                    }
                    for reply in response.quick_replies[:3]
                ]

                result = await self.send_buttons(
                    phone_number_id=phone_number_id,
                    access_token=access_token,
                    to=to,
                    body_text=(
                        response.text
                        or "Choose an option."
                    ),
                    buttons=buttons,
                )

                if not result.success:
                    raise RuntimeError(
                        result.error_message
                        or "WhatsApp quick reply delivery failed."
                    )

                if result.provider_message_id:
                    message_ids.append(
                        result.provider_message_id
                    )

            else:
                result = await self.send_text(
                    phone_number_id=phone_number_id,
                    access_token=access_token,
                    to=to,
                    text=response.text or "",
                )

                if not result.success:
                    raise RuntimeError(
                        result.error_message
                        or "WhatsApp message delivery failed."
                    )

                if result.provider_message_id:
                    message_ids.append(
                        result.provider_message_id
                    )

            return WhatsAppSendResult(
                success=True,
                provider_message_id=(
                    message_ids[-1]
                    if message_ids
                    else None
                ),
                provider_message_ids=message_ids,
            )

        except Exception as exc:
            logger.exception(
                "WhatsApp response delivery failed: %s",
                exc,
            )

            return WhatsAppSendResult(
                success=False,
                provider_message_id=(
                    message_ids[-1]
                    if message_ids
                    else None
                ),
                provider_message_ids=message_ids,
                error_message=str(exc),
            )

    @staticmethod
    def _build_product_caption(
        product: ResponseProduct,
    ) -> str:

        lines = [
            product.name,
        ]

        if product.product_type:
            lines.append(
                f"Type: {product.product_type}"
            )

        if (
            product.category
            and product.category
            != product.product_type
        ):
            lines.append(
                f"Category: {product.category}"
            )

        lines.append(
            f"Price: ₹{product.price:,.0f}"
        )

        lines.append(
            f"Stock: {product.stock}"
        )

        if product.colors_available:
            lines.append(
                "Colors: "
                + ", ".join(
                    product.colors_available
                )
            )

        if product.sizes_available:
            lines.append(
                "Sizes: "
                + ", ".join(
                    product.sizes_available
                )
            )

        if product.description:
            lines.append(
                product.description[:200]
            )

        return "\n".join(lines)

    async def _send(
        self,
        url: str,
        access_token: str,
        payload: Dict[str, Any],
    ) -> WhatsAppSendResult:

        client = self._get_client()

        try:
            response = await client.post(
                url,
                headers=self._build_headers(
                    access_token
                ),
                json=payload,
            )

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                error_code = None
                error_message = str(exc)

                try:
                    error_data = response.json()
                    error = error_data.get(
                        "error",
                        {},
                    )

                    if isinstance(error, dict):
                        if error.get("code") is not None:
                            error_code = str(
                                error["code"]
                            )

                        error_message = (
                            error.get("message")
                            or error_message
                        )
                except Exception:
                    pass

                raise RuntimeError(
                    "WhatsApp API error"
                    + (
                        f" [{error_code}]"
                        if error_code
                        else ""
                    )
                    + f": {error_message}"
                ) from exc

            data = response.json()

            message_id = self._extract_message_id(
                data
            )

            if not message_id:
                raise RuntimeError(
                    "WhatsApp API returned HTTP success "
                    "but no WhatsApp message ID."
                )

            return WhatsAppSendResult(
                success=True,
                provider_message_id=message_id,
                raw_response=data,
            )

        except httpx.HTTPStatusError as exc:
            logger.error(
                "WhatsApp API request failed: status=%s",
                exc.response.status_code,
            )
            raise

        except httpx.RequestError as exc:
            logger.error(
                "WhatsApp request failed: %s",
                exc,
            )
            raise


whatsapp_sender = WhatsAppSender()
