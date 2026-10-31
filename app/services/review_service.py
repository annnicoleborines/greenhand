"""RegistrationReviewService: admins approve or reject pending registrations (FR-3, FR-6).

Rules from the brief:
- Every method is ADMIN-only (`require_role`, checked here as well as on the route).
- Only a PENDING registration can be reviewed; a second click on Approve or Reject
  is refused with a clear message instead of silently overwriting the first review.
- Approve re-checks capacity under the same activity row lock that registration
  uses (`ActivityDAO.lock_for_update`): the number of APPROVED volunteers may not
  reach `max_volunteers`, and a CANCELLED or COMPLETED activity takes no approvals.
- Reject requires remarks (RejectSchema); the volunteer reads them in the notification.
- `reviewed_by` / `reviewed_at` / `remarks` are stored, the volunteer is notified
  (REGISTRATION_APPROVED / REGISTRATION_REJECTED) and an audit entry is written,
  all in one transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.auth.roles import require_role
from app.dao import ActivityDAO, AuditLogDAO, NotificationDAO, RegistrationDAO
from app.database import DatabaseManager
from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    Activity,
    ActivityStatus,
    AuditLog,
    Notification,
    Person,
    Registration,
    RegistrationStatus,
    RoleName,
)
from app.schemas.base import validate
from app.schemas.review import REMARKS_MESSAGE, RejectSchema
from app.services.pagination import Page, clamp_page, offset_for

log = logging.getLogger(__name__)

DEFAULT_PER_PAGE = 20
NOTIFICATION_TYPE_APPROVED = "REGISTRATION_APPROVED"
NOTIFICATION_TYPE_REJECTED = "REGISTRATION_REJECTED"
MSG_NOT_PENDING = "Only pending registrations can be reviewed; this one is already {status}."
MSG_ACTIVITY_OVER = "This activity is {status}; its registrations can no longer be approved."
MSG_NO_CAPACITY = "Every slot of this activity is already approved."
MSG_NOT_FOUND = "Registration not found."
# Review is only meaningful while the activity can still happen.
NO_APPROVAL_STATUSES = frozenset({ActivityStatus.CANCELLED, ActivityStatus.COMPLETED})


@dataclass
class RegistrationReviewService:
    db: DatabaseManager
    registrations: RegistrationDAO
    activities: ActivityDAO
    notifications: NotificationDAO
    audit: AuditLogDAO

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> RegistrationReviewService:
        """Convenience constructor used by controllers."""
        manager = db or DatabaseManager()
        return cls(
            db=manager,
            registrations=RegistrationDAO(manager),
            activities=ActivityDAO(manager),
            notifications=NotificationDAO(manager),
            audit=AuditLogDAO(manager),
        )

    # ----------------------------------------------------------------- read
    def list_page(
        self,
        actor: Person,
        status: RegistrationStatus | None = RegistrationStatus.PENDING,
        page: int = 1,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> Page[Registration]:
        """One page of registrations, oldest first; `status=None` means every status."""
        require_role(actor, RoleName.ADMIN)
        page = clamp_page(page)
        items = self.registrations.search(
            status=status, limit=per_page, offset=offset_for(page, per_page)
        )
        total = self.registrations.count_search(status=status)
        return Page(items=items, page=page, per_page=per_page, total=total)

    def get(self, actor: Person, registration_id: int) -> Registration:
        require_role(actor, RoleName.ADMIN)
        registration = self.registrations.find_by_id(registration_id)
        if registration is None:
            raise NotFoundError(MSG_NOT_FOUND)
        return registration

    # -------------------------------------------------------------- approve
    def approve(
        self, actor: Person, registration_id: int, *, now: datetime | None = None
    ) -> Registration:
        """PENDING -> APPROVED, after re-checking the activity's capacity under its row lock."""
        require_role(actor, RoleName.ADMIN)
        now = now or datetime.now()

        with self.db.transaction():
            registration, activity = self._lock_pending(registration_id)
            if activity.status in NO_APPROVAL_STATUSES:
                raise ConflictError(MSG_ACTIVITY_OVER.format(status=activity.status.value))
            approved = self.registrations.count_for_activity(
                activity.id or 0, [RegistrationStatus.APPROVED], for_update=True
            )
            if approved >= activity.max_volunteers:
                raise ConflictError(MSG_NO_CAPACITY)

            self._review(
                actor,
                registration,
                activity,
                status=RegistrationStatus.APPROVED,
                now=now,
                remarks=None,
                notification_type=NOTIFICATION_TYPE_APPROVED,
                message=(
                    f"Your registration for {activity.title} on "
                    f"{activity.activity_date.isoformat()} was approved. See you there!"
                ),
                audit_action="REGISTRATION_APPROVED",
                details=f"Approved {registration.volunteer_name} for {activity.title}.",
            )
        log.info(
            "registration approved",
            extra={"user_id": actor.id, "action": "REGISTRATION_APPROVED"},
        )
        return registration

    # --------------------------------------------------------------- reject
    def reject(
        self,
        actor: Person,
        registration_id: int,
        form: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> Registration:
        """PENDING -> REJECTED with the admin's remarks (required)."""
        require_role(actor, RoleName.ADMIN)
        now = now or datetime.now()
        try:
            data = validate(RejectSchema, form)
        except ValidationError as exc:
            # One field, one message: the controller shows it as a flash.
            raise ValidationError(REMARKS_MESSAGE, {"remarks": REMARKS_MESSAGE}) from exc

        with self.db.transaction():
            registration, activity = self._lock_pending(registration_id)
            self._review(
                actor,
                registration,
                activity,
                status=RegistrationStatus.REJECTED,
                now=now,
                remarks=data.remarks,
                notification_type=NOTIFICATION_TYPE_REJECTED,
                message=(
                    f"Your registration for {activity.title} on "
                    f"{activity.activity_date.isoformat()} was rejected. Remarks: {data.remarks}"
                ),
                audit_action="REGISTRATION_REJECTED",
                details=f"Rejected {registration.volunteer_name} for {activity.title}.",
            )
        log.info(
            "registration rejected",
            extra={"user_id": actor.id, "action": "REGISTRATION_REJECTED"},
        )
        return registration

    # -------------------------------------------------------------- helpers
    def _lock_pending(self, registration_id: int) -> tuple[Registration, Activity]:
        """Lock the activity row, then re-read the registration; it must still be PENDING.

        Must run inside `db.transaction()`. The registration is read once to learn its
        activity, the activity is locked, and the registration is read again so the
        status we check is the one every other reviewer and registrant also waited for.
        """
        first = self.registrations.find_by_id(registration_id)
        if first is None:
            raise NotFoundError(MSG_NOT_FOUND)
        activity = self.activities.lock_for_update(first.activity_id)
        registration = self.registrations.find_by_id(registration_id)
        if activity is None or registration is None:  # deleted between the two reads
            raise NotFoundError(MSG_NOT_FOUND)
        if registration.status != RegistrationStatus.PENDING:
            raise ConflictError(MSG_NOT_PENDING.format(status=registration.status.value))
        return registration, activity

    def _review(
        self,
        actor: Person,
        registration: Registration,
        activity: Activity,
        *,
        status: RegistrationStatus,
        now: datetime,
        remarks: str | None,
        notification_type: str,
        message: str,
        audit_action: str,
        details: str,
    ) -> None:
        """Write the review, the volunteer's notification and the audit entry together."""
        self.registrations.review(
            registration.id or 0,
            status=status,
            reviewed_by=actor.id or 0,
            reviewed_at=now,
            remarks=remarks,
        )
        registration.status = status
        registration.reviewed_by = actor.id
        registration.reviewed_at = now
        registration.remarks = remarks
        self.notifications.insert(
            Notification(user_id=registration.user_id, type=notification_type, message=message)
        )
        self.audit.insert(
            AuditLog(
                user_id=actor.id or 0,
                action=audit_action,
                entity="registration",
                record_reference=registration.id,
                details=details,
            )
        )
