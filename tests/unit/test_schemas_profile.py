"""Unit tests for the profile and change-password schemas (FR-4).

Plain Pydantic models: no database or Flask app needed. Each rule gets a happy
case and a failure case. Birth-date rules get "today" through the validation
context so the tests do not depend on the real clock.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.errors import ValidationError
from app.schemas.base import validate
from app.schemas.profile import ChangePasswordSchema, ProfileSchema

TODAY = date(2030, 6, 15)


def profile_form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "first_name": " Maria ",
        "last_name": "Santos",
        "phone": "0917 123 4567",
        "address": "",
        "birth_date": "2000-01-31",
        "emergency_contact_name": "Ana Santos",
        "emergency_contact_phone": "+63 917 000 0000",
    }
    form.update(overrides)
    return form


def password_form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "current_password": "OldSecret1",
        "new_password": "NewSecret2",
        "confirm_password": "NewSecret2",
    }
    form.update(overrides)
    return form


# ---------------------------------------------------------------- profile
def test_profile_valid_form_is_normalised() -> None:
    data = validate(ProfileSchema, profile_form())
    assert data.first_name == "Maria"  # whitespace stripped
    assert data.address is None  # blank optional field becomes NULL
    assert data.birth_date == date(2000, 1, 31)  # "YYYY-MM-DD" text becomes a date
    assert data.emergency_contact_phone == "+63 917 000 0000"


def test_profile_all_optional_fields_may_be_blank() -> None:
    data = validate(
        ProfileSchema,
        profile_form(
            phone="", birth_date="", emergency_contact_name="", emergency_contact_phone=""
        ),
    )
    assert data.phone is None and data.birth_date is None
    assert data.emergency_contact_name is None and data.emergency_contact_phone is None


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("first_name", "", "at least 1"),
        ("first_name", "x" * 51, "at most 50"),
        ("last_name", "   ", "at least 1"),
        ("phone", "abc", "valid phone"),
        ("address", "a" * 256, "at most 255"),
        ("birth_date", "31/01/2000", "valid date"),
        ("emergency_contact_name", "n" * 101, "at most 100"),
        ("emergency_contact_phone", "12", "valid phone"),
    ],
)
def test_profile_rejects_bad_field(field: str, value: str, fragment: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(ProfileSchema, profile_form(**{field: value}))
    assert fragment in exc_info.value.errors[field]
    assert exc_info.value.status_code == 422


def test_profile_birth_date_must_be_in_the_past() -> None:
    for value in (TODAY, TODAY.replace(year=TODAY.year + 1)):
        with pytest.raises(ValueError, match="in the past"):
            ProfileSchema.model_validate(profile_form(birth_date=value), context={"today": TODAY})


def test_profile_volunteer_must_be_at_least_13() -> None:
    thirteen_tomorrow = date(TODAY.year - 13, TODAY.month, TODAY.day + 1)
    with pytest.raises(ValueError, match="at least 13"):
        ProfileSchema.model_validate(
            profile_form(birth_date=thirteen_tomorrow), context={"today": TODAY}
        )


def test_profile_accepts_a_volunteer_who_turns_13_today() -> None:
    thirteen_today = date(TODAY.year - 13, TODAY.month, TODAY.day)
    data = ProfileSchema.model_validate(
        profile_form(birth_date=thirteen_today), context={"today": TODAY}
    )
    assert data.birth_date == thirteen_today


def test_profile_birth_date_uses_the_real_clock_without_context() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(ProfileSchema, profile_form(birth_date=date.today().isoformat()))
    assert "in the past" in exc_info.value.errors["birth_date"]


def test_profile_missing_required_fields_are_listed() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(ProfileSchema, {})
    assert set(exc_info.value.errors) == {"first_name", "last_name"}


# ------------------------------------------------------- change password
def test_change_password_valid_form() -> None:
    data = validate(ChangePasswordSchema, password_form())
    assert data.new_password == "NewSecret2"


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("current_password", "", "at least 1"),
        ("new_password", "short1", "at least 8"),
        ("new_password", "lettersonly", "letter and one number"),
        ("new_password", "12345678", "letter and one number"),
        ("new_password", "x1" * 40, "at most 72"),
        # 42 characters but 82 bytes: bcrypt would refuse it, so the schema must too.
        ("new_password", "a1" + "é" * 40, "max 72 bytes"),
    ],
)
def test_change_password_rejects_bad_field(field: str, value: str, fragment: str) -> None:
    form = password_form(**{field: value})
    if field == "new_password":
        form["confirm_password"] = value  # isolate the password rule itself
    with pytest.raises(ValidationError) as exc_info:
        validate(ChangePasswordSchema, form)
    assert fragment in exc_info.value.errors[field]


def test_change_password_new_must_differ_from_current() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(
            ChangePasswordSchema,
            password_form(new_password="OldSecret1", confirm_password="OldSecret1"),
        )
    assert exc_info.value.errors == {
        "new_password": "New password must be different from the current one."
    }


def test_change_password_mismatch_lands_on_confirm_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(ChangePasswordSchema, password_form(confirm_password="Different1"))
    assert exc_info.value.errors == {"confirm_password": "Passwords do not match."}


def test_change_password_mismatch_not_reported_when_new_password_invalid() -> None:
    """One password message at a time: fix the new password first, then the confirmation."""
    with pytest.raises(ValidationError) as exc_info:
        validate(ChangePasswordSchema, password_form(new_password="short", confirm_password="x"))
    assert "new_password" in exc_info.value.errors
    assert "confirm_password" not in exc_info.value.errors


def test_change_password_missing_fields_are_all_listed() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(ChangePasswordSchema, {})
    assert set(exc_info.value.errors) == {"current_password", "new_password", "confirm_password"}
