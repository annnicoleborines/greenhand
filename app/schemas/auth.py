"""Pydantic schemas for sign-up and login (FR-4: validate before saving)."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,50}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,20}$")

PASSWORD_MIN = 8
PASSWORD_MAX = 72  # bcrypt limit


def check_password_strength(value: str) -> str:
    """Shared rules for a new password (sign-up and change password).

    bcrypt reads at most 72 *bytes*, and accented letters take 2+ bytes each, so
    the byte length is checked here; the Field max_length only counts characters.
    """
    if len(value.encode("utf-8")) > PASSWORD_MAX:
        msg = f"Password is too long (max {PASSWORD_MAX} bytes)."
        raise ValueError(msg)
    if not re.search(r"[A-Za-z]", value) or not re.search(r"[0-9]", value):
        msg = "Password needs at least one letter and one number."
        raise ValueError(msg)
    return value


class SignUpSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=50)
    email: str = Field(max_length=100)
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
    confirm_password: str
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    phone: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=255)

    @field_validator("username")
    @classmethod
    def username_chars(cls, value: str) -> str:
        if not USERNAME_RE.fullmatch(value):
            msg = "Use 3-50 letters, numbers or underscores."
            raise ValueError(msg)
        return value.lower()

    @field_validator("email")
    @classmethod
    def email_shape(cls, value: str) -> str:
        if not EMAIL_RE.fullmatch(value):
            msg = "Enter a valid email address."
            raise ValueError(msg)
        return value.lower()

    @field_validator("password")
    @classmethod
    def password_rules(cls, value: str) -> str:
        return check_password_strength(value)

    @field_validator("phone", "address", mode="before")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("phone")
    @classmethod
    def phone_shape(cls, value: str | None) -> str | None:
        if value is not None and not PHONE_RE.fullmatch(value):
            msg = "Enter a valid phone number."
            raise ValueError(msg)
        return value

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, value: str, info: ValidationInfo) -> str:
        # A field validator (not a model validator) so the message lands on this
        # field and still shows when other fields are invalid. `password` is
        # missing from info.data when it failed its own checks; skip then.
        password = info.data.get("password")
        if password is not None and value != password:
            msg = "Passwords do not match."
            raise ValueError(msg)
        return value


class LoginSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX)
