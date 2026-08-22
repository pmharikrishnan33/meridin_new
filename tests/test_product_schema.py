from app.models.schemas import Product, ProductSearchFilters


def test_product_schema():

    product = Product(
        _id="product_001",
        tenant_id="tenant_001",
        title="Black Cotton Shirt",
        description="Premium shirt",
        category="shirt",
        type="casual",
        brand="Example",
        material="cotton",
        fit="regular",
        gender="men",
        color=["black"],
        size=["M", "L"],
        price=1299,
        stock=10,
    )

    assert product.id == "product_001"
    assert product.title == "Black Cotton Shirt"
    assert product.brand == "Example"
    assert product.material == "cotton"


def test_search_filters():

    filters = ProductSearchFilters(
        query="shirt",
        category="shirt",
        brand="nike",
        material="cotton",
        color="black",
        size="M",
        max_price=1500,
    )

    assert filters.query == "shirt"
    assert filters.brand == "nike"
    assert filters.material == "cotton"
    assert filters.max_price == 1500