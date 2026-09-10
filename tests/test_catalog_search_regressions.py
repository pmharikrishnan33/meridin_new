from app.models.schemas import EntityType, ExtractedEntity, ProductSearchFilters
from app.services.catalog_metadata_service import CatalogMetadataService
from app.services.product_service import ProductService


def metadata():
    return {
        "category_aliases": {"pants": ["pant", "trouser", "trousers"], "shirts": ["shirt"]},
        "department_ids": {"women": 100, "men": 200, "boys": 400},
        "category_ids": {
            "women": {"pants": 110, "shirts": 103},
            "men": {"trousers": 207, "shirts": 201},
            "boys": {"trousers": 405},
        },
        "category_size_map": {
            "pants": "numeric_pants", "pant": "numeric_pants",
            "trouser": "numeric_pants", "trousers": "numeric_pants",
        },
        "size_groups": {"numeric_pants": {"30": 1, "32": 2, "34": 3, "36": 4}},
    }


def test_trousers_alias_resolves_all_matching_category_ids():
    ids = CatalogMetadataService._get_matching_category_ids(metadata(), "pants")
    assert ids == [110, 207, 405]


def test_trousers_alias_contains_legacy_metadata_key():
    keys = CatalogMetadataService._category_metadata_keys(metadata(), "pants")
    assert "pants" in keys
    assert "trousers" in keys
    assert "trouser" in keys


def test_numeric_pants_size_32_resolves():
    normalized, size_id = CatalogMetadataService._resolve_size_id(metadata(), "pants", "32")
    assert normalized == "32"
    assert size_id == 2


def test_entity_to_filter_uses_highest_confidence_category():
    service = ProductService()
    entities = [
        ExtractedEntity(entity_type=EntityType.CATEGORY, value="shirt", normalized_value="shirt", confidence=0.30),
        ExtractedEntity(entity_type=EntityType.CATEGORY, value="trousers", normalized_value="trousers", confidence=0.85),
        ExtractedEntity(entity_type=EntityType.COLOR, value="black", normalized_value="black", confidence=0.85),
        ExtractedEntity(entity_type=EntityType.SIZE, value="2xl", normalized_value="2XL", confidence=0.85),
    ]
    filters = service.entities_to_filters(entities)
    assert filters.category == "trousers"
    assert filters.color == "black"
    assert filters.size == "2XL"


def test_multi_attribute_filters_can_be_merged():
    filters = ProductSearchFilters(category="shirts", color="black")
    followup = ProductSearchFilters(size="2XL")
    merged = {**filters.model_dump(exclude_none=True), **followup.model_dump(exclude_none=True)}
    assert merged["category"] == "shirts"
    assert merged["color"] == "black"
    assert merged["size"] == "2XL"
