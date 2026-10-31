"""Unit tests for RegistrationReviewService (FR-2 role check, FR-4 remarks, FR-6 audit).

No database: the DAOs are small in-memory fakes, like tests/unit/test_registration_service.py.
Rules under test: only PENDING rows are reviewed, approve re-checks capacity under the
activity lock, reject requires remarks, and review + notification + audit are written in
one transaction.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, time

import pytest

from app.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models import (
    Activity,
    ActivityStatus,
    Admin,
    AuditLog,
    Notification,
    Registration,
    RegistrationStatus,
    RoleName,
    Volunteer,
)
from app.schemas.review import REMARKS_MESSAGE
from app.services.review_service import (
    MSG_NO_CAPACITY,
    NOTIFICATION_TYPE_APPROVED,
    NOTIFICATION_TYPE_REJECTED,
    RegistrationReviewService,
)

NOW = datetime(2030, 6, 1, 9, 0)
ACTIVITY_ID = 40
REGISTRATION_ID = 77
VOLUNTEER_ID = 7
ADMIN_ID = 1


# ----------------------------------------------------------------- fakes
class FakeDB:
    def __init__(self) -> None:
        self.transactions = 0
        self.open = False

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.transactions += 1
        self.open = True
        try:
            yield None
        finally:
            self.open = False


class FakeActivityDAO:
    def __init__(self, activity: Activity | None, db: FakeDB) -> None:
        self.activity = activity
        self.db = db
        self.locks_inside_transaction: list[bool] = []

    def lock_for_update(self, activity_id: int) -> Activity | None:
        self.locks_inside_transaction.append(self.db.open)
        return self.activity if self.activity and self.activity.id == activity_id else None


class FakeRegistrationDAO:
    def __init__(self, *rows: Registration, approved: int = 0) -> None:
        self.rows = list(rows)
        self.approved = approved
        self.reviews: list[dict[str, object]] = []
        self.count_calls: list[tuple[list[RegistrationStatus], bool]] = []
        self.search_calls: list[dict[str, object]] = []

    def find_by_id(self, registration_id: int) -> Registration | None:
        return next((r for r in self.rows if r.id == registration_id), None)

    def count_for_activity(
        self, activity_id: int, statuses: Iterable[RegistrationStatus], *, for_update: bool = False
    ) -> int:
        self.count_calls.append((list(statuses), for_update))
        return self.approved

    def review(self, registration_id: int, **fields: object) -> bool:
        self.reviews.append({"id": registration_id, **fields})
        return True

    def search(self, **filters: object) -> list[Registration]:
        self.search_calls.append(filters)
        status = filters.get("status")
        return [r for r in self.rows if status is None or r.status == status]

    def count_search(self, **filters: object) -> int:
        return len(self.search(**filters))


class FakeNotificationDAO:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def insert(self, notification: Notification) -> int:
        notification.id = len(self.sent) + 1
        self.sent.append(notification)
        return notification.id


class FakeAuditDAO:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def insert(self, entry: AuditLog) -> int:
        entry.id = len(self.entries) + 1
        self.entries.append(entry)
        return entry.id


# --------------------------------------------------------------- builders
def admin() -> Admin:
    return Admin(
        id=ADMIN_ID,
        role_id=2,
        role_name=RoleName.ADMIN,
        username="ada",
        email="a@x",
        first_name="Ada",
        last_name="Admin",
    )


def volunteer() -> Volunteer:
    return Volunteer(
        id=VOLUNTEER_ID,
        role_id=1,
        role_name=RoleName.VOLUNTEER,
        username="vicky",
        email="v@x",
        first_name="Vicky",
        last_name="Vol",
    )


def activity(*, status: ActivityStatus = ActivityStatus.OPEN, max_volunteers: int = 10) -> Activity:
    return Activity(
        id=ACTIVITY_ID,
        created_by=ADMIN_ID,
        location_id=3,
        title="Mangrove Planting",
        activity_date=date(2030, 6, 8),
        start_time=time(8, 0),
        end_time=time(11, 0),
        max_volunteers=max_volunteers,
        status=status,
    )


def registration(status: RegistrationStatus = RegistrationStatus.PENDING) -> Registration:
    return Registration(
        id=REGISTRATION_ID,
        activity_id=ACTIVITY_ID,
        user_id=VOLUNTEER_ID,
        status=status,
        activity_title="Mangrove Planting",
        volunteer_name="Vicky Vol",
    )


def make_service(
    act: Activity | None = None,
    *rows: Registration,
    approved: int = 0,
) -> tuple[
    RegistrationReviewService,
    FakeDB,
    FakeActivityDAO,
    FakeRegistrationDAO,
    FakeNotificationDAO,
    FakeAuditDAO,
]:
    db = FakeDB()
    activities = FakeActivityDAO(act, db)
    registrations = FakeRegistrationDAO(*rows, approved=approved)
    notifications = FakeNotificationDAO()
    audit = FakeAuditDAO()
    service = RegistrationReviewService(
        db=db,  # type: ignore[arg-type]
        registrations=registrations,  # type: ignore[arg-type]
        activities=activities,  # type: ignore[arg-type]
        notifications=notifications,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )
    return service, db, activities, registrations, notifications, audit


# ----------------------------------------------------------------- approve
def test_approve_reviews_notifies_volunteer_and_audits_in_one_transaction() -> None:
    row = registration()
    service, db, activities, registrations, notifications, audit = make_service(
        activity(), row, approved=4
    )

    result = service.approve(admin(), REGISTRATION_ID, now=NOW)

    assert db.transactions == 1
    assert activities.locks_inside_transaction == [True]
    assert registrations.count_calls == [([RegistrationStatus.APPROVED], True)]
    assert registrations.reviews == [
        {
            "id": REGISTRATION_ID,
            "status": RegistrationStatus.APPROVED,
            "reviewed_by": ADMIN_ID,
            "reviewed_at": NOW,
            "remarks": None,
        }
    ]
    assert result is row and row.status == RegistrationStatus.APPROVED
    assert (row.reviewed_by, row.reviewed_at, row.remarks) == (ADMIN_ID, NOW, None)

    [note] = notifications.sent
    assert (note.user_id, note.type) == (VOLUNTEER_ID, NOTIFICATION_TYPE_APPROVED)
    assert "Mangrove Planting" in note.message and "approved" in note.message
    [entry] = audit.entries
    assert (entry.user_id, entry.action, entry.entity, entry.record_reference) == (
        ADMIN_ID,
        "REGISTRATION_APPROVED",
        "registration",
        REGISTRATION_ID,
    )


def test_approve_is_refused_when_every_slot_is_already_approved() -> None:
    service, _, _, registrations, notifications, audit = make_service(
        activity(max_volunteers=3), registration(), approved=3
    )
    with pytest.raises(ConflictError, match=MSG_NO_CAPACITY):
        service.approve(admin(), REGISTRATION_ID, now=NOW)
    assert not registrations.reviews and not notifications.sent and not audit.entries


@pytest.mark.parametrize("status", [ActivityStatus.CANCELLED, ActivityStatus.COMPLETED])
def test_approve_is_refused_for_cancelled_or_completed_activities(status: ActivityStatus) -> None:
    service, _, _, registrations, *_ = make_service(activity(status=status), registration())
    with pytest.raises(ConflictError, match=status.value):
        service.approve(admin(), REGISTRATION_ID, now=NOW)
    assert not registrations.reviews


def test_approve_still_works_for_a_closed_activity() -> None:
    # CLOSED only stops new sign-ups; pending ones can still be reviewed.
    service, _, _, registrations, *_ = make_service(
        activity(status=ActivityStatus.CLOSED), registration()
    )
    service.approve(admin(), REGISTRATION_ID, now=NOW)
    assert len(registrations.reviews) == 1


@pytest.mark.parametrize(
    "status",
    [
        RegistrationStatus.APPROVED,
        RegistrationStatus.REJECTED,
        RegistrationStatus.CANCELLED,
        RegistrationStatus.COMPLETED,
    ],
)
def test_only_pending_registrations_can_be_reviewed(status: RegistrationStatus) -> None:
    service, _, _, registrations, *_ = make_service(activity(), registration(status))
    with pytest.raises(ConflictError, match=status.value):
        service.approve(admin(), REGISTRATION_ID, now=NOW)
    with pytest.raises(ConflictError, match=status.value):
        service.reject(admin(), REGISTRATION_ID, {"remarks": "Sorry, no."}, now=NOW)
    assert not registrations.reviews


def test_missing_registration_is_not_found() -> None:
    service, *_ = make_service(activity())
    with pytest.raises(NotFoundError):
        service.approve(admin(), 999, now=NOW)
    with pytest.raises(NotFoundError):
        service.reject(admin(), 999, {"remarks": "Sorry, no."}, now=NOW)


def test_volunteers_cannot_review() -> None:
    service, db, *_ = make_service(activity(), registration())
    with pytest.raises(ForbiddenError):
        service.approve(volunteer(), REGISTRATION_ID, now=NOW)
    with pytest.raises(ForbiddenError):
        service.reject(volunteer(), REGISTRATION_ID, {"remarks": "Sorry, no."}, now=NOW)
    with pytest.raises(ForbiddenError):
        service.list_page(volunteer())
    assert db.transactions == 0


# ------------------------------------------------------------------ reject
def test_reject_stores_remarks_notifies_volunteer_with_them_and_audits() -> None:
    row = registration()
    service, db, _, registrations, notifications, audit = make_service(activity(), row)

    result = service.reject(admin(), REGISTRATION_ID, {"remarks": "  Age limit is 18. "}, now=NOW)

    assert db.transactions == 1
    assert registrations.reviews == [
        {
            "id": REGISTRATION_ID,
            "status": RegistrationStatus.REJECTED,
            "reviewed_by": ADMIN_ID,
            "reviewed_at": NOW,
            "remarks": "Age limit is 18.",  # stripped
        }
    ]
    assert result.status == RegistrationStatus.REJECTED and result.remarks == "Age limit is 18."
    [note] = notifications.sent
    assert (note.user_id, note.type) == (VOLUNTEER_ID, NOTIFICATION_TYPE_REJECTED)
    assert "Age limit is 18." in note.message
    [entry] = audit.entries
    assert entry.action == "REGISTRATION_REJECTED" and entry.record_reference == REGISTRATION_ID
    assert registrations.count_calls == []  # no capacity check when rejecting


@pytest.mark.parametrize(
    "form", [{}, {"remarks": ""}, {"remarks": "  no "}, {"remarks": "x" * 501}]
)
def test_reject_requires_remarks(form: dict[str, str]) -> None:
    service, db, _, registrations, notifications, audit = make_service(activity(), registration())
    with pytest.raises(ValidationError) as excinfo:
        service.reject(admin(), REGISTRATION_ID, form, now=NOW)
    assert excinfo.value.errors == {"remarks": REMARKS_MESSAGE}
    assert db.transactions == 0  # refused before touching the database
    assert not registrations.reviews and not notifications.sent and not audit.entries


# -------------------------------------------------------------------- list
def test_list_page_defaults_to_pending_and_can_show_everything() -> None:
    pending = registration()
    approved = registration(RegistrationStatus.APPROVED)
    approved.id = 78
    service, _, _, registrations, *_ = make_service(activity(), pending, approved)

    page = service.list_page(admin())
    assert page.items == [pending] and page.total == 1
    assert registrations.search_calls[-1]["status"] == RegistrationStatus.PENDING

    page = service.list_page(admin(), status=None, page=1)
    assert page.total == 2
    assert registrations.search_calls[-1]["status"] is None
