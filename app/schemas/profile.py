"""Pydantic schemas for the volunteer profile pages (FR-4: validate before saving).

Two forms live here: the profile details form and the change-password form.
Both reuse the rules from the sign-up schema (phone shape, password strength)
so a value that was fine at sign-up is still fine here.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.schemas.auth import PASSWORD_MAX, PASSWORD_MIN, PHONE_RE, check_password_strength

MIN_VOLUNTEER_AGE = 13


class ProfileSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    phone: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=255)
    birth_date: date | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=100)
    emergency_contact_phone: str | None = Field(default=None, max_length=20)

    @field_validator(
        "phone", "address", "emergency_contact_name", "emergency_contact_phone", mode="before"
    )
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        # An empty <input> arrives as "", which we store as NULL, not as "".
        return value or None

    @field_validator("phone", "emergency_contact_phone")
    @classmethod
    def phone_shape(cls, value: str | None) -> str | None:
        if value is not None and not PHONE_RE.fullmatch(value):
            msg = "Enter a valid phone number."
            raise ValueError(msg)
        return value

    @field_validator("birth_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> Any:
        # <input type="date"> posts "YYYY-MM-DD" or "" when left empty.
        if value is None or isinstance(value, date):
            return value
        text = str(value).strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            msg = "Enter a valid date."
            raise ValueError(msg) from exc

    @field_validator("birth_date")
    @classmethod
    def birth_date_rules(cls, value: date | None, info: ValidationInfo) -> date | None:
        if value is None:
            return None
        # Tests pass today's date through the validation context; the app uses the clock.
        context = info.context or {}
        today: date = context.get("today") or date.today()
        if value >= today:
            msg = "Birth date must be in the past."
            raise ValueError(msg)
        had_birthday = (today.month, today.day) >= (value.month, value.day)
        age = today.year - value.year - (0 if had_birthday else 1)
        if age < MIN_VOLUNTEER_AGE:
            msg = f"Volunteers must be at least {MIN_VOLUNTEER_AGE} years old."
            raise ValueError(msg)
        return value


class ChangePasswordSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX)
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_rules(cls, value: str, info: ValidationInfo) -> str:
        check_password_strength(value)  # same rules as sign-up, incl. the 72-byte limit
        # `current_password` is missing from info.data when it failed its own check.
        if info.data.get("current_password") == value:
            msg = "New password must be different from the current one."
            raise ValueError(msg)
        return value

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, value: str, info: ValidationInfo) -> str:
        # Field validator (not model validator) so the message lands on this field
        # and still shows when other fields fail. Skip when new_password failed.
        new_password = info.data.get("new_password")
        if new_password is not None and value != new_password:
            msg = "Passwords do not match."
            raise ValueError(msg)
        return value
