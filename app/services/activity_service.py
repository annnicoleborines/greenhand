"""ActivityService: admins create, edit, cancel and delete tree-planting activities.

Rules from the brief:
- Every method is ADMIN-only (`require_role`, checked here as well as on the route).
- The form is validated by ActivitySchema (FR-4); two rules need the database and
  are checked here: the location must exist, and on edit `max_volunteers` may not
  drop below the slots volunteers already hold.
- Deleting an activity that has ANY registration does not delete it. It becomes
  CANCELLED, every PENDING / APPROVED registrant gets a notification, and the
  audit action is ACTIVITY_CANCELLED. Only an activity nobody ever registered
  for is really deleted (ACTIVITY_DELETED). Setting the status to CANCELLED by
  hand follows the same cancel path.
- Every create / update / delete / cancel / status change writes an audit_logs
  entry in the same transaction (FR-6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.auth.roles import require_role
from app.dao import ActivityDAO, AuditLogDAO, LocationDAO, NotificationDAO, RegistrationDAO
from app.database import DatabaseManager
from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import Activity, ActivityStatus, AuditLog, Person, RegistrationStatus, RoleName
from app.schemas.activity import LOCATION_MESSAGE, ActivitySchema
from app.schemas.base import validate
from app.services.pagination import Page, clamp_page, offset_for

log = logging.getLogger(__name__)

ACTIVITY_FIELDS = (
    "location_id",
    "title",
    "description",
    "activity_date",
    "start_time",
    "end_time",
    "max_volunteers",
    "requirements",
)
NOTIFICATION_TYPE_CANCELLED = "ACTIVITY_CANCELLED"
# Registrants in these states still hold a slot, so they are told about a cancellation.
# (Same members as SLOT_TAKING_STATUSES, written out so the order is fixed.)
CANCEL_NOTIFY_STATUSES = (RegistrationStatus.PENDING, RegistrationStatus.APPROVED)
DEFAULT_PER_PAGE = 10


@dataclass
class ActivityService:
    db: DatabaseManager
    activities: ActivityDAO
    locations: LocationDAO
    registrations: RegistrationDAO
    notifications: NotificationDAO
    audit: AuditLogDAO

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> ActivityService:
        """Convenience constructor used by controllers."""
        manager = db or DatabaseManager()
        return cls(
            db=manager,
            activities=ActivityDAO(manager),
            locations=LocationDAO(manager),
            registrations=RegistrationDAO(manager),
            notifications=NotificationDAO(manager),
            audit=AuditLogDAO(manager),
        )

    # --------------------------------------------------------------- read
    def list_page(
        self,
        actor: Person,
        status: ActivityStatus | None = None,
        page: int = 1,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> Page[Activity]:
        """One page of activities for the admin list; `status=None` means all of them."""
        require_role(actor, RoleName.ADMIN)
        page = clamp_page(page)
        items = self.activities.search(
            status=status, limit=per_page, offset=offset_for(page, per_page)
        )
        total = self.activities.count_search(status=status)
        return Page(items=items, page=page, per_page=per_page, total=total)

    def get(self, actor: Person, activity_id: int) -> Activity:
        require_role(actor, RoleName.ADMIN)
        activity = self.activities.find_by_id(activity_id)
        if activity is None:
            msg = "Activity not found."
            raise NotFoundError(msg)
        return activity

    # ------------------------------------------------------------- create
    def create(self, actor: Person, form: dict[str, Any], *, today: date | None = None) -> Activity:
        """Validate (date must be today or later), then insert the row + audit entry."""
        require_role(actor, RoleName.ADMIN)
        data = validate(
            ActivitySchema, form, context={"today": today or date.today(), "creating": True}
        )
        self._check_location_exists(data.location_id)

        activity = Activity(
            created_by=actor.id or 0,
            location_id=data.location_id,
            title=data.title,
            description=data.description,
            activity_date=data.activity_date,
            start_time=data.start_time,
            end_time=data.end_time,
            max_volunteers=data.max_volunteers,
            requirements=data.requirements,
            status=ActivityStatus.OPEN,
        )
        activity.validate()  # the model's own copy of the database CHECK rules
        with self.db.transaction():
            self.activities.insert(activity)
            self._audit(actor, "ACTIVITY_CREATED", activity, f"Created activity {activity.title}.")
        log.info("activity created", extra={"user_id": actor.id, "action": "ACTIVITY_CREATED"})
        return activity

    # ------------------------------------------------------------- update
    def update(self, actor: Person, activity_id: int, form: dict[str, Any]) -> Activity:
        """Validate (any date allowed), keep capacity >= taken slots, then save + audit."""
        require_role(actor, RoleName.ADMIN)
        activity = self.get(actor, activity_id)
        data = validate(ActivitySchema, form, context={"creating": False})
        self._check_location_exists(data.location_id)

        if data.max_volunteers < activity.taken_slots:
            msg = f"{activity.taken_slots} volunteers already hold slots."
            raise ValidationError(msg, {"max_volunteers": msg})

        changed = [f for f in ACTIVITY_FIELDS if getattr(activity, f) != getattr(data, f)]
        if not changed:
            return activity  # nothing to save, nothing to audit

        for name in ACTIVITY_FIELDS:
            setattr(activity, name, getattr(data, name))
        activity.validate()
        with self.db.transaction():
            self.activities.update(activity)
            self._audit(actor, "ACTIVITY_UPDATED", activity, "Changed: " + ", ".join(changed) + ".")
        log.info("activity updated", extra={"user_id": actor.id, "action": "ACTIVITY_UPDATED"})
        return activity

    # ---------------------------------------------------- delete / cancel
    def delete_or_cancel(self, actor: Person, activity_id: int) -> str:
        """Return "deleted" when the row is gone, "cancelled" when registrations exist."""
        require_role(actor, RoleName.ADMIN)
        activity = self.get(actor, activity_id)

        if self.activities.registration_count(activity_id) > 0:
            self._cancel(actor, activity)
            return "cancelled"

        with self.db.transaction():
            self.activities.delete(activity_id)
            self._audit(actor, "ACTIVITY_DELETED", activity, f"Deleted activity {activity.title}.")
        log.info("activity deleted", extra={"user_id": actor.id, "action": "ACTIVITY_DELETED"})
        return "deleted"

    def change_status(self, actor: Person, activity_id: int, new_status: str) -> Activity:
        """Move an activity to OPEN / CLOSED / COMPLETED / CANCELLED (the last one notifies)."""
        require_role(actor, RoleName.ADMIN)
        activity = self.get(actor, activity_id)
        try:
            status = ActivityStatus(str(new_status or "").strip().upper())
        except ValueError as exc:
            msg = "Choose a valid status."
            raise ValidationError(msg, {"status": msg}) from exc

        if status == activity.status:
            msg = f"The activity is already {status.value}."
            raise ConflictError(msg)

        if status == ActivityStatus.CANCELLED:
            self._cancel(actor, activity)
            return activity

        details = f"{activity.status.value} -> {status.value}"
        with self.db.transaction():
            self.activities.set_status(activity_id, status)
            activity.status = status
            self._audit(actor, "ACTIVITY_STATUS_CHANGED", activity, details)
        log.info(
            "activity status changed",
            extra={"user_id": actor.id, "action": "ACTIVITY_STATUS_CHANGED"},
        )
        return activity

    # ------------------------------------------------------------ helpers
    def _cancel(self, actor: Person, activity: Activity) -> None:
        """Set CANCELLED, tell everyone still holding a slot, and audit, all together."""
        if activity.status == ActivityStatus.CANCELLED:
            msg = "The activity is already CANCELLED."
            raise ConflictError(msg)
        message = (
            f"Activity {activity.title} on {activity.activity_date.isoformat()} was cancelled."
        )
        with self.db.transaction():
            self.activities.set_status(activity.id or 0, ActivityStatus.CANCELLED)
            # REJECTED / CANCELLED / COMPLETED registrants no longer hold a slot: no message.
            user_ids = self.registrations.list_user_ids_by_activity(
                activity.id or 0, CANCEL_NOTIFY_STATUSES
            )
            notified = self.notifications.insert_many(
                user_ids, NOTIFICATION_TYPE_CANCELLED, message
            )
            previous = activity.status.value
            activity.status = ActivityStatus.CANCELLED
            self._audit(
                actor,
                "ACTIVITY_CANCELLED",
                activity,
                f"{previous} -> CANCELLED; {notified} volunteer(s) notified.",
            )
        log.info(
            "activity cancelled",
            extra={"user_id": actor.id, "action": "ACTIVITY_CANCELLED"},
        )

    def _check_location_exists(self, location_id: int) -> None:
        """A location id from the form must point at a real row (NotFound -> field error)."""
        if self.locations.find_by_id(location_id) is None:
            raise ValidationError(LOCATION_MESSAGE, {"location_id": LOCATION_MESSAGE})

    def _audit(self, actor: Person, action: str, activity: Activity, details: str) -> None:
        self.audit.insert(
            AuditLog(
                user_id=actor.id or 0,
                action=action,
                entity="activity",
                record_reference=activity.id,
                details=details,
            )
        )
