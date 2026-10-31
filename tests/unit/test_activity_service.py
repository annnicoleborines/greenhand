"""Unit tests for ActivityService (FR-2 role check, FR-4 validation, FR-6 audit entries).

No database: the DAOs are small in-memory fakes, like tests/unit/test_profile_service.py.
The important business rule here is delete-vs-cancel: an activity with registrations
is never deleted, it is cancelled and the slot holders are notified.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date, time
from typing import Any

import pytest

from app.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models import (
    Activity,
    ActivityStatus,
    Admin,
    AuditLog,
    Location,
    Notification,
    RegistrationStatus,
    RoleName,
    Volunteer,
)
from app.services.activity_service import ActivityService
from app.services.pagination import Page

TODAY = date(2030, 6, 15)


# ----------------------------------------------------------------- fakes
class FakeDB:
    def __init__(self) -> None:
        self.transactions = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.transactions += 1
        yield None


class FakeActivityDAO:
    def __init__(self, *activities: Activity) -> None:
        self.activities = list(activities)
        self.registration_counts: dict[int, int] = {}
        self.inserted: list[Activity] = []
        self.updated: list[Activity] = []
        self.deleted: list[int] = []
        self.status_changes: list[tuple[int, ActivityStatus]] = []
        self.search_calls: list[dict[str, Any]] = []

    def find_by_id(self, activity_id: int) -> Activity | None:
        return next((a for a in self.activities if a.id == activity_id), None)

    def search(self, **filters: Any) -> list[Activity]:
        self.search_calls.append(filters)
        status = filters.get("status")
        rows = [a for a in self.activities if status is None or a.status == status]
        offset, limit = filters.get("offset", 0), filters.get("limit", 10)
        return rows[offset : offset + limit]

    def count_search(self, **filters: Any) -> int:
        status = filters.get("status")
        return len([a for a in self.activities if status is None or a.status == status])

    def registration_count(self, activity_id: int) -> int:
        return self.registration_counts.get(activity_id, 0)

    def insert(self, activity: Activity) -> int:
        activity.id = 300 + len(self.inserted)
        self.inserted.append(activity)
        self.activities.append(activity)
        return activity.id

    def update(self, activity: Activity) -> bool:
        self.updated.append(activity)
        return True

    def set_status(self, activity_id: int, status: ActivityStatus) -> bool:
        self.status_changes.append((activity_id, status))
        return True

    def delete(self, activity_id: int) -> bool:
        self.deleted.append(activity_id)
        return True


class FakeLocationDAO:
    def __init__(self, *ids: int) -> None:
        self.ids = set(ids)

    def find_by_id(self, location_id: int) -> Location | None:
        if location_id not in self.ids:
            return None
        return Location(id=location_id, location_name=f"Place {location_id}", address="x")


class FakeRegistrationDAO:
    def __init__(self, registrants: dict[int, list[tuple[int, RegistrationStatus]]]) -> None:
        # activity_id -> [(user_id, status), ...]
        self.registrants = registrants
        self.calls: list[tuple[int, list[RegistrationStatus]]] = []

    def list_user_ids_by_activity(
        self, activity_id: int, statuses: Iterable[RegistrationStatus]
    ) -> list[int]:
        wanted = list(statuses)
        self.calls.append((activity_id, wanted))
        return [uid for uid, status in self.registrants.get(activity_id, []) if status in wanted]


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


def make_admin() -> Admin:
    return Admin(
        id=1,
        role_id=2,
        role_name=RoleName.ADMIN,
        username="admin",
        email="admin@example.com",
        first_name="Ada",
        last_name="Min",
    )


def make_volunteer() -> Volunteer:
    return Volunteer(
        id=5,
        role_id=1,
        role_name=RoleName.VOLUNTEER,
        username="maria",
        email="maria@example.com",
        first_name="Maria",
        last_name="Santos",
    )


def make_activity(**overrides: Any) -> Activity:
    fields: dict[str, Any] = {
        "id": 40,
        "created_by": 1,
        "location_id": 3,
        "title": "Mangrove planting",
        "description": None,
        "activity_date": date(2030, 7, 1),
        "start_time": time(8, 0),
        "end_time": time(11, 30),
        "max_volunteers": 25,
        "requirements": "Bring gloves",
        "status": ActivityStatus.OPEN,
        "taken_slots": 0,
    }
    fields.update(overrides)
    return Activity(**fields)


class Harness:
    """Bundles the service and its fakes so tests can inspect every side effect."""

    def __init__(
        self,
        *activities: Activity,
        location_ids: Iterable[int] = (3, 4),
        registrants: dict[int, list[tuple[int, RegistrationStatus]]] | None = None,
    ) -> None:
        self.db = FakeDB()
        self.activities = FakeActivityDAO(*activities)
        self.locations = FakeLocationDAO(*location_ids)
        self.registrations = FakeRegistrationDAO(registrants or {})
        self.notifications = FakeNotificationDAO()
        self.audit = FakeAuditDAO()
        self.service = ActivityService(
            db=self.db,  # type: ignore[arg-type]
            activities=self.activities,  # type: ignore[arg-type]
            locations=self.locations,  # type: ignore[arg-type]
            registrations=self.registrations,  # type: ignore[arg-type]
            notifications=self.notifications,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
        )

    @property
    def audit_actions(self) -> list[str]:
        return [e.action for e in self.audit.entries]

    def assert_nothing_written(self) -> None:
        assert self.db.transactions == 0 and self.audit.entries == []
        assert self.activities.inserted == [] and self.activities.updated == []
        assert self.activities.deleted == [] and self.activities.status_changes == []
        assert self.notifications.sent == []


def activity_form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "title": "Mangrove planting",
        "description": "",
        "location_id": "3",
        "activity_date": "2030-07-01",
        "start_time": "08:00",
        "end_time": "11:30",
        "max_volunteers": "25",
        "requirements": "Bring gloves",
    }
    form.update(overrides)
    return form


# ------------------------------------------------------------ role check
@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("list_page", ()),
        ("get", (40,)),
        ("create", ({},)),
        ("update", (40, {})),
        ("delete_or_cancel", (40,)),
        ("change_status", (40, "CLOSED")),
    ],
)
def test_volunteers_are_refused_before_anything_is_read_or_written(
    method: str, args: tuple[Any, ...]
) -> None:
    h = Harness(make_activity())
    with pytest.raises(ForbiddenError):
        getattr(h.service, method)(make_volunteer(), *args)
    h.assert_nothing_written()


# ------------------------------------------------------------- list_page
def test_list_page_returns_a_page_with_the_requested_filter() -> None:
    open_one = make_activity(id=41)
    closed = make_activity(id=42, status=ActivityStatus.CLOSED)
    h = Harness(open_one, closed, make_activity(id=43))

    result = h.service.list_page(make_admin(), status=ActivityStatus.CLOSED, page=1, per_page=10)

    assert isinstance(result, Page)
    assert result.items == [closed] and result.total == 1
    assert h.activities.search_calls[-1] == {
        "status": ActivityStatus.CLOSED,
        "limit": 10,
        "offset": 0,
    }


def test_list_page_without_status_lists_everything_and_paginates() -> None:
    h = Harness(*[make_activity(id=50 + i) for i in range(12)])

    result = h.service.list_page(make_admin(), status=None, page=2, per_page=10)

    assert result.total == 12 and result.pages == 2
    assert [a.id for a in result.items] == [60, 61]
    assert h.activities.search_calls[-1]["offset"] == 10


def test_list_page_clamps_bad_page_numbers_to_one() -> None:
    h = Harness(make_activity())
    assert h.service.list_page(make_admin(), page=0).page == 1


def test_get_raises_not_found_for_unknown_id() -> None:
    h = Harness()
    with pytest.raises(NotFoundError):
        h.service.get(make_admin(), 99)


# ---------------------------------------------------------------- create
def test_create_inserts_an_open_activity_owned_by_the_admin_and_audits() -> None:
    h = Harness()

    activity = h.service.create(make_admin(), activity_form(), today=TODAY)

    assert h.db.transactions == 1 and h.activities.inserted == [activity]
    assert activity.id == 300 and activity.created_by == 1
    assert activity.status == ActivityStatus.OPEN
    assert activity.location_id == 3 and activity.max_volunteers == 25
    assert activity.start_time == time(8, 0) and activity.end_time == time(11, 30)
    entry = h.audit.entries[0]
    assert (entry.user_id, entry.action, entry.entity, entry.record_reference) == (
        1,
        "ACTIVITY_CREATED",
        "activity",
        300,
    )


def test_create_refuses_a_date_in_the_past() -> None:
    h = Harness()
    with pytest.raises(ValidationError) as exc_info:
        h.service.create(make_admin(), activity_form(activity_date="2030-06-14"), today=TODAY)
    assert "in the past" in exc_info.value.errors["activity_date"]
    h.assert_nothing_written()


def test_create_refuses_an_unknown_location_as_a_field_error() -> None:
    h = Harness(location_ids=(3,))
    with pytest.raises(ValidationError) as exc_info:
        h.service.create(make_admin(), activity_form(location_id="9"), today=TODAY)
    assert exc_info.value.errors == {"location_id": "Choose a location."}
    h.assert_nothing_written()


def test_create_rejects_invalid_form_before_touching_the_database() -> None:
    h = Harness()
    with pytest.raises(ValidationError) as exc_info:
        h.service.create(make_admin(), activity_form(title="ab", end_time="07:00"), today=TODAY)
    assert set(exc_info.value.errors) == {"title", "end_time"}
    h.assert_nothing_written()


# ---------------------------------------------------------------- update
def test_update_saves_changed_fields_and_audits_their_names() -> None:
    existing = make_activity()
    h = Harness(existing)

    result = h.service.update(
        make_admin(), 40, activity_form(title="Mangrove planting (moved)", location_id="4")
    )

    assert result is existing
    assert result.title == "Mangrove planting (moved)" and result.location_id == 4
    assert h.db.transactions == 1 and h.activities.updated == [existing]
    assert h.audit.entries[0].action == "ACTIVITY_UPDATED"
    assert h.audit.entries[0].details == "Changed: location_id, title."


def test_update_allows_a_date_in_the_past() -> None:
    h = Harness(make_activity())
    result = h.service.update(make_admin(), 40, activity_form(activity_date="2020-01-01"))
    assert result.activity_date == date(2020, 1, 1)


def test_update_with_no_changes_writes_nothing() -> None:
    h = Harness(make_activity())
    h.service.update(make_admin(), 40, activity_form())
    h.assert_nothing_written()


def test_update_refuses_capacity_below_the_slots_already_taken() -> None:
    h = Harness(make_activity(taken_slots=8))

    with pytest.raises(ValidationError) as exc_info:
        h.service.update(make_admin(), 40, activity_form(max_volunteers="5"))

    assert exc_info.value.errors == {"max_volunteers": "8 volunteers already hold slots."}
    h.assert_nothing_written()


def test_update_allows_capacity_equal_to_the_slots_taken() -> None:
    h = Harness(make_activity(taken_slots=8))
    result = h.service.update(make_admin(), 40, activity_form(max_volunteers="8"))
    assert result.max_volunteers == 8


def test_update_refuses_an_unknown_location() -> None:
    h = Harness(make_activity(), location_ids=(3,))
    with pytest.raises(ValidationError) as exc_info:
        h.service.update(make_admin(), 40, activity_form(location_id="9"))
    assert "location_id" in exc_info.value.errors
    h.assert_nothing_written()


def test_update_unknown_activity_raises_not_found() -> None:
    h = Harness()
    with pytest.raises(NotFoundError):
        h.service.update(make_admin(), 99, activity_form())


# ------------------------------------------------------ delete_or_cancel
def test_delete_removes_the_row_when_nobody_ever_registered() -> None:
    h = Harness(make_activity())

    outcome = h.service.delete_or_cancel(make_admin(), 40)

    assert outcome == "deleted"
    assert h.activities.deleted == [40] and h.activities.status_changes == []
    assert h.db.transactions == 1 and h.notifications.sent == []
    assert [(e.action, e.entity, e.record_reference) for e in h.audit.entries] == [
        ("ACTIVITY_DELETED", "activity", 40)
    ]


def test_delete_with_registrations_cancels_instead_and_notifies_slot_holders() -> None:
    activity = make_activity()
    h = Harness(
        activity,
        registrants={
            40: [
                (11, RegistrationStatus.PENDING),
                (12, RegistrationStatus.APPROVED),
                (13, RegistrationStatus.REJECTED),
                (14, RegistrationStatus.CANCELLED),
                (15, RegistrationStatus.COMPLETED),
            ]
        },
    )
    h.activities.registration_counts = {40: 5}

    outcome = h.service.delete_or_cancel(make_admin(), 40)

    assert outcome == "cancelled"
    assert h.activities.deleted == []  # the row stays for the history
    assert h.activities.status_changes == [(40, ActivityStatus.CANCELLED)]
    assert activity.status == ActivityStatus.CANCELLED
    assert h.db.transactions == 1
    # Only PENDING and APPROVED registrants still hold a slot, so only they hear about it.
    assert [n.user_id for n in h.notifications.sent] == [11, 12]
    assert {n.message for n in h.notifications.sent} == {
        "Activity Mangrove planting on 2030-07-01 was cancelled."
    }
    assert h.registrations.calls == [
        (40, [RegistrationStatus.PENDING, RegistrationStatus.APPROVED])
    ]
    entry = h.audit.entries[0]
    assert (entry.action, entry.entity, entry.record_reference) == (
        "ACTIVITY_CANCELLED",
        "activity",
        40,
    )
    assert entry.details is not None and "2 volunteer(s) notified" in entry.details


def test_delete_of_an_already_cancelled_activity_with_registrations_is_refused() -> None:
    h = Harness(make_activity(status=ActivityStatus.CANCELLED))
    h.activities.registration_counts = {40: 1}

    with pytest.raises(ConflictError, match="already CANCELLED"):
        h.service.delete_or_cancel(make_admin(), 40)
    h.assert_nothing_written()


def test_delete_unknown_activity_raises_not_found() -> None:
    h = Harness()
    with pytest.raises(NotFoundError):
        h.service.delete_or_cancel(make_admin(), 99)
    h.assert_nothing_written()


# --------------------------------------------------------- change_status
@pytest.mark.parametrize(
    ("current", "new", "details"),
    [
        (ActivityStatus.OPEN, "CLOSED", "OPEN -> CLOSED"),
        (ActivityStatus.CLOSED, "OPEN", "CLOSED -> OPEN"),
        (ActivityStatus.OPEN, "completed", "OPEN -> COMPLETED"),  # case-insensitive input
    ],
)
def test_change_status_updates_the_row_and_audits_the_transition(
    current: ActivityStatus, new: str, details: str
) -> None:
    activity = make_activity(status=current)
    h = Harness(activity)

    result = h.service.change_status(make_admin(), 40, new)

    assert result.status == ActivityStatus(new.upper())
    assert h.activities.status_changes == [(40, ActivityStatus(new.upper()))]
    assert h.db.transactions == 1 and h.notifications.sent == []
    assert h.audit_actions == ["ACTIVITY_STATUS_CHANGED"]
    assert h.audit.entries[0].details == details


def test_change_status_to_cancelled_goes_through_the_cancel_path() -> None:
    h = Harness(
        make_activity(),
        registrants={40: [(11, RegistrationStatus.APPROVED), (12, RegistrationStatus.REJECTED)]},
    )

    result = h.service.change_status(make_admin(), 40, "CANCELLED")

    assert result.status == ActivityStatus.CANCELLED
    assert h.activities.status_changes == [(40, ActivityStatus.CANCELLED)]
    assert [n.user_id for n in h.notifications.sent] == [11]
    assert h.notifications.sent[0].type == "ACTIVITY_CANCELLED"
    assert h.audit_actions == ["ACTIVITY_CANCELLED"]


def test_change_status_to_cancelled_with_no_registrants_still_audits() -> None:
    h = Harness(make_activity())
    h.service.change_status(make_admin(), 40, "CANCELLED")
    assert h.notifications.sent == [] and h.audit_actions == ["ACTIVITY_CANCELLED"]


@pytest.mark.parametrize("bad", ["", "DELETED", "open now", None])
def test_change_status_rejects_unknown_values(bad: str | None) -> None:
    h = Harness(make_activity())
    with pytest.raises(ValidationError) as exc_info:
        h.service.change_status(make_admin(), 40, bad)  # type: ignore[arg-type]
    assert exc_info.value.errors == {"status": "Choose a valid status."}
    h.assert_nothing_written()


def test_change_status_to_the_current_status_is_a_conflict() -> None:
    h = Harness(make_activity(status=ActivityStatus.CLOSED))
    with pytest.raises(ConflictError, match="already CLOSED"):
        h.service.change_status(make_admin(), 40, "CLOSED")
    h.assert_nothing_written()


def test_change_status_unknown_activity_raises_not_found() -> None:
    h = Harness()
    with pytest.raises(NotFoundError):
        h.service.change_status(make_admin(), 99, "CLOSED")
