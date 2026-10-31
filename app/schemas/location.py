"""Pydantic schema for the admin location form (FR-4: validate before saving).

Uniqueness of the name needs the database, so LocationService checks it and
raises ConflictError; this schema only knows about shape and length.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

LOCATION_NAME_MIN = 2
LOCATION_NAME_MAX = 100
ADDRESS_MAX = 255
DETAILS_MAX = 1000


class LocationSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    location_name: str = Field(min_length=LOCATION_NAME_MIN, max_length=LOCATION_NAME_MAX)
    address: str = Field(min_length=1, max_length=ADDRESS_MAX)
    details: str | None = Field(default=None, max_length=DETAILS_MAX)

    @field_validator("details", mode="before")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        # An empty <textarea> arrives as "", which we store as NULL, not as "".
        return value or None
