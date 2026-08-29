"""Search result ranking."""

from datetime import datetime, timezone
from typing import List

from app.models.schemas import ProductSearchResult


def rank_results(results: List[ProductSearchResult]) -> List[ProductSearchResult]:
    if not results:
        return results

    timestamps = []
    for result in results:
        created_at = result.product.created_at
        if created_at is None:
            timestamps.append(0.0)
        else:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            timestamps.append(created_at.timestamp())

    min_ts, max_ts = min(timestamps), max(timestamps)
    ts_range = max_ts - min_ts if max_ts > min_ts else 1.0

    for result, timestamp in zip(results, timestamps):
        popularity = 1.0 if result.product.is_featured else 0.0
        recency = (timestamp - min_ts) / ts_range if timestamp else 0.0
        result.score = 0.6 * result.score + 0.2 * popularity + 0.2 * recency

    return sorted(results, key=lambda item: item.score, reverse=True)
