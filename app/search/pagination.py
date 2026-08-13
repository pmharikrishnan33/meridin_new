"""
Pagination utilities for search results.

Provides a simple, dependency-free paginator that works with any
list of items and is compatible with the ``ProductSearchFilters``
offset/limit convention used throughout the application.
"""

from dataclasses import dataclass, field
from typing import Generic, List, TypeVar

T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    """A single page of results."""

    items: List[T]
    page: int
    per_page: int
    total: int

    @property
    def has_next(self) -> bool:
        """Whether there is a next page."""
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        """Whether there is a previous page."""
        return self.page > 1

    @property
    def total_pages(self) -> int:
        """Total number of pages."""
        if self.per_page <= 0:
            return 1
        return (self.total + self.per_page - 1) // self.per_page


@dataclass
class Paginator(Generic[T]):
    """
    Paginate a list of items.

    Usage::

        paginator = Paginator(items, per_page=10)
        page = paginator.get_page(page_number=2)
    """

    items: List[T] = field(default_factory=list)
    per_page: int = 10
    _total: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._total = len(self.items)

    @property
    def total(self) -> int:
        return self._total

    def get_page(self, page_number: int = 1) -> Page[T]:
        """
        Return a :class:`Page` for the given 1-based page number.

        Page numbers are clamped to the valid range [1, total_pages].
        """
        if page_number < 1:
            page_number = 1

        total_pages = self.total_pages
        if page_number > total_pages:
            page_number = total_pages if total_pages > 0 else 1

        start = (page_number - 1) * self.per_page
        end = start + self.per_page
        page_items = self.items[start:end]

        return Page(
            items=page_items,
            page=page_number,
            per_page=self.per_page,
            total=self._total,
        )

    @property
    def total_pages(self) -> int:
        if self.per_page <= 0:
            return 1
        return (self._total + self.per_page - 1) // self.per_page

    @staticmethod
    def from_offset_limit(
        items: List[T],
        offset: int,
        limit: int,
    ) -> Page[T]:
        """
        Build a single :class:`Page` from offset/limit (the convention
        used by :class:`~app.models.schemas.ProductSearchFilters`).
        """
        total = len(items)
        per_page = limit if limit > 0 else total
        page_number = (offset // per_page) + 1 if per_page > 0 else 1

        page_items = items[offset:offset + limit]

        return Page(
            items=page_items,
            page=page_number,
            per_page=per_page,
            total=total,
        )


def paginate(
    items: List[T],
    page: int = 1,
    per_page: int = 10,
) -> Page[T]:
    """
    Convenience function to paginate a list of items.

    Args:
        items: The full list of items to paginate.
        page: 1-based page number (default 1).
        per_page: Number of items per page (default 10).

    Returns:
        A :class:`Page` containing the items for the requested page.
    """
    paginator = Paginator(items=items, per_page=per_page)
    return paginator.get_page(page_number=page)
