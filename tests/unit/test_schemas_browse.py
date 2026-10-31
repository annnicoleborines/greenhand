"""Unit tests for BrowseFilterSchema (FR-4): a GET filter form that never raises.

Plain Pydantic, no database. Each field gets a good value, a blank value and a
bad value. `from_query` is tested with the kind of dict Flask's request.args
gives us (all values are strings).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.schemas.browse import BrowseFilterSchema


def test_defaults_when_query_is_empty() -> None:
    filters = BrowseFilterSchema.from_query({})
    assert filters.keyword is None
    assert filters.location_id is None
    assert filters.activity_date is None
    assert filters.page == 1
    assert filters.is_filtered is False


def test_good_values_are_parsed() -> None:
    filters = BrowseFilterSchema.from_query(
        {"keyword": "  mangrove ", "location_id": "3", "activity_date": "2030-06-15", "page": "2"}
    )
    assert filters.keyword == "mangrove"  # stripped
    assert filters.location_id == 3
    assert filters.activity_date == date(2030, 6, 15)
    assert filters.page == 2
    assert filters.is_filtered is True


@pytest.mark.parametrize("value", ["", "   ", None])
def test_blank_keyword_becomes_none(value: str | None) -> None:
    assert BrowseFilterSchema.from_query({"keyword": value}).keyword is None


def test_keyword_over_max_length_is_dropped_not_raised() -> None:
    filters = BrowseFilterSchema.from_query({"keyword": "x" * 101, "location_id": "2"})
    assert filters.keyword is None
    assert filters.location_id == 2  # the other filters survive


@pytest.mark.parametrize("value", ["", "abc", "1.5", "-4", "0", None])
def test_bad_location_becomes_none(value: str | None) -> None:
    assert BrowseFilterSchema.from_query({"location_id": value}).location_id is None


@pytest.mark.parametrize("value", ["", "not-a-date", "2030-13-45", "15/06/2030", None])
def test_bad_date_becomes_none(value: str | None) -> None:
    assert BrowseFilterSchema.from_query({"activity_date": value}).activity_date is None


@pytest.mark.parametrize("value", ["", "abc", "0", "-2", None])
def test_bad_page_falls_back_to_one(value: str | None) -> None:
    assert BrowseFilterSchema.from_query({"page": value}).page == 1


def test_unknown_query_keys_are_ignored() -> None:
    filters = BrowseFilterSchema.from_query({"evil": "DROP TABLE", "page": "3"})
    assert filters.page == 3


def test_as_query_args_keeps_only_set_filters() -> None:
    filters = BrowseFilterSchema.from_query(
        {"keyword": "tree", "location_id": "", "activity_date": "2030-01-02", "page": "4"}
    )
    # page is left out on purpose: the pagination macro adds its own page number
    assert filters.as_query_args() == {"keyword": "tree", "activity_date": "2030-01-02"}


def test_direct_construction_with_typed_values() -> None:
    filters = BrowseFilterSchema(location_id=7, activity_date=date(2030, 1, 1), page=2)
    assert filters.location_id == 7
    assert filters.page == 2
