import pytest

from app.models.schemas import ProductSearchFilters


def test_search_filter_contract():

    filters = ProductSearchFilters(
        query="shirt",
        category="shirt",
        brand="nike",
        material="cotton",
        fit="slim",
        gender="men",
        color="black",
        size="M",
        min_price=500,
        max_price=1500,
        in_stock_only=True,
    )

    assert filters.brand == "nike"
    assert filters.material == "cotton"
    assert filters.fit == "slim"
    assert filters.gender == "men"
    assert filters.color == "black"
    assert filters.size == "M"