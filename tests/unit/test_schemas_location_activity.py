"""Unit tests for the admin location and activity form schemas (FR-4).

Plain Pydantic models: no database or Flask app needed. Every rule gets a happy
case and a failure case. The activity date rule gets "today" and the
create-vs-edit flag through the validation context, so the tests do not depend
on the real clock.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

import pytest

from app.errors import ValidationError
from app.schemas.activity import ActivitySchema
from app.schemas.base import validate
from app.schemas.location import LocationSchema

TODAY = date(2030, 6, 15)
CREATING = {"today": TODAY, "creating": True}
EDITING = {"today": TODAY, "creating": False}


def location_form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "location_name": " Riverside Park ",
        "address": "12 River Road",
        "details": "",
    }
    form.update(overrides)
    return form


def activity_form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "title": " Mangrove planting ",
        "description": "",
        "location_id": "3",
        "activity_date": "2030-07-01",
        "start_time": "08:00",
        "end_time": "11:30",
        "max_volunteers": "25",
        "requirements": "Bring gloves",
    }
    form.update(overrides)
    return form


# --------------------------------------------------------------- location
def test_location_valid_form_is_normalised() -> None:
    data = validate(LocationSchema, location_form())
    assert data.location_name == "Riverside Park"  # whitespace stripped
    assert data.address == "12 River Road"
    assert data.details is None  # blank optional field becomes NULL


def test_location_details_are_kept_when_given() -> None:
    data = validate(LocationSchema, location_form(details="Meet at the main gate."))
    assert data.details == "Meet at the main gate."


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("location_name", "A", "at least 2"),
        ("location_name", "x" * 101, "at most 100"),
        ("address", "", "at least 1"),
        ("address", "   ", "at least 1"),
        ("address", "a" * 256, "at most 255"),
        ("details", "d" * 1001, "at most 1000"),
    ],
)
def test_location_rejects_bad_field(field: str, value: str, fragment: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(LocationSchema, location_form(**{field: value}))
    assert fragment in exc_info.value.errors[field]


def test_location_missing_fields_are_reported_per_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(LocationSchema, {})
    assert set(exc_info.value.errors) == {"location_name", "address"}


# --------------------------------------------------------------- activity
def test_activity_valid_form_is_parsed_into_real_values() -> None:
    data = validate(ActivitySchema, activity_form(), context=CREATING)
    assert data.title == "Mangrove planting"
    assert data.description is None
    assert data.location_id == 3  # "3" -> int
    assert data.activity_date == date(2030, 7, 1)  # "YYYY-MM-DD" -> date
    assert data.start_time == time(8, 0) and data.end_time == time(11, 30)  # "HH:MM" -> time
    assert data.max_volunteers == 25
    assert data.requirements == "Bring gloves"


def test_activity_accepts_already_typed_values_too() -> None:
    form = activity_form(
        location_id=3,
        activity_date=date(2030, 7, 1),
        start_time=time(8, 0),
        end_time=time(11, 30),
        max_volunteers=25,
    )
    data = validate(ActivitySchema, form, context=EDITING)
    assert data.location_id == 3 and data.max_volunteers == 25


def test_activity_accepts_seconds_in_times() -> None:
    data = validate(ActivitySchema, activity_form(start_time="08:00:00"), context=EDITING)
    assert data.start_time == time(8, 0)


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("title", "ab", "at least 3"),
        ("title", "t" * 151, "at most 150"),
        ("location_id", "", "Choose a location."),
        ("location_id", "0", "Choose a location."),
        ("location_id", "abc", "Choose a location."),
        ("location_id", "-2", "Choose a location."),
        ("activity_date", "", "valid date"),
        ("activity_date", "01/07/2030", "valid date"),
        ("start_time", "", "valid time"),
        ("start_time", "8am", "valid time"),
        ("end_time", "25:00", "valid time"),
        ("max_volunteers", "", "whole number"),
        ("max_volunteers", "ten", "whole number"),
        ("max_volunteers", "0", "greater than or equal to 1"),
        ("max_volunteers", "1001", "less than or equal to 1000"),
    ],
)
def test_activity_rejects_bad_field(field: str, value: str, fragment: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(ActivitySchema, activity_form(**{field: value}), context=CREATING)
    assert fragment in exc_info.value.errors[field]


def test_activity_max_volunteers_boundaries_are_inclusive() -> None:
    assert validate(ActivitySchema, activity_form(max_volunteers="1"), context=EDITING)
    assert validate(ActivitySchema, activity_form(max_volunteers="1000"), context=EDITING)


# ----------------------------------------------------- end > start rule
def test_activity_end_time_must_be_after_start_time() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(ActivitySchema, activity_form(start_time="11:30", end_time="08:00"))
    assert exc_info.value.errors == {"end_time": "End time must be after start time."}


def test_activity_end_time_equal_to_start_time_is_refused() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(ActivitySchema, activity_form(start_time="09:00", end_time="09:00"))
    assert "after start time" in exc_info.value.errors["end_time"]


def test_activity_end_time_rule_is_skipped_when_start_time_is_invalid() -> None:
    # Only the start_time error shows; end_time has nothing to compare against.
    with pytest.raises(ValidationError) as exc_info:
        validate(ActivitySchema, activity_form(start_time="nope", end_time="08:00"))
    assert set(exc_info.value.errors) == {"start_time"}


# ------------------------------------------------- date rule: create vs edit
def test_activity_create_refuses_a_date_in_the_past() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(ActivitySchema, activity_form(activity_date="2030-06-14"), context=CREATING)
    assert exc_info.value.errors == {"activity_date": "Activity date cannot be in the past."}


def test_activity_create_accepts_today() -> None:
    data = validate(ActivitySchema, activity_form(activity_date="2030-06-15"), context=CREATING)
    assert data.activity_date == TODAY


def test_activity_edit_accepts_a_date_in_the_past() -> None:
    data = validate(ActivitySchema, activity_form(activity_date="2020-01-01"), context=EDITING)
    assert data.activity_date == date(2020, 1, 1)


def test_activity_without_context_does_not_apply_the_create_rule() -> None:
    # No context = not creating: an old date passes (the service always passes one).
    data = validate(ActivitySchema, activity_form(activity_date="2020-01-01"))
    assert data.activity_date == date(2020, 1, 1)


def test_activity_create_uses_the_clock_when_today_is_not_given() -> None:
    with pytest.raises(ValidationError, match="highlighted"):
        validate(
            ActivitySchema, activity_form(activity_date="2000-01-01"), context={"creating": True}
        )


def test_activity_several_errors_are_reported_together() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(
            ActivitySchema,
            activity_form(title="", location_id="", max_volunteers="0"),
            context=CREATING,
        )
    assert set(exc_info.value.errors) == {"title", "location_id", "max_volunteers"}
