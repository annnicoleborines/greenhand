"""Unit tests for RegistrationService (FR-2 role check, FR-3 rules, FR-6 audit).

No database: the DAOs are small in-memory fakes, like tests/unit/test_activity_service.py.
The rules under test: lock first, OPEN and not started, one row per volunteer and
activity (CANCELLED re-used, REJECTED / COMPLETED final), slots counted under the
lock, and registration + audit + admin notifications written in one transaction.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time

import pytest

from app.errors import ConflictError, ForbiddenError, NotFoundError
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
from app.services.registration_service import (
    MSG_ALREADY,
    MSG_FINAL,
    MSG_FULL,
    MSG_NOT_OPEN,
    NOTIFICATION_TYPE_SUBMITTED,
    RegistrationService,
)

NOW = datetime(2030, 6, 1, 9, 0)
ACTIVITY_ID = 40
VOLUNTEER_ID = 7
ADMIN_IDS = [1, 2]


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
        self.locked_inside_transaction: list[bool] = []

    def lock_for_update(self, activity_id: int) -> Activity | None:
        self.locked_inside_transaction.append(self.db.open)
        if self.activity is None or self.activity.id != activity_id:
            return None
        return self.activity

    def find_by_id(self, activity_id: int) -> Activity | None:
        return self.lock_for_update(activity_id)


class FakeRegistrationDAO:
    def __init__(self, existing: Registration | None = None, taken: int = 0) -> None:
        self.existing = existing
        self.taken = taken
        self.inserted: list[Registration] = []
        self.reopened: list[int] = []
        self.count_calls: list[bool] = []

    def find_by_activity_and_user(self, activity_id: int, user_id: int) -> Registration | None:
        if self.existing and (self.existing.activity_id, self.existing.user_id) == (
            activity_id,
            user_id,
        ):
            return self.existing
        return None

    def count_slot_taking(self, activity_id: int, *, for_update: bool = False) -> int:
        self.count_calls.append(for_update)
        return self.taken

    def insert(self, registration: Registration) -> int:
        registration.id = 500 + len(self.inserted)
        self.inserted.append(registration)
        return registration.id

    def reopen(self, registration_id: int) -> bool:
        self.reopened.append(registration_id)
        return True


class FakeUserDAO:
    def list_admin_ids(self) -> list[int]:
        return list(ADMIN_IDS)


class FakeNotificationDAO:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def insert(self, notification: Notification) -> int:
        notification.id = len(self.sent) + 1
        self.sent.append(notification)
        return notification.id

    def insert_many(self, user_ids: list[int], type_: str, message: str) -> int:
        for user_id in user_ids:
            self.insert(Notification(user_id=user_id, type=type_, message=message))
        return len(user_ids)


class FakeAuditDAO:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def insert(self, entry: AuditLog) -> int:
        entry.id = len(self.entries) + 1
        self.entries.append(entry)
        return entry.id


# --------------------------------------------------------------- builders
def volunteer() -> Volunteer:
    return Volunteer(
        id=VOLUNTEER_ID,
        role_id=1,
        role_name=RoleName.VOLUNTEER,
        username="vicky",
        email="v@example.com",
        first_name="Vicky",
        last_name="Vol",
    )


def admin() -> Admin:
    return Admin(
        id=1,
        role_id=2,
        role_name=RoleName.ADMIN,
        username="ada",
        email="a@x",
        first_name="Ada",
        last_name="A",
    )


def activity(
    *, status: ActivityStatus = ActivityStatus.OPEN, max_volunteers: int = 10, in_days: int = 7
) -> Activity:
    return Activity(
        id=ACTIVITY_ID,
        created_by=1,
        location_id=3,
        title="Mangrove Planting",
        activity_date=NOW.date().replace(day=NOW.day + in_days)
        if in_days >= 0
        else date(2030, 5, 1),
        start_time=time(8, 0),
        end_time=time(11, 0),
        max_volunteers=max_volunteers,
        status=status,
    )


def existing(status: RegistrationStatus) -> Registration:
    return Registration(
        id=77,
        activity_id=ACTIVITY_ID,
        user_id=VOLUNTEER_ID,
        status=status,
        reviewed_by=1,
        reviewed_at=NOW,
        remarks="old remark",
    )


def make_service(
    act: Activity | None,
    *,
    row: Registration | None = None,
    taken: int = 0,
) -> tuple[
    RegistrationService,
    FakeDB,
    FakeActivityDAO,
    FakeRegistrationDAO,
    FakeNotificationDAO,
    FakeAuditDAO,
]:
    db = FakeDB()
    activities = FakeActivityDAO(act, db)
    registrations = FakeRegistrationDAO(row, taken)
    notifications = FakeNotificationDAO()
    audit = FakeAuditDAO()
    service = RegistrationService(
        db=db,  # type: ignore[arg-type]
        activities=activities,  # type: ignore[arg-type]
        registrations=registrations,  # type: ignore[arg-type]
        users=FakeUserDAO(),  # type: ignore[arg-type]
        notifications=notifications,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )
    return service, db, activities, registrations, notifications, audit


# ------------------------------------------------------------------ tests
def test_register_inserts_pending_row_audits_and_notifies_admins_in_one_transaction() -> None:
    service, db, activities, registrations, notifications, audit = make_service(activity(), taken=3)

    registration = service.register(volunteer(), ACTIVITY_ID, now=NOW)

    assert db.transactions == 1
    assert activities.locked_inside_transaction == [True]  # lock taken inside the transaction
    assert registrations.count_calls == [True]  # slots counted with a locking read
    assert registration.status == RegistrationStatus.PENDING
    assert registration.registration_date == NOW
    assert registration.id == 500 and registrations.inserted == [registration]
    assert registration.activity_title == "Mangrove Planting"

    [entry] = audit.entries
    assert (entry.action, entry.entity, entry.record_reference, entry.user_id) == (
        "REGISTRATION_CREATED",
        "registration",
        500,
        VOLUNTEER_ID,
    )
    assert "Mangrove Planting" in (entry.details or "")

    assert [n.user_id for n in notifications.sent] == ADMIN_IDS
    assert all(n.type == NOTIFICATION_TYPE_SUBMITTED for n in notifications.sent)
    assert "Vicky Vol registered for Mangrove Planting" in notifications.sent[0].message


def test_admin_cannot_register() -> None:
    service, db, *_ = make_service(activity())
    with pytest.raises(ForbiddenError):
        service.register(admin(), ACTIVITY_ID, now=NOW)
    assert db.transactions == 0


def test_missing_activity_is_not_found() -> None:
    service, *_ = make_service(None)
    with pytest.raises(NotFoundError):
        service.register(volunteer(), ACTIVITY_ID, now=NOW)


@pytest.mark.parametrize(
    "status", [ActivityStatus.CLOSED, ActivityStatus.CANCELLED, ActivityStatus.COMPLETED]
)
def test_only_open_activities_accept_registrations(status: ActivityStatus) -> None:
    service, _, _, registrations, notifications, audit = make_service(activity(status=status))
    with pytest.raises(ConflictError, match=MSG_NOT_OPEN):
        service.register(volunteer(), ACTIVITY_ID, now=NOW)
    assert not registrations.inserted and not notifications.sent and not audit.entries


def test_started_activity_is_closed_for_registration() -> None:
    service, *_ = make_service(activity(in_days=-1))  # dated last month
    with pytest.raises(ConflictError, match=MSG_NOT_OPEN):
        service.register(volunteer(), ACTIVITY_ID, now=NOW)


@pytest.mark.parametrize("status", [RegistrationStatus.PENDING, RegistrationStatus.APPROVED])
def test_pending_or_approved_row_means_already_registered(status: RegistrationStatus) -> None:
    service, _, _, registrations, *_ = make_service(activity(), row=existing(status))
    with pytest.raises(ConflictError, match=MSG_ALREADY):
        service.register(volunteer(), ACTIVITY_ID, now=NOW)
    assert not registrations.inserted and not registrations.reopened


@pytest.mark.parametrize("status", [RegistrationStatus.REJECTED, RegistrationStatus.COMPLETED])
def test_rejected_and_completed_are_final(status: RegistrationStatus) -> None:
    service, _, _, registrations, *_ = make_service(activity(), row=existing(status))
    with pytest.raises(ConflictError, match=MSG_FINAL):
        service.register(volunteer(), ACTIVITY_ID, now=NOW)
    assert not registrations.inserted and not registrations.reopened


def test_full_activity_is_refused_using_the_locked_count() -> None:
    # The activity object says 9 taken (stale), the locked count says 10: the lock wins.
    act = activity(max_volunteers=10)
    act.taken_slots = 9
    service, _, _, registrations, notifications, audit = make_service(act, taken=10)
    with pytest.raises(ConflictError, match=MSG_FULL):
        service.register(volunteer(), ACTIVITY_ID, now=NOW)
    assert not registrations.inserted and not notifications.sent and not audit.entries


def test_cancelled_row_is_reopened_instead_of_inserting() -> None:
    row = existing(RegistrationStatus.CANCELLED)
    service, _, _, registrations, notifications, audit = make_service(activity(), row=row, taken=2)

    registration = service.register(volunteer(), ACTIVITY_ID, now=NOW)

    assert registrations.reopened == [77] and not registrations.inserted
    assert registration is row
    assert registration.status == RegistrationStatus.PENDING
    assert (registration.reviewed_by, registration.reviewed_at, registration.remarks) == (
        None,
        None,
        None,
    )
    assert registration.registration_date == NOW
    [entry] = audit.entries
    assert entry.record_reference == 77 and "again" in (entry.details or "")
    assert len(notifications.sent) == len(ADMIN_IDS)


def test_registration_for_returns_own_row_for_volunteers_and_none_for_admins() -> None:
    row = existing(RegistrationStatus.APPROVED)
    service, *_ = make_service(activity(), row=row)
    assert service.registration_for(volunteer(), ACTIVITY_ID) is row
    assert service.registration_for(admin(), ACTIVITY_ID) is None


@pytest.mark.parametrize(
    ("status", "row", "taken", "expected"),
    [
        (ActivityStatus.OPEN, None, 0, True),
        (ActivityStatus.OPEN, RegistrationStatus.CANCELLED, 0, True),
        (ActivityStatus.OPEN, RegistrationStatus.PENDING, 0, False),
        (ActivityStatus.OPEN, RegistrationStatus.REJECTED, 0, False),
        (ActivityStatus.OPEN, None, 10, False),
        (ActivityStatus.CLOSED, None, 0, False),
    ],
)
def test_can_register_rule(
    status: ActivityStatus, row: RegistrationStatus | None, taken: int, expected: bool
) -> None:
    act = activity(status=status, max_volunteers=10)
    act.taken_slots = taken
    reg = existing(row) if row else None
    assert RegistrationService.can_register(act, reg, now=NOW) is expected
