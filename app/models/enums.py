"""Enumerations that mirror the ENUM columns in database/schema.sql.

`StrEnum` means `UserStatus.ACTIVE == "ACTIVE"`, so values read from MySQL
compare directly and templates can print them as text.
"""

from __future__ import annotations

from enum import StrEnum


class RoleName(StrEnum):
    VOLUNTEER = "VOLUNTEER"
    ADMIN = "ADMIN"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ActivityStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class RegistrationStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


# Registrations in these states occupy a slot:
# available = max_volunteers - count(PENDING + APPROVED)
SLOT_TAKING_STATUSES: frozenset[RegistrationStatus] = frozenset(
    {RegistrationStatus.PENDING, RegistrationStatus.APPROVED}
)
