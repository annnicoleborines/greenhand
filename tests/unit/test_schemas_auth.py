"""Unit tests for the sign-up and login schemas (FR-4: validate before saving).

The schemas are plain Pydantic models, so no database or Flask app is needed.
`validate()` is the helper services use; it turns Pydantic errors into our
ValidationError with one message per field, which the templates show inline.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.errors import ValidationError
from app.schemas.auth import LoginSchema, SignUpSchema
from app.schemas.base import validate


def signup_form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "username": "Maria_01",
        "email": "Maria@Example.com",
        "password": "Secret123",
        "confirm_password": "Secret123",
        "first_name": " Maria ",
        "last_name": "Santos",
        "phone": "0917 123 4567",
        "address": "",
    }
    form.update(overrides)
    return form


# ---------------------------------------------------------------- sign-up
def test_signup_valid_form_is_normalised() -> None:
    data = validate(SignUpSchema, signup_form())
    assert data.username == "maria_01"  # lower-cased so logins are case-insensitive
    assert data.email == "maria@example.com"
    assert data.first_name == "Maria"  # whitespace stripped
    assert data.phone == "0917 123 4567"
    assert data.address is None  # blank optional field becomes NULL, not ""


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("username", "ab", "at least 3"),
        ("username", "bad name!", "letters, numbers or underscores"),
        ("email", "not-an-email", "valid email"),
        ("password", "short1", "at least 8"),
        ("password", "lettersonly", "letter and one number"),
        ("password", "12345678", "letter and one number"),
        # 42 characters but 82 bytes: bcrypt would refuse it, so the schema must too.
        ("password", "a1" + "é" * 40, "max 72 bytes"),
        ("phone", "abc", "valid phone"),
        ("first_name", "", "at least 1"),
    ],
)
def test_signup_rejects_bad_field(field: str, value: str, fragment: str) -> None:
    form = signup_form(**{field: value})
    if field == "password":
        form["confirm_password"] = value  # isolate the password rule itself
    with pytest.raises(ValidationError) as exc_info:
        validate(SignUpSchema, form)
    assert fragment in exc_info.value.errors[field]


def test_signup_password_mismatch_lands_on_confirm_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(SignUpSchema, signup_form(confirm_password="Different1"))
    assert exc_info.value.errors == {"confirm_password": "Passwords do not match."}


def test_signup_mismatch_is_reported_alongside_other_errors() -> None:
    """Regression: a model-level validator used to be skipped when another field failed."""
    with pytest.raises(ValidationError) as exc_info:
        validate(SignUpSchema, signup_form(email="nope", confirm_password="Different1"))
    assert "email" in exc_info.value.errors
    assert exc_info.value.errors["confirm_password"] == "Passwords do not match."


def test_signup_mismatch_not_reported_when_password_itself_invalid() -> None:
    """Only one password message at a time: fix the password first, then the confirmation."""
    with pytest.raises(ValidationError) as exc_info:
        validate(SignUpSchema, signup_form(password="short", confirm_password="Different1"))
    assert "password" in exc_info.value.errors
    assert "confirm_password" not in exc_info.value.errors


def test_signup_missing_required_fields_are_all_listed() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate(SignUpSchema, {})
    assert set(exc_info.value.errors) >= {
        "username",
        "email",
        "password",
        "confirm_password",
        "first_name",
        "last_name",
    }
    assert exc_info.value.status_code == 422


# ------------------------------------------------------------------ login
def test_login_schema_strips_whitespace() -> None:
    data = validate(LoginSchema, {"username": "  maria ", "password": "x"})
    assert data.username == "maria"


@pytest.mark.parametrize("form", [{}, {"username": "", "password": "x"}, {"username": "m"}])
def test_login_schema_requires_both_fields(form: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        validate(LoginSchema, form)


def test_signup_password_limit_counts_bytes_not_characters() -> None:
    """bcrypt stops at 72 bytes; 'é' is 2 bytes, so 72 such characters must be refused."""
    too_long = "a1" + "é" * 70  # 72 characters, 142 bytes
    with pytest.raises(ValidationError) as exc_info:
        validate(SignUpSchema, signup_form(password=too_long, confirm_password=too_long))
    assert "too long" in exc_info.value.errors["password"]
