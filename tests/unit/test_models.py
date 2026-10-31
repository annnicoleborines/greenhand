"""Unit tests for the domain model classes (Inheritance / polymorphism). No database."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

import pytest

from app.errors import ValidationError
from app.models import (
    Activity,
    ActivityStatus,
    Admin,
    Location,
    Person,
    Registration,
    RegistrationStatus,
    RoleName,
    UserStatus,
    Volunteer,
)
from app.services.reports.base_report import ReportContext


def make_volunteer(**overrides: Any) -> Volunteer:
    data: dict[str, Any] = {
        "id": 5,
        "role_id": 1,
        "role_name": RoleName.VOLUNTEER,
        "username": "maria",
        "email": "maria@example.com",
        "password_hash": "$2b$12$secret",
        "first_name": "Maria",
        "last_name": "Santos",
    }
    data.update(overrides)
    return Volunteer(**data)


def make_admin() -> Admin:
    return Admin(
        id=1,
        role_id=2,
        role_name=RoleName.ADMIN,
        username="admin",
        email="admin@example.com",
        first_name="Alex",
        last_name="Rivera",
    )


# ---- BaseEntity ----
def test_to_dict_converts_enums_and_dates() -> None:
    loc = Location(id=1, location_name="Park", address="Main St")
    assert loc.to_dict() == {
        "id": 1,
        "created_at": None,
        "updated_at": None,
        "location_name": "Park",
        "address": "Main St",
        "details": None,
        "activity_count": 0,  # not a column; filled by LocationDAO.list_with_activity_counts()
    }
    act = make_activity()
    data = act.to_dict()
    assert data["status"] == "OPEN"
    assert data["activity_date"] == "2030-01-01"
    assert data["start_time"] == "08:00:00"


def test_is_new_when_id_missing() -> None:
    assert Location(location_name="x", address="y").is_new
    assert not Location(id=3, location_name="x", address="y").is_new


# ---- Person / Volunteer / Admin ----
def test_person_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        Person(  # type: ignore[abstract]
            role_id=1,
            role_name=RoleName.VOLUNTEER,
            username="x",
            email="x@y.z",
            first_name="A",
            last_name="B",
        )


def test_name_helpers_and_role_flags() -> None:
    maria = make_volunteer()
    assert maria.full_name == "Maria Santos"
    assert maria.initials == "MS"
    assert not maria.is_admin
    assert make_admin().is_admin


def test_password_hash_never_in_to_dict() -> None:
    assert "password_hash" not in make_volunteer().to_dict()


def test_flask_login_protocol() -> None:
    maria = make_volunteer()
    assert maria.get_id() == "5"
    assert maria.is_authenticated and maria.is_active and not maria.is_anonymous
    assert not make_volunteer(status=UserStatus.INACTIVE).is_active


def test_is_locked_only_while_lockout_in_future() -> None:
    now = datetime(2030, 1, 1, 12, 0)
    assert make_volunteer(locked_until=now + timedelta(minutes=5)).is_locked(now)
    assert not make_volunteer(locked_until=now - timedelta(minutes=5)).is_locked(now)
    assert not make_volunteer().is_locked(now)


class _StubRegistrationDAO:
    def report_rows_for_user(self, user_id: int) -> list[dict[str, Any]]:
        return [
            {
                "activity_title": "Planting",
                "activity_date": date(2030, 1, 1),
                "start_time": timedelta(hours=7),
                "end_time": timedelta(hours=11),
                "status": "APPROVED",
            },
            {
                "activity_title": "Cleanup",
                "activity_date": date(2030, 2, 1),
                "start_time": timedelta(hours=8),
                "end_time": timedelta(hours=10),
                "status": "PENDING",
            },
        ]

    def count_by_status(self) -> dict[str, int]:
        return {"PENDING": 2, "APPROVED": 1}


class _StubActivityDAO:
    def count_all(self) -> int:
        return 7


class _StubUserDAO:
    def count_by_role(self, role: RoleName) -> int:
        return 4


def _context() -> ReportContext:
    return ReportContext(
        user_dao=_StubUserDAO(),  # type: ignore[arg-type]
        activity_dao=_StubActivityDAO(),  # type: ignore[arg-type]
        registration_dao=_StubRegistrationDAO(),  # type: ignore[arg-type]
    )


def test_volunteer_generate_report_counts_own_hours() -> None:
    result = make_volunteer().generate_report(_context())
    assert result.title == "My Volunteer Activity"
    assert result.summary["total_registrations"] == 2
    assert result.summary["hours"] == 4.0  # only the APPROVED one counts
    assert result.rows[0]["Activity"] == "Planting"


def test_admin_generate_report_gives_system_totals() -> None:
    result = make_admin().generate_report(_context())
    assert result.title == "System Totals"
    assert result.summary["Total activities"] == 7
    assert result.summary["Total volunteers"] == 4
    assert result.summary["Registrations PENDING"] == 2


# ---- Activity ----
def make_activity(**overrides: Any) -> Activity:
    data: dict[str, Any] = {
        "id": 10,
        "created_by": 1,
        "location_id": 1,
        "title": "Planting",
        "activity_date": date(2030, 1, 1),
        "start_time": time(8, 0),
        "end_time": time(11, 30),
        "max_volunteers": 10,
    }
    data.update(overrides)
    return Activity(**data)


def test_available_slots_are_computed() -> None:
    assert make_activity(taken_slots=3).available_slots == 7
    assert make_activity(taken_slots=10).is_full
    assert make_activity(taken_slots=12).available_slots == 0  # never negative


def test_activity_validate_rejects_bad_rules() -> None:
    with pytest.raises(ValidationError) as exc:
        make_activity(end_time=time(7, 0), max_volunteers=0).validate()
    assert set(exc.value.errors) == {"end_time", "max_volunteers"}
    make_activity().validate()  # valid -> no error


def test_activity_time_helpers() -> None:
    act = make_activity()
    assert act.duration_hours == 3.5
    assert act.has_started(datetime(2030, 1, 1, 9, 0))
    assert not act.has_started(datetime(2029, 12, 31, 9, 0))
    assert act.status == ActivityStatus.OPEN


# ---- Registration ----
def test_registration_slot_rules() -> None:
    assert Registration(activity_id=1, user_id=1).takes_slot
    assert Registration(activity_id=1, user_id=1, status=RegistrationStatus.APPROVED).takes_slot
    rejected = Registration(activity_id=1, user_id=1, status=RegistrationStatus.REJECTED)
    assert not rejected.takes_slot
    assert not rejected.can_be_cancelled
