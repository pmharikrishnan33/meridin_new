# Meridin production search/state fixes

This build addresses the connected catalogue-search issues:

- deterministic routing for explicit clothing search phrases such as `show some trousers`;
- category aliases resolve to department-specific metadata IDs (`trousers` can resolve to men's `trousers` rather than requiring a `pants` key);
- legacy textual product fields remain searchable alongside canonical numeric IDs;
- category/color/size filters are preserved while a required attribute is collected across turns;
- a new category/product search interrupts an old pending clarification;
- greetings interrupt stale pending clarification/search state;
- availability catalogue searches reuse the same normalized conversational filters;
- catalogue/product and availability handler errors do not fall through to AI-generated catalogue facts;
- generic AI fallback is blocked when commerce entities are present so an LLM cannot invent catalogue products/prices.

## Critical conversation tests

1. `Show me shirts` -> color question -> `black` -> size question -> `2XL` -> search uses shirts + black + 2XL.
2. `Show some trousers` -> searches the correct trousers category.
3. `Show me shirts` -> `Show me trousers` -> second message is a new search.
4. `Show me shirts` -> color question -> `Hi` -> greeting response; stale pending state is cleared.
5. `Show me black trousers` -> `32` -> preserves category + color and applies size.

## Validation

Python compilation and the source-level regression suite pass in the build environment. Full MongoDB/WhatsApp integration tests require the project's production dependencies and services.
