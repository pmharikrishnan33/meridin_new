import pytest
from unittest.mock import AsyncMock

from app.models.schemas import Product
from app.services.product_service import ProductService


@pytest.mark.asyncio
async def test_get_product_by_id():

    repository = AsyncMock()

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

    repository.find_by_id.return_value = product

    service = ProductService(repository)

    result = await service.get_product_by_id(
        tenant_id="tenant_001",
        product_id="product_001",
    )

    assert result == product

    repository.find_by_id.assert_awaited_once_with(
        tenant_id="tenant_001",
        product_id="product_001",
    )


@pytest.mark.asyncio
async def test_get_product_by_reference_uses_title_fallback():

    repository = AsyncMock()

    product = Product(
        _id="product_001",
        tenant_id="tenant_001",
        title="Black Shirt",
        category="shirt",
        color=["black"],
        size=["M"],
        price=999,
        stock=10,
    )

    repository.find_by_id.return_value = None
    repository.find_by_title.return_value = product

    service = ProductService(repository)

    result = await service.get_product_by_reference(
        tenant_id="tenant_001",
        reference="Black Shirt",
    )

    assert result == product

    repository.find_by_title.assert_awaited_once_with(
        tenant_id="tenant_001",
        title="Black Shirt",
    )