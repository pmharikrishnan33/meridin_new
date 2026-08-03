"""
Inventory search service.

This service owns the search-state lifecycle for a cached, pageable product
search result set. It keeps the store of result IDs and a stable search key
so the conversation can paginate without re-running the MongoDB query.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from app.models.schemas import ProductSearchFilters


class InventorySearchService:
    """Build and expose stable search-page metadata for the bot flow."""

    def _build_search_key(self, tenant_id: str, filters: ProductSearchFilters) -> str:
        payload = {
            "tenant_id": tenant_id,
            "filters": filters.model_dump(exclude_none=True),
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def build_search_page(
        self,
        tenant_id: str,
        filters: ProductSearchFilters,
        result_ids: List[str],
        page: int = 1,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Build a paginated result snapshot for a stored search.

        Returns a dict with search_key, page metadata, and sliced product ids.
        """

        page_size = page_size or filters.limit or 10
        if page_size <= 0:
            page_size = len(result_ids) or 1

        total = len(result_ids)
        total_pages = (total + page_size - 1) // page_size if total else 1
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size
        items = result_ids[offset:offset + page_size]

        return {
            "search_key": self._build_search_key(tenant_id, filters),
            "query": filters.query,
            "filters": filters.model_dump(exclude_none=True),
            "items": items,
            "page": page,
            "page_size": page_size,
            "offset": offset,
            "total": total,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
        }


inventory_search_service = InventorySearchService()
