"""Pydantic schema for the admin activity form (FR-4: validate before saving).

The HTML form posts everything as text: the date as "YYYY-MM-DD", the times as
"HH:MM" and the numbers as digits. The `mode="before"` validators turn that text
into real date/time/int values; the plain validators then apply the rules.

Two rules need facts the form cannot supply, so they come through the
validation context (`validate(ActivitySchema, form, context={...})`):
- "today": the date to compare against (tests pass a fixed date);
- "creating": True on the New Activity form, where a date in the past is refused.
  Editing allows any date so an old activity can still be corrected.

Two more rules need the database and live in ActivityService: the location must
exist, and on edit max_volunteers may not drop below the slots already taken.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

TITLE_MIN = 3
TITLE_MAX = 150
MAX_VOLUNTEERS_MIN = 1
MAX_VOLUNTEERS_MAX = 1000

LOCATION_MESSAGE = "Choose a location."


class ActivitySchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=TITLE_MIN, max_length=TITLE_MAX)
    description: str | None = None
    location_id: int
    activity_date: date
    start_time: time
    end_time: time
    max_volunteers: int = Field(ge=MAX_VOLUNTEERS_MIN, le=MAX_VOLUNTEERS_MAX)
    requirements: str | None = None

    # ------------------------------------------------------- text -> values
    @field_validator("description", "requirements", mode="before")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("location_id", mode="before")
    @classmethod
    def parse_location(cls, value: Any) -> Any:
        # A <select> with no choice posts "" (or "0" for a "-- choose --" option).
        if isinstance(value, bool):
            raise ValueError(LOCATION_MESSAGE)
        if isinstance(value, int):
            return value
        text = str(value or "").strip()
        if not text.isdigit() or int(text) <= 0:
            raise ValueError(LOCATION_MESSAGE)
        return int(text)

    @field_validator("activity_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> Any:
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            msg = "Enter a valid date."
            raise ValueError(msg) from exc

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def parse_time(cls, value: Any) -> Any:
        # <input type="time"> posts "HH:MM" (some browsers add ":SS").
        if isinstance(value, time):
            return value
        text = str(value or "").strip()
        try:
            return time.fromisoformat(text)
        except ValueError as exc:
            msg = "Enter a valid time (HH:MM)."
            raise ValueError(msg) from exc

    @field_validator("max_volunteers", mode="before")
    @classmethod
    def parse_int(cls, value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        text = str(value or "").strip()
        if not text.lstrip("-").isdigit():
            msg = "Enter a whole number."
            raise ValueError(msg)
        return int(text)

    # ---------------------------------------------------------------- rules
    @field_validator("activity_date")
    @classmethod
    def not_in_the_past_when_creating(cls, value: date, info: ValidationInfo) -> date:
        context = info.context or {}
        if context.get("creating"):
            today: date = context.get("today") or date.today()
            if value < today:
                msg = "Activity date cannot be in the past."
                raise ValueError(msg)
        return value

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, value: time, info: ValidationInfo) -> time:
        # `start_time` is missing from info.data when it failed its own parsing.
        start = info.data.get("start_time")
        if start is not None and value <= start:
            msg = "End time must be after start time."
            raise ValueError(msg)
        return value
