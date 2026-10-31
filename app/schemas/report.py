"""Pydantic schemas for the report and audit-log filter forms (FR-4).

Like the browse filters, these are GET forms: their values arrive in the URL, so a
hand-typed bad value must never show an error page. `from_query()` validates and
*drops* whatever is invalid, then validates again, so callers always get a usable
schema. A date range given backwards simply loses its end date.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.models import ActivityStatus

TEXT_MAX = 50


def _parse_date(value: Any) -> Any:
    """'YYYY-MM-DD' -> date; blank or unreadable -> None (the filter is ignored)."""
    if value is None or isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class _TolerantFilters(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date_from: date | None = None
    date_to: date | None = None

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def parse_dates(cls, value: Any) -> Any:
        return _parse_date(value)

    @model_validator(mode="after")
    def drop_backwards_range(self) -> _TolerantFilters:
        if self.date_from and self.date_to and self.date_to < self.date_from:
            self.date_to = None
        return self

    @classmethod
    def from_query(cls, args: Mapping[str, Any]) -> Self:
        data: dict[str, Any] = {name: args.get(name) for name in cls.model_fields if name in args}
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            for err in exc.errors():
                for part in err["loc"]:
                    data.pop(str(part), None)
            return cls.model_validate(data)

    def as_query_args(self) -> dict[str, Any]:
        """The set filters as url_for kwargs (CSV / print links keep the same view)."""
        args: dict[str, Any] = {}
        for name in type(self).model_fields:
            value = getattr(self, name)
            if value is None or name == "page":
                continue
            args[name] = value.isoformat() if isinstance(value, date) else str(value)
        return args

    @property
    def is_filtered(self) -> bool:
        return any(
            getattr(self, name) is not None for name in type(self).model_fields if name != "page"
        )


class ReportFilterSchema(_TolerantFilters):
    """Filters for the admin reports: activity date range and activity status."""

    status: ActivityStatus | None = None

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value: Any) -> Any:
        text = _blank_to_none(value)
        if text is None:
            return None
        try:
            return ActivityStatus(str(text).upper())
        except ValueError:
            return None


class AuditFilterSchema(_TolerantFilters):
    """Filters for the audit log viewer: action code, username, date range, page."""

    action: str | None = Field(default=None, max_length=TEXT_MAX)
    username: str | None = Field(default=None, max_length=TEXT_MAX)
    page: int = Field(default=1, ge=1)

    @field_validator("action", mode="before")
    @classmethod
    def upper_action(cls, value: Any) -> Any:
        text = _blank_to_none(value)
        return str(text).upper() if text is not None else None

    @field_validator("username", mode="before")
    @classmethod
    def clean_username(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("page", mode="before")
    @classmethod
    def parse_page(cls, value: Any) -> Any:
        if value is None or isinstance(value, bool):
            return 1
        if isinstance(value, int):
            return max(value, 1)
        text = str(value).strip()
        return max(int(text), 1) if text.isdigit() else 1
