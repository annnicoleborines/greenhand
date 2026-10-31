"""RegistrationService: a volunteer signs up for an activity (FR-3, FR-6).

Rules from the brief, all checked inside ONE database transaction:
- VOLUNTEER only (`require_role`, checked here as well as on the route).
- The activity row is locked first (`ActivityDAO.lock_for_update`, SELECT ... FOR
  UPDATE), so two volunteers racing for the last slot queue up: the second one
  waits for the first to commit, then sees the slot gone and is refused.
- The activity must be OPEN and not started yet.
- One row per (activity, volunteer): a PENDING / APPROVED row means "already
  registered"; a CANCELLED row is re-used (`reopen`, back to PENDING, same id);
  REJECTED and COMPLETED are final, no second registration.
- Slots are never stored: PENDING + APPROVED rows are counted under the lock.
- The new / re-opened registration, the audit entry (REGISTRATION_CREATED) and one
  notification per administrator are written together, or not at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.auth.roles import require_role
from app.dao import ActivityDAO, AuditLogDAO, NotificationDAO, RegistrationDAO, UserDAO
from app.database import DatabaseManager
from app.errors import ConflictError, NotFoundError
from app.models import (
    SLOT_TAKING_STATUSES,
    Activity,
    ActivityStatus,
    AuditLog,
    Person,
    Registration,
    RegistrationStatus,
    RoleName,
)

log = logging.getLogger(__name__)

NOTIFICATION_TYPE_SUBMITTED = "REGISTRATION_SUBMITTED"
MSG_NOT_OPEN = "This activity is not open for registration."
MSG_ALREADY = "You are already registered for this activity."
MSG_FINAL = "You cannot register for this activity again."
MSG_FULL = "This activity is full."
MSG_NOT_FOUND = "Activity not found."


@dataclass
class RegistrationService:
    db: DatabaseManager
    activities: ActivityDAO
    registrations: RegistrationDAO
    users: UserDAO
    notifications: NotificationDAO
    audit: AuditLogDAO

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> RegistrationService:
        """Convenience constructor used by controllers."""
        manager = db or DatabaseManager()
        return cls(
            db=manager,
            activities=ActivityDAO(manager),
            registrations=RegistrationDAO(manager),
            users=UserDAO(manager),
            notifications=NotificationDAO(manager),
            audit=AuditLogDAO(manager),
        )

    # ----------------------------------------------------------------- read
    def registration_for(self, actor: Person, activity_id: int) -> Registration | None:
        """The actor's own registration row for this activity, if any (details page state)."""
        if actor.role_name != RoleName.VOLUNTEER:
            return None  # admins never have one
        return self.registrations.find_by_activity_and_user(activity_id, actor.id or 0)

    @staticmethod
    def can_register(
        activity: Activity, existing: Registration | None, now: datetime | None = None
    ) -> bool:
        """Pure rule used by the template to decide whether to show the Register button."""
        if activity.status != ActivityStatus.OPEN or activity.has_started(now):
            return False
        if existing is not None and existing.status != RegistrationStatus.CANCELLED:
            return False
        return not activity.is_full

    # ------------------------------------------------------------- register
    def register(
        self, actor: Person, activity_id: int, *, now: datetime | None = None
    ) -> Registration:
        """Create (or re-open) a PENDING registration; raise a typed error otherwise."""
        require_role(actor, RoleName.VOLUNTEER)
        now = now or datetime.now()
        user_id = actor.id or 0

        with self.db.transaction():
            # 1. Lock the activity row: every other registration for it now waits here.
            activity = self.activities.lock_for_update(activity_id)
            if activity is None:
                raise NotFoundError(MSG_NOT_FOUND)

            # 2. OPEN and not started.
            if activity.status != ActivityStatus.OPEN or activity.has_started(now):
                raise ConflictError(MSG_NOT_OPEN)

            # 3. One row per volunteer and activity.
            existing = self.registrations.find_by_activity_and_user(activity_id, user_id)
            if existing is not None and existing.status in SLOT_TAKING_STATUSES:
                raise ConflictError(MSG_ALREADY)
            if existing is not None and existing.status != RegistrationStatus.CANCELLED:
                raise ConflictError(MSG_FINAL)  # REJECTED / COMPLETED stay final

            # 4. Slots, counted under the lock with a locking read so the number is
            #    the latest committed one, not a snapshot taken before we waited.
            taken = self.registrations.count_slot_taking(activity_id, for_update=True)
            if taken >= activity.max_volunteers:
                raise ConflictError(MSG_FULL)

            # 5. Insert, or re-use the cancelled row.
            if existing is None:
                registration = Registration(
                    activity_id=activity_id,
                    user_id=user_id,
                    status=RegistrationStatus.PENDING,
                    registration_date=now,
                    activity_title=activity.title,
                    volunteer_name=actor.full_name,
                )
                # A duplicate slipped in between the check and the insert is caught by
                # UNIQUE(activity_id, user_id): MySQL error 1062 becomes ConflictError.
                self.registrations.insert(registration)
                details = f"Registered for activity {activity.title} (PENDING)."
            else:
                self.registrations.reopen(existing.id or 0)
                registration = existing
                registration.status = RegistrationStatus.PENDING
                registration.registration_date = now
                registration.reviewed_at = None
                registration.reviewed_by = None
                registration.remarks = None
                details = (
                    f"Registered again for activity {activity.title} after cancelling (PENDING)."
                )

            # 6. Audit + tell every administrator, in the same transaction.
            self.audit.insert(
                AuditLog(
                    user_id=user_id,
                    action="REGISTRATION_CREATED",
                    entity="registration",
                    record_reference=registration.id,
                    details=details,
                )
            )
            message = (
                f"{actor.full_name} registered for {activity.title} on "
                f"{activity.activity_date.isoformat()}. Review it under Registrations."
            )
            self.notifications.insert_many(
                self.users.list_admin_ids(), NOTIFICATION_TYPE_SUBMITTED, message
            )

        log.info(
            "registration created",
            extra={"user_id": user_id, "action": "REGISTRATION_CREATED"},
        )
        return registration
