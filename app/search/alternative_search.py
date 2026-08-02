"""
Alternative search strategies for product search.

When the primary MongoDB text search returns no results or the query
is ambiguous, these strategies provide fallback matching:

1. **Fuzzy matching** — uses ``rapidfuzz`` to find products whose names
   are similar to the query (handles typos and partial matches).

2. **Keyword overlap** — splits the query into tokens and scores products
   by how many query tokens appear in the product name, description, or
   tags.

3. **Category boost** — if the query contains a known category or brand,
   that signal is used to narrow the search.
"""

from typing import List, Optional

from rapidfuzz import process, fuzz

from app.models.schemas import Product, ProductSearchFilters
from app.utils.logger import logger


# Common e-commerce categories and their keywords
CATEGORY_KEYWORDS: dict[str, List[str]] = {
    "shirt": ["shirt", "t-shirt", "tshirt", "top", "kurta", "kurti"],
    "pants": ["pants", "trousers", "jeans", "joggers", "shorts", "leggings"],
    "jacket": ["jacket", "coat", "hoodie", "sweater", "cardigan"],
    "dress": ["dress", "gown", "saree", "sari"],
    "shoes": ["shoes", "sneakers", "boots", "sandals", "flip-flop"],
}


def fuzzy_match_products(
    products: List[Product],
    query: str,
    score_cutoff: int = 60,
    limit: int = 10,
) -> List[Product]:
    """
    Fuzzy-match a query against product names.

    Uses ``rapidfuzz.process.extract`` to find products whose names
    have a similarity score above ``score_cutoff``.

    Args:
        products: The candidate product list (already filtered by tenant).
        query: The user's search query.
        score_cutoff: Minimum similarity score (0-100).
        limit: Maximum number of results to return.

    Returns:
        List of matching products sorted by similarity score (descending).
    """
    if not products or not query:
        return []

    names = [p.name for p in products]
    results = process.extract(
        query,
        names,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=score_cutoff,
        limit=limit,
    )

    # Map matched names back to products
    matched = []
    name_to_product = {p.name: p for p in products}
    for matched_name, score, _ in results:
        product = name_to_product.get(matched_name)
        if product:
            matched.append(product)

    logger.debug(
        f"Fuzzy match '{query}' -> {len(matched)} products "
        f"(cutoff={score_cutoff})"
    )
    return matched


def keyword_overlap_search(
    products: List[Product],
    query: str,
    min_overlap: int = 1,
) -> List[Product]:
    """
    Score products by keyword overlap with the query.

    Splits the query into lowercase tokens and scores each product by
    counting how many tokens appear in the product's name, description,
    tags, or category.  Products are returned sorted by score descending.

    Args:
        products: The candidate product list.
        query: The user's search query.
        min_overlap: Minimum number of matching tokens to include a product.

    Returns:
        List of products sorted by keyword overlap score.
    """
    if not products or not query:
        return []

    query_tokens = set(query.lower().split())

    scored: List[tuple[float, Product]] = []
    for product in products:
        # Build a text blob from searchable fields
        searchable = " ".join([
            product.name,
            product.description,
            product.category or "",
            " ".join(product.tags),
        ]).lower()

        product_tokens = set(searchable.split())
        overlap = query_tokens & product_tokens

        if len(overlap) >= min_overlap:
            # Score: proportion of query tokens that matched
            score = len(overlap) / len(query_tokens) if query_tokens else 0
            scored.append((score, product))

    scored.sort(key=lambda x: x[0], reverse=True)
    logger.debug(
        f"Keyword overlap search '{query}' -> {len(scored)} products"
    )
    return [p for _, p in scored]


def detect_category(query: str) -> Optional[str]:
    """
    Detect a product category from the query text.

    Returns the category name (e.g. ``"shirt"``) or ``None`` if no
    category keyword is found.
    """
    query_lower = query.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in query_lower:
                return category
    return None


def alternative_search(
    products: List[Product],
    filters: ProductSearchFilters,
) -> List[Product]:
    """
    Run alternative search strategies and merge results.

    Tries fuzzy matching first, then keyword overlap.  Results are
    de-duplicated while preserving the order of first appearance.

    Args:
        products: The full product list for the tenant.
        filters: The original search filters (used for the query string).

    Returns:
        A de-duplicated list of products from all strategies.
    """
    if not filters.query:
        return products

    query = filters.query
    seen_ids: set[str] = set()
    results: List[Product] = []

    # Strategy 1: Fuzzy matching
    fuzzy_results = fuzzy_match_products(products, query)
    for p in fuzzy_results:
        if p.id not in seen_ids:
            seen_ids.add(p.id)
            results.append(p)

    # Strategy 2: Keyword overlap
    keyword_results = keyword_overlap_search(products, query)
    for p in keyword_results:
        if p.id not in seen_ids:
            seen_ids.add(p.id)
            results.append(p)

    logger.info(
        f"Alternative search for '{query}': "
        f"{len(fuzzy_results)} fuzzy + {len(keyword_results)} keyword "
        f"= {len(results)} unique"
    )
    return results
