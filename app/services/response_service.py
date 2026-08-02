"""
Response service - builds structured bot responses from intent handler output.

This service acts as a bridge between the intent handlers (which produce
:class:`~app.models.schemas.BotResponse` objects) and the various output
channels (WhatsApp, local chat, etc.).  It handles:

- Response text formatting (currency, truncation, language)
- Quick-reply button construction
- Template selection for WhatsApp template messages
- Fallback response generation
"""

from typing import Dict, Any, Optional, List

from app.models.schemas import BotResponse, ResponseProduct, MessageUnderstanding
from app.utils.logger import logger


class ResponseService:
    """
    Builds and formats bot responses for different output channels.
    """

    MAX_TEXT_LENGTH = 1000  # WhatsApp text message limit

    def format_response(
        self,
        response: BotResponse,
        tenant_settings: Optional[Dict[str, Any]] = None,
    ) -> BotResponse:
        """
        Apply final formatting to a bot response.

        - Truncates text that exceeds the max length.
        - Ensures quick-replies have the required ``id`` field.
        """
        settings = tenant_settings or {}
        currency = settings.get("currency", "INR")

        # Truncate text if needed
        if response.text and len(response.text) > self.MAX_TEXT_LENGTH:
            response.text = response.text[: self.MAX_TEXT_LENGTH - 3] + "..."
            logger.warning(
                f"Response text truncated to {self.MAX_TEXT_LENGTH} characters."
            )

        # Ensure quick-replies have ids
        for reply in response.quick_replies:
            if "id" not in reply:
                reply["id"] = reply.get("value", reply.get("label", ""))

        return response

    def build_text_response(
        self,
        text: str,
        quick_replies: Optional[List[Dict[str, str]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BotResponse:
        """
        Convenience method to build a simple text BotResponse.
        """
        return BotResponse(
            response_type="text",
            text=text,
            quick_replies=quick_replies or [],
            metadata=metadata or {},
        )

    def build_product_list_response(
        self,
        products: List[ResponseProduct],
        intro_text: Optional[str] = None,
        quick_replies: Optional[List[Dict[str, str]]] = None,
    ) -> BotResponse:
        """
        Build a product list response from ResponseProduct objects.
        """
        return BotResponse(
            response_type="product_list",
            text=intro_text or f"I found {len(products)} items for you:",
            products=products,
            quick_replies=quick_replies or [],
            metadata={"products_count": len(products)},
        )

    def select_template(
        self,
        response: BotResponse,
        understanding: Optional[MessageUnderstanding] = None,
    ) -> Optional[str]:
        """
        Select an appropriate WhatsApp template name for the response.

        Returns the template name or ``None`` if no template is needed.
        """
        intent = understanding.intent if understanding else None

        template_map = {
            "greeting": "greeting",
            "order_status": "order_status",
            "availability": "product_available",
        }

        if response.response_type == "text":
            return None

        if intent and intent.value in template_map:
            return template_map[intent.value]

        return None

    def get_template_params(
        self,
        response: BotResponse,
        understanding: Optional[MessageUnderstanding] = None,
    ) -> List[str]:
        """
        Extract template parameters from the response for WhatsApp
        template message submission.
        """
        params: List[str] = []

        if response.text:
            params.append(response.text)

        for product in response.products[:1]:
            params.append(product.name)
            params.append(str(product.price))

        return params

    def build_fallback(
        self,
        fallback_message: str = "I didn't understand that. Could you please rephrase?",
        quick_replies: Optional[List[Dict[str, str]]] = None,
    ) -> BotResponse:
        """
        Build a standard fallback response.
        """
        return BotResponse(
            response_type="text",
            text=fallback_message,
            quick_replies=quick_replies or [
                {"label": "Browse Products", "value": "browse_products"},
                {"label": "Track Order", "value": "track_order"},
                {"label": "Contact Support", "value": "contact_support"},
            ],
            metadata={"fallback": True},
        )


response_service = ResponseService()
