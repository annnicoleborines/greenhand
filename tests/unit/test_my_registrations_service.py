"""Unit tests for MyRegistrationsService and NotificationService (FR-2, FR-3, FR-6).

No database: the DAOs are small in-memory fakes. Rules under test: a volunteer sees
only their own rows, cancel is allowed only for PENDING / APPROVED before the activity
starts and runs under the activity lock, admins are notified and the audit entry is
written in the same transaction, the schedule splits upcoming from history, and
mark-as-read never touches another user's notification.
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
from app.services.my_registrations_service import (
    MSG_STARTED,
    NOTIFICATION_TYPE_CANCELLED,
    MyRegistrationsService,
)
from app.services.notification_service import NotificationService

NOW = datetime(2030, 6, 1, 9, 0)
TODAY = NOW.date()
VOLUNTEER_ID = 7
OTHER_ID = 8
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
    def __init__(self, db: FakeDB, *activities: Activity) -> None:
        self.db = db
        self.activities = list(activities)
        self.locks_inside_transaction: list[bool] = []

    def lock_for_update(self, activity_id: int) -> Activity | None:
        self.locks_inside_transaction.append(self.db.open)
        return next((a for a in self.activities if a.id == activity_id), None)


class FakeRegistrationDAO:
    def __init__(self, *rows: Registration) -> None:
        self.rows = list(rows)
        self.status_changes: list[tuple[int, RegistrationStatus]] = []

    def find_by_id(self, registration_id: int) -> Registration | None:
        return next((r for r in self.rows if r.id == registration_id), None)

    def list_by_user(
        self, user_id: int, status: RegistrationStatus | None = None
    ) -> list[Registration]:
        rows = [r for r in self.rows if r.user_id == user_id]
        return [r for r in rows if status is None or r.status == status]

    def set_status(self, registration_id: int, status: RegistrationStatus) -> bool:
        self.status_changes.append((registration_id, status))
        return True


class FakeUserDAO:
    def list_admin_ids(self) -> list[int]:
        return list(ADMIN_IDS)


class FakeNotificationDAO:
    def __init__(self) -> None:
        self.sent: list[Notification] = []
        self.read: list[tuple[int, int]] = []
        self.read_all_for: list[int] = []
        self.mark_read_result = True

    def insert(self, notification: Notification) -> int:
        notification.id = len(self.sent) + 1
        self.sent.append(notification)
        return notification.id

    def insert_many(self, user_ids: list[int], type_: str, message: str) -> int:
        for user_id in user_ids:
            self.insert(Notification(user_id=user_id, type=type_, message=message))
        return len(user_ids)

    def mark_read(self, notification_id: int, user_id: int) -> bool:
        self.read.append((notification_id, user_id))
        return self.mark_read_result

    def mark_all_read(self, user_id: int) -> int:
        self.read_all_for.append(user_id)
        return 3

    def unread_count(self, user_id: int) -> int:
        return 3

    def list_by_user(self, user_id: int, *, limit: int = 50) -> list[Notification]:
        return [n for n in self.sent if n.user_id == user_id][:limit]


class FakeAuditDAO:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def insert(self, entry: AuditLog) -> int:
        entry.id = len(self.entries) + 1
        self.entries.append(entry)
        return entry.id


# --------------------------------------------------------------- builders
def volunteer(user_id: int = VOLUNTEER_ID) -> Volunteer:
    return Volunteer(
        id=user_id,
        role_id=1,
        role_name=RoleName.VOLUNTEER,
        username=f"vol{user_id}",
        email=f"v{user_id}@x",
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
        first_name="A",
        last_name="A",
    )


def activity(
    activity_id: int = 40,
    *,
    on: date = date(2030, 6, 8),
    status: ActivityStatus = ActivityStatus.OPEN,
) -> Activity:
    return Activity(
        id=activity_id,
        created_by=1,
        location_id=3,
        title=f"Activity {activity_id}",
        activity_date=on,
        start_time=time(8, 0),
        end_time=time(11, 0),
        max_volunteers=10,
        status=status,
    )


def registration(
    registration_id: int,
    *,
    status: RegistrationStatus = RegistrationStatus.PENDING,
    user_id: int = VOLUNTEER_ID,
    activity_id: int = 40,
    on: date = date(2030, 6, 8),
    start: time = time(8, 0),
    end: time = time(11, 0),
) -> Registration:
    return Registration(
        id=registration_id,
        activity_id=activity_id,
        user_id=user_id,
        status=status,
        activity_title=f"Activity {activity_id}",
        activity_date=on,
        activity_start_time=start,
        activity_end_time=end,
        activity_status=ActivityStatus.OPEN,
        location_name="Park",
    )


def make_service(
    *rows: Registration, activities: tuple[Activity, ...] = (activity(),)
) -> tuple[
    MyRegistrationsService,
    FakeDB,
    FakeActivityDAO,
    FakeRegistrationDAO,
    FakeNotificationDAO,
    FakeAuditDAO,
]:
    db = FakeDB()
    activity_dao = FakeActivityDAO(db, *activities)
    registrations = FakeRegistrationDAO(*rows)
    notifications = FakeNotificationDAO()
    audit = FakeAuditDAO()
    service = MyRegistrationsService(
        db=db,  # type: ignore[arg-type]
        registrations=registrations,  # type: ignore[arg-type]
        activities=activity_dao,  # type: ignore[arg-type]
        users=FakeUserDAO(),  # type: ignore[arg-type]
        notifications=notifications,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )
    return service, db, activity_dao, registrations, notifications, audit


# ------------------------------------------------------------------- list
def test_list_mine_shows_only_own_rows_with_tab_counts() -> None:
    service, *_ = make_service(
        registration(1),
        registration(2, status=RegistrationStatus.APPROVED),
        registration(3, status=RegistrationStatus.APPROVED),
        registration(4, user_id=OTHER_ID),  # someone else's: never shown or counted
    )
    mine = service.list_mine(volunteer())
    assert [r.id for r in mine.items] == [1, 2, 3]
    assert mine.counts["PENDING"] == 1 and mine.counts["APPROVED"] == 2
    assert mine.counts["REJECTED"] == 0 and mine.total == 3

    only_approved = service.list_mine(volunteer(), RegistrationStatus.APPROVED)
    assert [r.id for r in only_approved.items] == [2, 3]
    assert only_approved.total == 3  # the tabs still show every count


def test_list_mine_is_volunteer_only() -> None:
    service, *_ = make_service()
    with pytest.raises(ForbiddenError):
        service.list_mine(admin())
    with pytest.raises(ForbiddenError):
        service.schedule(admin())
    with pytest.raises(ForbiddenError):
        service.cancel(admin(), 1, now=NOW)


# --------------------------------------------------------------- schedule
def test_schedule_splits_upcoming_from_history_and_sums_hours() -> None:
    service, *_ = make_service(
        registration(1, on=date(2030, 6, 10)),  # pending, future -> upcoming
        registration(
            2, status=RegistrationStatus.APPROVED, on=date(2030, 6, 2)
        ),  # upcoming, sooner
        registration(
            3, status=RegistrationStatus.APPROVED, on=date(2030, 5, 20)
        ),  # past -> history
        registration(4, status=RegistrationStatus.COMPLETED, on=date(2030, 5, 1), end=time(12, 0)),
        registration(5, status=RegistrationStatus.REJECTED, on=date(2030, 5, 15)),  # never shown
        registration(6, status=RegistrationStatus.CANCELLED, on=date(2030, 6, 20)),  # never shown
        registration(
            7, status=RegistrationStatus.PENDING, on=date(2030, 5, 25)
        ),  # past pending: history
    )
    plan = service.schedule(volunteer(), today=TODAY)
    assert [r.id for r in plan.upcoming] == [2, 1]  # soonest first
    assert [r.id for r in plan.history] == [7, 3, 4]  # most recent first
    assert (
        plan.hours == 3.0 + 4.0
    )  # APPROVED (3h) + COMPLETED (4h); the past PENDING row counts nothing


def test_schedule_counts_today_as_upcoming() -> None:
    service, *_ = make_service(registration(1, status=RegistrationStatus.APPROVED, on=TODAY))
    plan = service.schedule(volunteer(), today=TODAY)
    assert [r.id for r in plan.upcoming] == [1] and plan.history == []


# ----------------------------------------------------------------- cancel
@pytest.mark.parametrize("status", [RegistrationStatus.PENDING, RegistrationStatus.APPROVED])
def test_cancel_sets_cancelled_notifies_admins_and_audits_in_one_transaction(
    status: RegistrationStatus,
) -> None:
    row = registration(1, status=status)
    service, db, activities, registrations, notifications, audit = make_service(row)

    result = service.cancel(volunteer(), 1, now=NOW)

    assert db.transactions == 1
    assert activities.locks_inside_transaction == [True]
    assert registrations.status_changes == [(1, RegistrationStatus.CANCELLED)]
    assert result is row and row.status == RegistrationStatus.CANCELLED
    assert [n.user_id for n in notifications.sent] == ADMIN_IDS
    assert all(n.type == NOTIFICATION_TYPE_CANCELLED for n in notifications.sent)
    assert f"{status.value.lower()} registration" in notifications.sent[0].message
    [entry] = audit.entries
    assert (entry.user_id, entry.action, entry.entity, entry.record_reference) == (
        VOLUNTEER_ID,
        "REGISTRATION_CANCELLED",
        "registration",
        1,
    )
    assert f"{status.value} -> CANCELLED" in (entry.details or "")


@pytest.mark.parametrize(
    "status",
    [RegistrationStatus.REJECTED, RegistrationStatus.CANCELLED, RegistrationStatus.COMPLETED],
)
def test_cancel_is_refused_for_rows_that_hold_no_slot(status: RegistrationStatus) -> None:
    service, _, _, registrations, notifications, audit = make_service(
        registration(1, status=status)
    )
    with pytest.raises(ConflictError, match=status.value):
        service.cancel(volunteer(), 1, now=NOW)
    assert not registrations.status_changes and not notifications.sent and not audit.entries


def test_cancel_is_refused_once_the_activity_has_started() -> None:
    started = activity(on=TODAY)  # starts 08:00 today; NOW is 09:00
    service, _, _, registrations, *_ = make_service(
        registration(1, status=RegistrationStatus.APPROVED, on=TODAY), activities=(started,)
    )
    with pytest.raises(ConflictError, match=MSG_STARTED):
        service.cancel(volunteer(), 1, now=NOW)
    assert not registrations.status_changes


def test_cancel_someone_elses_registration_is_not_found() -> None:
    service, _, activities, registrations, *_ = make_service(registration(1, user_id=OTHER_ID))
    with pytest.raises(NotFoundError):
        service.cancel(volunteer(), 1, now=NOW)
    assert activities.locks_inside_transaction == []  # refused before locking anything
    assert not registrations.status_changes
    with pytest.raises(NotFoundError):
        service.cancel(volunteer(), 999, now=NOW)


# ---------------------------------------------------------- notifications
def test_mark_read_uses_the_actors_id_and_404s_when_nothing_changed() -> None:
    dao = FakeNotificationDAO()
    service = NotificationService(notifications=dao)  # type: ignore[arg-type]
    service.mark_read(volunteer(), 5)
    assert dao.read == [(5, VOLUNTEER_ID)]

    dao.mark_read_result = False  # the DAO's WHERE user_id = %s matched nothing
    with pytest.raises(NotFoundError):
        service.mark_read(volunteer(), 6)

    assert service.mark_all_read(volunteer()) == 3
    assert dao.read_all_for == [VOLUNTEER_ID]
