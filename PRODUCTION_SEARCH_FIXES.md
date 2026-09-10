# Meridin production search fixes

This build addresses the connected WhatsApp catalogue-search/state problems identified during review.

## Changed files

- `app/ml/intent_classifier.py`
  - Added deterministic `Hei` greeting handling.
  - Added a deterministic product-search boundary for explicit requests such as `show some trousers`, preventing low-confidence ML predictions from routing the request incorrectly.

- `app/services/catalog_metadata_service.py`
  - Added alias-aware canonical-category to metadata-key resolution.
  - `pants`, `pant`, `trouser`, and `trousers` can resolve to department-specific category IDs.
  - Category aliases are retained for legacy textual product documents.
  - Size-group resolution uses the resolved category/ID relationship.

- `app/models/schemas.py`
  - Added `category_text_values` to `ProductSearchFilters` for safe legacy textual-category fallback.

- `app/repositories/product_repository.py`
  - Category filtering now supports canonical IDs and legacy textual category fields.
  - Text fallback is restricted to documents without a usable category ID, so a conflicting stored ID is not silently overridden.
  - Department ID/text compatibility is retained for migration-era documents.

- `app/services/product_service.py`
  - Entity-to-filter conversion now selects the highest-confidence entity of each type instead of depending on extractor ordering.

- `app/conversation/context.py`
  - Removed the duplicate global product-filter merge. ProductSearchHandler now owns the decision between a new search and a follow-up.

- `app/conversation/session.py`
  - Removed duplicate product-search state merging for the same reason.

- `app/routing/intent_router.py`
  - Greetings clear stale pending entity/search state.
  - A clearly new product search interrupts an old pending requirement.
  - Unrelated high-level intents no longer remain trapped in an old pending requirement.
  - Deterministic catalogue handler failures return a safe non-invented catalogue error instead of falling through to AI-generated product facts.

- `app/handlers/product_availability.py`
  - Availability catalogue searches now reuse attribute-only follow-up filters consistently and run through the same metadata normalization path as product search.

- `app/handlers/fallback.py`
  - Generic AI fallback is blocked for product/availability/catalogue intents so catalogue facts cannot be fabricated by the fallback LLM.

- `tests/test_catalog_search_regressions.py`
  - Regression coverage for trousers/pants alias resolution, numeric trouser sizes, high-confidence entity selection, and multi-attribute filter merging.

## Expected flows

`Show some trousers` -> product_search -> canonical `pants` -> correct department-specific category ID.

`Do you have black shirt` -> `2XL` -> previous category/color are preserved and size is added.

`black shirt` -> bot asks for size -> `Hello` -> pending state is cleared and greeting is handled normally.

`Show me shirts` -> `Show me trousers` -> second message starts a fresh search.

If deterministic catalogue processing fails, the system does not invent product names, prices, stock, colors, or sizes.

## Verification

Python bytecode compilation passed for `app` and `tests` in the build environment. Full pytest execution could not be completed because the execution environment did not have the repository's MongoDB dependency (`pymongo`/`bson`) installed and package installation was unavailable. A targeted metadata regression script was executed successfully.
