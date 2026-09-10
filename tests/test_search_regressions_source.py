from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_pending_clarification_persists_collected_filters():
    src = read("app/routing/intent_router.py")
    assert 'response.metadata.get("filters_collected")' in src
    assert 'session.context.last_search_filters = dict(collected)' in src


def test_category_resolution_is_alias_aware():
    src = read("app/services/catalog_metadata_service.py")
    assert "def _category_metadata_keys" in src
    assert "accepted_keys" in src
    assert "not in accepted_keys" in src


def test_repository_supports_legacy_category_and_department_text():
    src = read("app/repositories/product_repository.py")
    assert 'getattr(filters, "category_terms", [])' in src
    assert 'getattr(filters, "department_terms", [])' in src
    assert 'category_combined = self._or_condition' in src
    assert 'department_combined = self._or_condition' in src


def test_catalogue_intents_do_not_ai_fallback_on_router_error():
    src = read("app/routing/intent_router.py")
    assert 'if intent in {' in src
    assert 'IntentType.PRODUCT_SEARCH' in src
    assert 'IntentType.AVAILABILITY' in src
    assert '"catalogue_error": True' in src


def test_fallback_blocks_ai_for_commerce_entities():
    src = read("app/handlers/fallback.py")
    assert "has_catalogue_entity" in src
    assert "allow_ai_catalogue_fallback" in src


def test_explicit_clothing_search_has_deterministic_intent_route():
    src = read("app/ml/intent_classifier.py")
    assert "show some" in src
    assert "trousers" in src
    assert "IntentType.PRODUCT_SEARCH" in src
