"""
Search result ranking.

Provides a simple scoring function that combines text relevance,
product popularity (featured flag), and recency to produce a final
score for each search result.
"""

from typing import List

from app.models.schemas import ProductSearchResult


def rank_results(results: List[ProductSearchResult]) -> List[ProductSearchResult]:
    """
    Re-rank search results by a weighted score.

    The score is computed as::

        final = 0.6 * relevance + 0.2 * popularity + 0.2 * recency

    where ``relevance`` is the existing score, ``popularity`` is 1.0 if
    the product is featured, and ``recency`` is normalized to [0, 1]
    based on ``created_at``.
    """
    if not results:
        return results

    # Compute recency normalization
    timestamps = [r.product.created_at.timestamp() for r in results]
    min_ts, max_ts = min(timestamps), max(timestamps)
    ts_range = max_ts - min_ts if max_ts > min_ts else 1.0

    for r in results:
        popularity = 1.0 if r.product.is_featured else 0.0
        recency = (r.product.created_at.timestamp() - min_ts) / ts_range
        r.score = 0.6 * r.score + 0.2 * popularity + 0.2 * recency

    return sorted(results, key=lambda r: r.score, reverse=True)
