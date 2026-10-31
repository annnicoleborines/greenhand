"""DAO layer: one class per table. ALL SQL lives here (DAO pattern)."""

from app.dao.activity_dao import ActivityDAO
from app.dao.audit_log_dao import AuditLogDAO
from app.dao.base_dao import BaseDAO
from app.dao.location_dao import LocationDAO
from app.dao.notification_dao import NotificationDAO
from app.dao.registration_dao import RegistrationDAO
from app.dao.role_dao import RoleDAO
from app.dao.user_dao import UserDAO
from app.dao.volunteer_profile_dao import VolunteerProfileDAO

__all__ = [
    "ActivityDAO",
    "AuditLogDAO",
    "BaseDAO",
    "LocationDAO",
    "NotificationDAO",
    "RegistrationDAO",
    "RoleDAO",
    "UserDAO",
    "VolunteerProfileDAO",
]
