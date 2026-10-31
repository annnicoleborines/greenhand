from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models.base_entity import BaseEntity


@dataclass(kw_only=True)
class VolunteerProfile(BaseEntity):
    """volunteer_profiles table: extra details that only volunteers have."""

    user_id: int
    address: str | None = None
    birth_date: date | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
