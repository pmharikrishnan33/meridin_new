"""
Response model helpers and factory functions.

Provides convenience functions for building structured
:class:`~app.models.schemas.BotResponse` objects used throughout
the intent handlers and services.
"""

from typing import Any, Dict, List, Optional

from app.models.schemas import (
    BotResponse,
    ResponseProduct,
    Product,
    ExtractedEntity,
)


def text_response(
    text: str,
    quick_replies: Optional[List[Dict[str, str]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> BotResponse:
    """Build a simple text bot response."""
    return BotResponse(
        response_type="text",
        text=text,
        quick_replies=quick_replies or [],
        metadata=metadata or {},
    )


def product_list_response(
    products: List[ResponseProduct],
    intro_text: Optional[str] = None,
    quick_replies: Optional[List[Dict[str, str]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> BotResponse:
    """Build a product list bot response."""
    meta = metadata or {}
    meta["products_count"] = len(products)
    return BotResponse(
        response_type="product_list",
        text=intro_text or f"I found {len(products)} items for you:",
        products=products,
        quick_replies=quick_replies or [],
        metadata=meta,
    )


def product_card_response(
    product: ResponseProduct,
    details: Optional[str] = None,
    quick_replies: Optional[List[Dict[str, str]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> BotResponse:
    """Build a product card bot response."""
    return BotResponse(
        response_type="product_card",
        text=details or product.name,
        products=[product],
        quick_replies=quick_replies or [],
        metadata=metadata or {},
    )


def order_status_response(
    order_number: str,
    status: str,
    total: float,
    carrier: Optional[str] = None,
    tracking_number: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    quick_replies: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Format an order status message as a plain-text string.

    Returns the formatted text (not a BotResponse) so callers can
    embed it in a larger response.
    """
    lines = [
        f"📦 Order #{order_number}",
        f"Status: {status}",
        f"Total: ₹{total:,.2f}",
    ]
    if carrier:
        lines.append(f"Carrier: {carrier}")
    if tracking_number:
        lines.append(f"Tracking: {tracking_number}")
    if items:
        lines.append("")
        lines.append("Items:")
        for item in items:
            lines.append(f"  • {item['name']} x{item['quantity']}")
    return "\n".join(lines)


def clarification_response(
    missing_entities: List[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> BotResponse:
    """Build a clarification request response for missing entities."""
    entity_names = {
        "product": "which product",
        "color": "which color",
        "size": "which size",
        "fit": "which fit",
        "price": "what price range",
        "order_id": "your order ID",
    }
    questions = []
    for entity in missing_entities:
        name = entity_names.get(entity, entity)
        questions.append(f"Could you please specify {name}?")

    meta = metadata or {}
    meta["needs_clarification"] = True
    meta["missing_entities"] = missing_entities

    return BotResponse(
        response_type="text",
        text=" ".join(questions),
        metadata=meta,
    )


def entities_to_dict(entities: List[ExtractedEntity]) -> Dict[str, str]:
    """
    Convert a list of ExtractedEntity objects into a simple
    ``{entity_type: value}`` dict for quick lookup.
    """
    result: Dict[str, str] = {}
    for entity in entities:
        key = entity.entity_type.value
        if key not in result:
            result[key] = entity.normalized_value or entity.value
    return result


def product_to_response_product(
    product: Product,
) -> ResponseProduct:
    image = (
        product.media[0]
        if product.media
        else None
    )

    if not image:
        for variant in product.variants:
            if not isinstance(variant, dict):
                continue

            images = variant.get("images") or variant.get("media") or []

            if images:
                image = str(images[0])
                break

    return ResponseProduct(
        product_id=product.id,
        name=product.title,
        price=product.price,
        sale_price=None,
        currency="INR",
        image=image,
        stock=product.stock,
        sizes_available=sorted(
            set(product.size)
        ),
        colors_available=sorted(
            set(product.color)
        ),
        in_stock=product.stock > 0,
    )