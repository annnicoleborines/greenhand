from __future__ import annotations

from dataclasses import dataclass, field

from app.models.base_entity import BaseEntity


@dataclass(kw_only=True)
class Location(BaseEntity):
    """locations table: a place that hosts zero or many activities."""

    location_name: str
    address: str
    details: str | None = None

    # NOT a column: LocationDAO.list_with_activity_counts() fills it from a COUNT
    # so the admin list can show "3 activities" without one query per row.
    activity_count: int = field(default=0, compare=False)
