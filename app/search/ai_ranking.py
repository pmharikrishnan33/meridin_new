"""
AI-powered search result ranking.

Uses the OpenRouter LLM to rank products by relevance to the user's
query.  When the LLM is unavailable or fails, a lightweight heuristic
based on text-score, recency, and stock level is used instead.
"""

from typing import List, Optional, Dict, Any

from app.ai.openrouter import openrouter_client
from app.models.inventory import ClothingItem, RankedClothingItem
from app.utils.logger import logger


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_ranking_prompt(query: str, products: List[ClothingItem]) -> List[Dict[str, str]]:
    """
    Build the LLM prompt that asks the model to rank products by relevance.
    """
    product_lines = []
    for i, p in enumerate(products):
        product_lines.append(
            f"[{i}] id={p.id} | title={p.title} | "
            f"desc={p.description or 'N/A'} | category={p.category or 'N/A'} | "
            f"type={p.type or 'N/A'}"
        )

    system = (
        "You are a product search ranking assistant. "
        "Given a user query and a list of product candidates, "
        "rank them from most to least relevant. "
        "Return a JSON array of indices (e.g. [2, 0, 1]) sorted by relevance, "
        "most relevant first. Only include each index once."
    )

    user = (
        f"User query: {query}\n\n"
        f"Products:\n" + "\n".join(product_lines) + "\n\n"
        f"Rank the product indices from most to least relevant:"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _build_relaxation_prompt(query: str, filters: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Build a prompt that asks the LLM which single filter to remove
    to get the best relaxation of the query.
    """
    system = (
        "You are a search assistant helping relax overly-specific queries. "
        "Given a user query and the filters extracted from it, "
        "suggest which ONE filter, if removed, is most likely to yield results. "
        "Respond with ONLY a JSON object: {\"remove\": \"<filter_key>\"}. "
        "If removing any single filter is unlikely to help, respond with {\"remove\": null}."
    )

    user = (
        f"Query: {query}\n"
        f"Filters: {filters}\n\n"
        f"Which single filter should be removed to find similar products?"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _build_narrowing_prompt(query: str, result_count: int, filters: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Build a prompt that asks the LLM to generate narrowing questions.
    """
    system = (
        "You are a shopping assistant. The user searched for products but got too many results. "
        "Generate 2-3 natural follow-up questions that would help narrow the search. "
        "Suggest refinements like brand, material, price range, size, or color. "
        "Respond with ONLY a JSON array of question strings."
    )

    user = (
        f"User query: {query}\n"
        f"Result count: {result_count}\n"
        f"Current filters: {filters}\n\n"
        f"Generate narrowing questions:"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def rank_products(
    query: str,
    products: List[ClothingItem],
    color_names: Optional[List[str]] = None,
    size_names: Optional[List[str]] = None,
    prices: Optional[List[float]] = None,
    stocks: Optional[List[int]] = None,
) -> List[RankedClothingItem]:
    """
    Rank products by relevance to ``query`` using the OpenRouter LLM.

    Falls back to a text-match heuristic when the LLM is unavailable.

    Args:
        query: The user's search query.
        products: Candidate products (already filtered to tenant / criteria).
        color_names: Optional parallel list of resolved color names.
        size_names: Optional parallel list of resolved size names.
        prices: Optional parallel list of prices.
        stocks: Optional parallel list of stock counts.

    Returns:
        A list of ``RankedClothingItem`` sorted by descending score.
    """
    if not products:
        return []

    # --- Try LLM ranking -------------------------------------------------
    if openrouter_client.is_configured:
        try:
            messages = _build_ranking_prompt(query, products)
            raw = await openrouter_client.chat(messages, temperature=0.3, max_tokens=500)
            ranked_indices = _parse_ranking_indices(raw, len(products))
            if ranked_indices is not None:
                logger.info(f"AI ranking returned order: {ranked_indices}")
                return _order_ranked_items(
                    products, ranked_indices,
                    color_names, size_names, prices, stocks,
                )
        except Exception as exc:
            logger.warning(f"AI ranking failed, falling back to heuristic: {exc}")

    # --- Heuristic fallback ----------------------------------------------
    return _heuristic_rank(
        query, products,
        color_names, size_names, prices, stocks,
    )


def _parse_ranking_indices(raw: str, count: int) -> Optional[List[int]]:
    """
    Parse the LLM's response into a list of integer indices.

    Accepts JSON arrays like ``[2, 0, 1]`` or plain text ``2 0 1``.
    Returns ``None`` if parsing fails.
    """
    import json

    raw = raw.strip()

    # Try JSON parse first
    try:
        indices = json.loads(raw)
        if isinstance(indices, list) and all(isinstance(i, int) for i in indices):
            if len(indices) == count and set(indices) == set(range(count)):
                return indices
    except (json.JSONDecodeError, ValueError):
        pass

    # Try extracting numbers from text
    import re
    numbers = re.findall(r"\d+", raw)
    indices = [int(n) for n in numbers]
    if len(indices) == count and set(indices) == set(range(count)):
        return indices

    return None


def _order_ranked_items(
    products: List[ClothingItem],
    indices: List[int],
    color_names: Optional[List[str]] = None,
    size_names: Optional[List[str]] = None,
    prices: Optional[List[float]] = None,
    stocks: Optional[List[int]] = None,
) -> List[RankedClothingItem]:
    """
    Build ``RankedClothingItem`` list ordered by the LLM-provided indices.
    """
    ranked = []
    count = len(products)
    for rank, idx in enumerate(indices):
        product = products[idx]
        ranked.append(RankedClothingItem(
            item=product,
            color_name=color_names[idx] if color_names else "",
            size_name=size_names[idx] if size_names else "",
            price=prices[idx] if prices else 0.0,
            stock=stocks[idx] if stocks else 0,
            score=float(count - rank),  # higher = more relevant
            sizes_available=[],
            colors_available=[],
        ))

    return ranked


def _heuristic_rank(
    query: str,
    products: List[ClothingItem],
    color_names: Optional[List[str]] = None,
    size_names: Optional[List[str]] = None,
    prices: Optional[List[float]] = None,
    stocks: Optional[List[int]] = None,
) -> List[RankedClothingItem]:
    """
    Fallback ranking: text match + recency + stock.

    Score = 0.6 * text_score + 0.2 * recency_score + 0.2 * stock_score
    """
    query_lower = query.lower()
    query_tokens = set(query_lower.split())

    timestamps = [p.created_at.timestamp() if p.created_at else 0 for p in products]
    min_ts = min(timestamps) if timestamps else 0
    max_ts = max(timestamps) if timestamps else 1
    ts_range = max_ts - min_ts if max_ts > min_ts else 1.0

    scored = []
    for i, product in enumerate(products):
        # Text relevance: title, description, category, type
        text_blob = " ".join(filter(None, [
            product.title,
            product.description,
            product.category,
            product.type,
        ])).lower()
        product_tokens = set(text_blob.split())
        overlap = query_tokens & product_tokens
        text_score = len(overlap) / len(query_tokens) if query_tokens else 0.0

        # Recency
        ts = timestamps[i]
        recency_score = (ts - min_ts) / ts_range if ts_range > 0 else 0.5

        # Stock
        stock_val = stocks[i] if stocks and i < len(stocks) else 0
        stock_score = min(stock_val / 10.0, 1.0) if stock_val > 0 else 0.0

        final_score = 0.6 * text_score + 0.2 * recency_score + 0.2 * stock_score

        scored.append(RankedClothingItem(
            item=product,
            color_name=color_names[i] if color_names and i < len(color_names) else "",
            size_name=size_names[i] if size_names and i < len(size_names) else "",
            price=prices[i] if prices and i < len(prices) else 0.0,
            stock=stock_val,
            score=final_score,
            sizes_available=[],
            colors_available=[],
        ))

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Convenience: narrowing questions
# ---------------------------------------------------------------------------

async def generate_narrowing_questions(
    query: str,
    result_count: int,
    filters: Dict[str, Any],
) -> List[str]:
    """
    Ask the LLM to generate 2-3 narrowing questions.

    Falls back to static questions if the LLM is unavailable.
    """
    if openrouter_client.is_configured:
        try:
            messages = _build_narrowing_prompt(query, result_count, filters)
            raw = await openrouter_client.chat(messages, temperature=0.5, max_tokens=300)
            questions = _parse_questions(raw)
            if questions:
                return questions
        except Exception as exc:
            logger.warning(f"AI narrowing question generation failed: {exc}")

    # Fallback to static questions
    return _static_narrowing_questions(filters)


def _parse_questions(raw: str) -> List[str]:
    """Parse a JSON array of question strings from LLM output."""
    import json
    import re

    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(q) for q in data if str(q).strip()]
    except (json.JSONDecodeError, ValueError):
        pass

    # Try extracting quoted strings
    questions = re.findall(r'"([^"]+)"', raw)
    if questions:
        return questions

    # Try line-by-line
    lines = [l.strip().lstrip("- ").strip() for l in raw.splitlines() if l.strip()]
    return lines


def _static_narrowing_questions(filters: Dict[str, Any]) -> List[str]:
    """Fallback narrowing questions when AI is unavailable."""
    questions = []
    if "brand" not in filters:
        questions.append("Would you like to narrow by brand?")
    if "category" not in filters:
        questions.append("Do you have a specific category in mind?")
    questions.append("What's your preferred budget range?")
    return questions
