from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time

from app.models.base_entity import BaseEntity
from app.models.enums import SLOT_TAKING_STATUSES, ActivityStatus, RegistrationStatus


@dataclass(kw_only=True)
class Registration(BaseEntity):
    """registrations table: one volunteer signed up for one activity.

    UNIQUE(activity_id, user_id): a volunteer has at most one row per activity.
    Cancel + register again re-uses the row (status goes back to PENDING).
    """

    activity_id: int
    user_id: int
    status: RegistrationStatus = RegistrationStatus.PENDING
    registration_date: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by: int | None = None
    remarks: str | None = None

    # Filled by joins for list pages (not stored here)
    activity_title: str | None = field(default=None, compare=False)
    activity_date: date | None = field(default=None, compare=False)
    activity_start_time: time | None = field(default=None, compare=False)
    activity_end_time: time | None = field(default=None, compare=False)
    activity_status: ActivityStatus | None = field(default=None, compare=False)
    location_name: str | None = field(default=None, compare=False)
    volunteer_name: str | None = field(default=None, compare=False)

    @property
    def takes_slot(self) -> bool:
        return self.status in SLOT_TAKING_STATUSES

    @property
    def can_be_cancelled(self) -> bool:
        return self.status in SLOT_TAKING_STATUSES

    @property
    def activity_starts_at(self) -> datetime | None:
        """When the activity begins, from the joined columns (None when not joined)."""
        if self.activity_date is None or self.activity_start_time is None:
            return None
        return datetime.combine(self.activity_date, self.activity_start_time)

    def activity_has_started(self, now: datetime | None = None) -> bool:
        starts_at = self.activity_starts_at
        return starts_at is not None and starts_at <= (now or datetime.now())

    def can_cancel(self, now: datetime | None = None) -> bool:
        """Brief: only PENDING / APPROVED, and only before the activity starts."""
        return self.can_be_cancelled and not self.activity_has_started(now)

    @property
    def activity_hours(self) -> float:
        if self.activity_start_time is None or self.activity_end_time is None:
            return 0.0
        delta = datetime.combine(date.min, self.activity_end_time) - datetime.combine(
            date.min, self.activity_start_time
        )
        return round(delta.total_seconds() / 3600, 2)
