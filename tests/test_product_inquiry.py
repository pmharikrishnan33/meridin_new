import pytest
from unittest.mock import AsyncMock, patch

from app.handlers.product_inquiry import ProductInquiryHandler
from app.models.schemas import (
    EntityType,
    ExtractedEntity,
    IntentType,
    MessageUnderstanding,
    Product,
    ResponseProduct,
)


@pytest.mark.asyncio
async def test_product_inquiry_uses_title_not_name():

    product = Product(
        _id="product_001",
        tenant_id="tenant_001",
        title="Black Shirt",
        description="Cotton shirt",
        category="shirt",
        color=["black"],
        size=["M", "L"],
        price=999,
        stock=10,
    )

    understanding = MessageUnderstanding(
        original_text="tell me about black shirt",
        normalized_text="tell me about black shirt",
        intent=IntentType.PRODUCT_INQUIRY,
        intent_confidence=0.95,
        entities=[
            ExtractedEntity(
                entity_type=EntityType.PRODUCT,
                value="Black Shirt",
                normalized_value="Black Shirt",
                confidence=0.95,
            )
        ],
    )

    with patch(
        "app.handlers.product_inquiry.product_service"
    ) as service:

        service.get_product_by_reference = (
            AsyncMock(
                return_value=product
            )
        )

        service.product_to_response.return_value = ResponseProduct(
            product_id="product_001",
            name="Black Shirt",
            price=999.0,
            stock=10,
        )

        handler = ProductInquiryHandler()

        response = await handler.handle(
            understanding=understanding,
            tenant_id="tenant_001",
            tenant_settings={},
            conversation_context=None,
        )

    assert response.metadata["product_name"] == (
        "Black Shirt"
    )