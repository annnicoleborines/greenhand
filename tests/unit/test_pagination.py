"""Unit tests for the Page helper used by every paginated admin list."""

from __future__ import annotations

import pytest

from app.services.pagination import Page, clamp_page, offset_for


def test_clamp_page_never_goes_below_one() -> None:
    assert clamp_page(None) == 1
    assert clamp_page(0) == 1
    assert clamp_page(-7) == 1
    assert clamp_page(3) == 3


def test_offset_for_skips_whole_pages() -> None:
    assert offset_for(1, 20) == 0
    assert offset_for(2, 20) == 20
    assert offset_for(4, 10) == 30
    assert offset_for(0, 10) == 0  # a bad page number is clamped first


def test_page_counts_and_bounds_in_the_middle() -> None:
    page = Page(items=["x"] * 10, page=2, per_page=10, total=25)
    assert page.pages == 3
    assert (page.has_prev, page.has_next) == (True, True)
    assert (page.prev_page, page.next_page) == (1, 3)
    assert (page.start, page.end) == (11, 20)


def test_first_page_has_no_previous() -> None:
    page = Page(items=["x"] * 10, page=1, per_page=10, total=25)
    assert page.has_prev is False and page.prev_page is None
    assert page.has_next is True and page.next_page == 2
    assert (page.start, page.end) == (1, 10)


def test_last_page_is_shorter_and_has_no_next() -> None:
    page = Page(items=["x"] * 5, page=3, per_page=10, total=25)
    assert page.has_next is False and page.next_page is None
    assert (page.start, page.end) == (21, 25)


def test_exact_multiple_does_not_create_an_empty_extra_page() -> None:
    assert Page(page=1, per_page=10, total=20).pages == 2


def test_empty_list_still_reads_page_one_of_one() -> None:
    page: Page[str] = Page()
    assert page.pages == 1
    assert (page.start, page.end) == (0, 0)
    assert page.has_prev is False and page.has_next is False


@pytest.mark.parametrize(("total", "per_page", "pages"), [(1, 10, 1), (11, 10, 2), (99, 20, 5)])
def test_pages_is_a_ceiling_division(total: int, per_page: int, pages: int) -> None:
    assert Page(page=1, per_page=per_page, total=total).pages == pages
