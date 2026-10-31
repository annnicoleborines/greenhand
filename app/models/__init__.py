"""Domain model classes (the M in MVC). Plain dataclasses, no SQL here."""

from app.models.activity import Activity
from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.models.base_entity import BaseEntity
from app.models.enums import (
    SLOT_TAKING_STATUSES,
    ActivityStatus,
    RegistrationStatus,
    RoleName,
    UserStatus,
)
from app.models.location import Location
from app.models.notification import Notification
from app.models.person import Person
from app.models.registration import Registration
from app.models.role import Role
from app.models.volunteer import Volunteer
from app.models.volunteer_profile import VolunteerProfile

__all__ = [
    "SLOT_TAKING_STATUSES",
    "Activity",
    "ActivityStatus",
    "Admin",
    "AuditLog",
    "BaseEntity",
    "Location",
    "Notification",
    "Person",
    "Registration",
    "RegistrationStatus",
    "Role",
    "RoleName",
    "UserStatus",
    "Volunteer",
    "VolunteerProfile",
]
