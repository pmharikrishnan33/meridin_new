"""
Zero-result fallback handler.

When a product search returns no results, this module implements a 5-step
progressive relaxation strategy:

1. **Understand** — the user message has already been parsed into entities
   by the time we get here.
2. **Search** — run the DB query with all extracted filters.
3. **Relax** — systematically remove each filter (one at a time) and
   re-search, finding which removal yields the most results.
4. **Select closest** — pick the top 3 from the best relaxed search.
5. **Build response** — return the closest products with a helpful message.
"""

from typing import Dict, Any, List, Optional

from app.ai.openrouter import openrouter_client
from app.models.schemas import MessageUnderstanding
from app.utils.logger import logger


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_which_to_remove_prompt(
    query: str,
    filters: Dict[str, Any],
    removal_results: Dict[str, int],
) -> List[Dict[str, str]]:
    """
    Build a prompt that asks the LLM which relaxation gave the best
    balance of relevance and result count.
    """
    system = (
        "You are a search assistant. A product search returned zero results. "
        "We tried removing one filter at a time and got the following result counts. "
        "Pick the filter removal that is most likely to give the user what they want, "
        "balancing high result count with relevance. "
        "Respond with ONLY: {\"remove\": \"<filter_key>\"}"
    )

    removal_str = ", ".join(f"{k}={v}" for k, v in removal_results.items())
    user = (
        f"Original query: {query}\n"
        f"Original filters: {filters}\n"
        f"Result counts after removing each filter: {removal_str}\n\n"
        f"Which filter removal would you recommend?"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def find_best_relaxation(
    query: str,
    filters: Dict[str, Any],
    search_fn,  # callable: async (filters: Dict) -> List (product IDs or items)
) -> Optional[str]:
    """
    Step 3 of the zero-result fallback.

    For each filter key in ``filters``, remove it and call ``search_fn``
    with the relaxed filter set.  Return the key whose removal yielded the
    most results (ties broken by LLM suggestion).

    Args:
        query: The original user query string.
        filters: The entity-derived filter dict (e.g. ``{"color": "red", "size": "m"}``).
        search_fn: An async callable that takes a filter dict and returns
            a list of product IDs (or items).

    Returns:
        The filter key that should be removed, or ``None`` if none of the
        permitted relaxations yielded results.
    """
    relaxable_keys = [
        key for key in filters
        if key in {"color", "size", "type", "min_price", "max_price", "fit", "brand"}
    ]
    if not relaxable_keys:
        return None

    results_per_removal: Dict[str, int] = {}
    results_per_key: Dict[str, List] = {}

    for key in relaxable_keys:
        relaxed = {k: v for k, v in filters.items() if k != key}
        try:
            found = await search_fn(relaxed)
            results_per_removal[key] = len(found)
            results_per_key[key] = found
            logger.debug(f"Relax [{key}]: {len(found)} results")
        except Exception as exc:
            logger.warning(f"Relaxation search for key={key} failed: {exc}")
            results_per_removal[key] = 0
            results_per_key[key] = []

    # Find the best by count
    best_key_by_count = max(results_per_removal, key=results_per_removal.get)
    best_count = results_per_removal[best_key_by_count]

    if best_count == 0:
        return None

    # If there's a tie, let the LLM decide
    tied = [k for k, v in results_per_removal.items() if v == best_count]
    if len(tied) > 1 and openrouter_client.is_configured:
        try:
            messages = _build_which_to_remove_prompt(query, filters, results_per_removal)
            raw = await openrouter_client.chat(messages, temperature=0.3, max_tokens=200)
            import json
            data = json.loads(raw.strip())
            chosen = data.get("remove")
            if chosen and chosen in tied:
                best_key_by_count = chosen
        except Exception as exc:
            logger.debug(f"LLM tie-break failed, using first: {exc}")

    return best_key_by_count


def build_relaxation_message(
    query: str,
    filters: Dict[str, Any],
    removed_key: str,
    removed_value: Any,
) -> str:
    """
    Step 5 (message) — generate a human-friendly explanation of what
    filters were relaxed.
    """
    display_names = {
        "color": "color",
        "size": "size",
        "category": "category",
        "brand": "brand",
        "type": "type",
        "min_price": "minimum price",
        "max_price": "maximum price",
        "material": "material",
        "fit": "fit",
        "gender": "gender",
    }
    label = display_names.get(removed_key, removed_key)
    return (
        f"I couldn't find anything matching \"{query}\" exactly, "
        f"but I looked more broadly by dropping the {label} filter."
    )


def extract_entity_filters(understanding: MessageUnderstanding) -> Dict[str, Any]:
    """
    Convert the extracted entities from a ``MessageUnderstanding`` into a
    flat filter dict suitable for progressive relaxation.
    """
    filters: Dict[str, Any] = {}
    for entity in understanding.entities:
        key = entity.entity_type.value
        if key not in filters:  # keep first occurrence (highest confidence)
            filters[key] = entity.normalized_value or entity.value
    return filters
