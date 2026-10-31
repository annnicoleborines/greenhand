"""Page: one page of a long list, plus the numbers a pagination bar needs.

Services return a Page instead of a bare list so templates can show
"Showing 21-40 of 95" and previous/next links without doing arithmetic in Jinja.
The class is generic: Page[Activity], Page[Person], ... all share this code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def clamp_page(page: int | None) -> int:
    """Turn whatever came from ?page= into a usable page number (never below 1)."""
    return max(page or 1, 1)


def offset_for(page: int, per_page: int) -> int:
    """Rows to skip for `page`: page 1 skips nothing, page 2 skips `per_page`, ..."""
    return (clamp_page(page) - 1) * per_page


@dataclass
class Page[T]:
    items: list[T] = field(default_factory=list)
    page: int = 1
    per_page: int = 20
    total: int = 0

    @property
    def pages(self) -> int:
        """How many pages exist (at least 1, so an empty list still reads "page 1 of 1")."""
        if self.total <= 0 or self.per_page <= 0:
            return 1
        return -(-self.total // self.per_page)  # ceiling division without math.ceil

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def prev_page(self) -> int | None:
        return self.page - 1 if self.has_prev else None

    @property
    def next_page(self) -> int | None:
        return self.page + 1 if self.has_next else None

    @property
    def start(self) -> int:
        """1-based number of the first row on this page (0 when the list is empty)."""
        if self.total == 0:
            return 0
        return (self.page - 1) * self.per_page + 1

    @property
    def end(self) -> int:
        """1-based number of the last row on this page (0 when the list is empty)."""
        if self.total == 0:
            return 0
        return min(self.page * self.per_page, self.total)
