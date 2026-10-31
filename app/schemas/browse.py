"""Pydantic schema for the browse-activities filter form (FR-4).

This form is different from the others: it is a GET form, so its values arrive
in the URL (?keyword=...&location_id=...&page=...). A typo in the URL must never
show an error page; we just ignore the bad value and show the unfiltered list.
That is why `from_query` exists: it validates and *drops* anything invalid
instead of raising. Controllers call `BrowseFilterSchema.from_query(request.args)`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

KEYWORD_MAX = 100
FILTER_FIELDS = ("keyword", "location_id", "activity_date", "page")


class BrowseFilterSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    keyword: str | None = Field(default=None, max_length=KEYWORD_MAX)
    location_id: int | None = None
    activity_date: date | None = None
    page: int = Field(default=1, ge=1)

    @field_validator("keyword", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> Any:
        # An empty search box arrives as ""; treat it as "no keyword filter".
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("location_id", mode="before")
    @classmethod
    def parse_location(cls, value: Any) -> Any:
        # The <select> posts "" for "All locations" and a number otherwise.
        # Anything that is not a positive whole number means "no location filter".
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        text = str(value).strip()
        if not text.isdigit():
            return None
        return int(text) if int(text) > 0 else None

    @field_validator("activity_date", mode="before")
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
        except ValueError:
            return None  # a hand-typed bad date is simply ignored

    @field_validator("page", mode="before")
    @classmethod
    def parse_page(cls, value: Any) -> Any:
        # ?page=abc or ?page=0 should land on page 1, not on an error page.
        if value is None or isinstance(value, bool):
            return 1
        if isinstance(value, int):
            return value if value >= 1 else 1
        text = str(value).strip()
        if not text.isdigit():
            return 1
        return max(int(text), 1)

    @classmethod
    def from_query(cls, args: Mapping[str, Any]) -> BrowseFilterSchema:
        """Build filters from the query string, dropping any value that fails validation.

        The `mode="before"` validators above already swallow most bad input. This
        method catches whatever still fails (for example a keyword over 100
        characters), removes those fields and validates again, so the caller
        always gets a usable schema and never a ValidationError.
        """
        data: dict[str, Any] = {name: args.get(name) for name in FILTER_FIELDS if name in args}
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            for err in exc.errors():
                for part in err["loc"]:
                    data.pop(str(part), None)
            return cls.model_validate(data)

    @property
    def is_filtered(self) -> bool:
        """True when any filter (not the page number) is set; drives the clear-filters link."""
        return any(
            value is not None for value in (self.keyword, self.location_id, self.activity_date)
        )

    def as_query_args(self) -> dict[str, Any]:
        """The set filters as url_for kwargs, so pagination links keep them."""
        args: dict[str, Any] = {}
        if self.keyword is not None:
            args["keyword"] = self.keyword
        if self.location_id is not None:
            args["location_id"] = self.location_id
        if self.activity_date is not None:
            args["activity_date"] = self.activity_date.isoformat()
        return args
