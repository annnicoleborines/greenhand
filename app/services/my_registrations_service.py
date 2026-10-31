"""MyRegistrationsService: a volunteer's own registrations, schedule and cancellations (FR-3, FR-6).

Rules from the brief:
- Every method is VOLUNTEER-only (`require_role`, checked here as well as on the route),
  and a volunteer only ever sees or changes their OWN rows (the user id comes from
  the logged-in actor, never from the request; someone else's id is a 404).
- Cancel is allowed only for PENDING / APPROVED registrations whose activity has not
  started (`Registration.can_cancel`). It runs under the activity row lock, like
  registering and reviewing, so the slot count every other request sees is right.
- Cancelling notifies every administrator (REGISTRATION_CANCELLED) and writes an
  audit entry in the same transaction. Registering again later re-uses the row
  (Phase 5).
- The schedule splits the volunteer's rows into "upcoming" (PENDING / APPROVED,
  activity today or later) and "history" (activities that already happened or were
  marked COMPLETED); rejected and cancelled rows never appear in the history.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from app.auth.roles import require_role
from app.dao import ActivityDAO, AuditLogDAO, NotificationDAO, RegistrationDAO, UserDAO
from app.database import DatabaseManager
from app.errors import ConflictError, NotFoundError
from app.models import (
    SLOT_TAKING_STATUSES,
    AuditLog,
    Person,
    Registration,
    RegistrationStatus,
    RoleName,
)

log = logging.getLogger(__name__)

NOTIFICATION_TYPE_CANCELLED = "REGISTRATION_CANCELLED"
MSG_NOT_FOUND = "Registration not found."
MSG_NOT_CANCELLABLE = "This registration can no longer be cancelled; it is {status}."
MSG_STARTED = "The activity has already started, so the registration cannot be cancelled."
HISTORY_STATUSES = frozenset(
    {RegistrationStatus.APPROVED, RegistrationStatus.COMPLETED, RegistrationStatus.PENDING}
)


@dataclass
class MyRegistrations:
    """The list page: the rows for the chosen tab plus a count per status for the tabs."""

    items: list[Registration]
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass
class Schedule:
    upcoming: list[Registration] = field(default_factory=list)
    history: list[Registration] = field(default_factory=list)

    @property
    def hours(self) -> float:
        """Hours of activities that happened (APPROVED or COMPLETED rows in the history)."""
        done = (RegistrationStatus.APPROVED, RegistrationStatus.COMPLETED)
        return round(sum(r.activity_hours for r in self.history if r.status in done), 2)


@dataclass
class MyRegistrationsService:
    db: DatabaseManager
    registrations: RegistrationDAO
    activities: ActivityDAO
    users: UserDAO
    notifications: NotificationDAO
    audit: AuditLogDAO

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> MyRegistrationsService:
        """Convenience constructor used by controllers."""
        manager = db or DatabaseManager()
        return cls(
            db=manager,
            registrations=RegistrationDAO(manager),
            activities=ActivityDAO(manager),
            users=UserDAO(manager),
            notifications=NotificationDAO(manager),
            audit=AuditLogDAO(manager),
        )

    # ----------------------------------------------------------------- read
    def list_mine(self, actor: Person, status: RegistrationStatus | None = None) -> MyRegistrations:
        """The actor's registrations (newest first), filtered to one status, plus tab counts."""
        require_role(actor, RoleName.VOLUNTEER)
        rows = self.registrations.list_by_user(actor.id or 0)
        counts = {s.value: 0 for s in RegistrationStatus}
        for row in rows:
            counts[row.status.value] += 1
        items = [r for r in rows if status is None or r.status == status]
        return MyRegistrations(items=items, counts=counts)

    def schedule(self, actor: Person, today: date | None = None) -> Schedule:
        """Upcoming (soonest first) and history (most recent first) from the actor's rows."""
        require_role(actor, RoleName.VOLUNTEER)
        today = today or date.today()
        schedule = Schedule()
        for row in self.registrations.list_by_user(actor.id or 0):
            if row.activity_date is None:  # cannot happen with the join, but never crash
                continue
            if row.status in SLOT_TAKING_STATUSES and row.activity_date >= today:
                schedule.upcoming.append(row)
            elif row.status == RegistrationStatus.COMPLETED or (
                row.status in HISTORY_STATUSES and row.activity_date < today
            ):
                schedule.history.append(row)
        schedule.upcoming.sort(
            key=lambda r: (r.activity_date or today, r.activity_start_time or datetime.min.time())
        )
        schedule.history.sort(
            key=lambda r: (r.activity_date or today, r.activity_start_time or datetime.min.time()),
            reverse=True,
        )
        return schedule

    # --------------------------------------------------------------- cancel
    def cancel(
        self, actor: Person, registration_id: int, *, now: datetime | None = None
    ) -> Registration:
        """PENDING / APPROVED -> CANCELLED before the activity starts; admins are told."""
        require_role(actor, RoleName.VOLUNTEER)
        now = now or datetime.now()
        user_id = actor.id or 0

        with self.db.transaction():
            first = self.registrations.find_by_id(registration_id)
            if first is None or first.user_id != user_id:
                raise NotFoundError(MSG_NOT_FOUND)  # not theirs: do not reveal it exists
            # Same lock order as registering and reviewing: activity row first.
            activity = self.activities.lock_for_update(first.activity_id)
            registration = self.registrations.find_by_id(registration_id)
            if activity is None or registration is None:
                raise NotFoundError(MSG_NOT_FOUND)
            if not registration.can_be_cancelled:
                raise ConflictError(MSG_NOT_CANCELLABLE.format(status=registration.status.value))
            if activity.has_started(now):
                raise ConflictError(MSG_STARTED)

            previous = registration.status.value
            self.registrations.set_status(registration_id, RegistrationStatus.CANCELLED)
            registration.status = RegistrationStatus.CANCELLED
            self.audit.insert(
                AuditLog(
                    user_id=user_id,
                    action="REGISTRATION_CANCELLED",
                    entity="registration",
                    record_reference=registration.id,
                    details=(
                        f"Cancelled registration for {activity.title} ({previous} -> CANCELLED)."
                    ),
                )
            )
            message = (
                f"{actor.full_name} cancelled their {previous.lower()} registration for "
                f"{activity.title} on {activity.activity_date.isoformat()}."
            )
            self.notifications.insert_many(
                self.users.list_admin_ids(), NOTIFICATION_TYPE_CANCELLED, message
            )

        log.info(
            "registration cancelled",
            extra={"user_id": user_id, "action": "REGISTRATION_CANCELLED"},
        )
        return registration
