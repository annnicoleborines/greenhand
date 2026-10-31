from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time

from app.models.base_entity import BaseEntity
from app.models.enums import ActivityStatus


@dataclass(kw_only=True)
class Activity(BaseEntity):
    """activities table: a tree-planting event at one location, created by an admin.

    `taken_slots` is NOT a column. The DAO fills it from a COUNT of PENDING and
    APPROVED registrations, so `available_slots` is always computed, never stored.
    """

    created_by: int
    location_id: int
    title: str
    description: str | None = None
    activity_date: date
    start_time: time
    end_time: time
    max_volunteers: int
    requirements: str | None = None
    status: ActivityStatus = ActivityStatus.OPEN

    # Filled by joins, not stored in this table
    taken_slots: int = field(default=0, compare=False)
    location_name: str | None = field(default=None, compare=False)

    @property
    def available_slots(self) -> int:
        return max(self.max_volunteers - self.taken_slots, 0)

    @property
    def is_full(self) -> bool:
        return self.available_slots == 0

    @property
    def starts_at(self) -> datetime:
        return datetime.combine(self.activity_date, self.start_time)

    def has_started(self, now: datetime | None = None) -> bool:
        return self.starts_at <= (now or datetime.now())

    @property
    def duration_hours(self) -> float:
        delta = datetime.combine(date.min, self.end_time) - datetime.combine(
            date.min, self.start_time
        )
        return round(delta.total_seconds() / 3600, 2)

    def validate(self) -> None:
        """Python-side copy of the database CHECK rules."""
        from app.errors import ValidationError

        errors: dict[str, str] = {}
        if self.end_time <= self.start_time:
            errors["end_time"] = "End time must be after start time."
        if self.max_volunteers <= 0:
            errors["max_volunteers"] = "Max volunteers must be greater than zero."
        if errors:
            raise ValidationError("Invalid activity.", errors)
