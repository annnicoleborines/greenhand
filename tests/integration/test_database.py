"""Integration tests against the real test database (MariaDB locally, MySQL 8 in CI).

They prove that schema.sql, the DatabaseManager and the DAOs work together,
and that FR-8 error cases (duplicates, lost connection, bad input) are handled.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

import pytest
from flask.testing import FlaskClient

from app.dao import (
    ActivityDAO,
    LocationDAO,
    RegistrationDAO,
    RoleDAO,
    UserDAO,
    VolunteerProfileDAO,
)
from app.database import DatabaseManager
from app.errors import ConflictError, DatabaseError, ValidationError
from app.models import (
    Activity,
    Admin,
    Location,
    Registration,
    RegistrationStatus,
    RoleName,
    Volunteer,
    VolunteerProfile,
)

EXPECTED_TABLES = {
    "roles",
    "users",
    "volunteer_profiles",
    "locations",
    "activities",
    "registrations",
    "notifications",
    "audit_logs",
}


def make_admin(db: DatabaseManager, username: str = "admin_t") -> Admin:
    role = RoleDAO(db).find_by_name(RoleName.ADMIN)
    admin = Admin(
        role_id=role.id or 0,
        role_name=RoleName.ADMIN,
        username=username,
        email=f"{username}@example.com",
        password_hash="x",
        first_name="A",
        last_name="D",
    )
    UserDAO(db).insert(admin)
    return admin


def make_volunteer(db: DatabaseManager, username: str = "vol_t") -> Volunteer:
    role = RoleDAO(db).find_by_name(RoleName.VOLUNTEER)
    volunteer = Volunteer(
        role_id=role.id or 0,
        role_name=RoleName.VOLUNTEER,
        username=username,
        email=f"{username}@example.com",
        password_hash="x",
        first_name="V",
        last_name="T",
    )
    UserDAO(db).insert(volunteer)
    return volunteer


def make_activity(db: DatabaseManager, admin: Admin, **overrides: Any) -> Activity:
    location = Location(location_name="L", address="A")
    LocationDAO(db).insert(location)
    data: dict[str, Any] = {
        "created_by": admin.id,
        "location_id": location.id,
        "title": "T",
        "activity_date": date(2030, 1, 1),
        "start_time": time(8, 0),
        "end_time": time(10, 0),
        "max_volunteers": 5,
    }
    data.update(overrides)
    activity = Activity(**data)
    ActivityDAO(db).insert(activity)
    return activity


# ---- schema ----
def test_schema_has_all_tables_with_innodb_utf8mb4(clean_db: DatabaseManager) -> None:
    rows = clean_db.fetch_all(
        # Aliases: MySQL 8 returns these columns in UPPER CASE, MariaDB in lower case.
        "SELECT table_name AS table_name, engine AS engine, "
        "table_collation AS table_collation "
        "FROM information_schema.tables WHERE table_schema = DATABASE()"
    )
    assert {r["table_name"] for r in rows} == EXPECTED_TABLES
    for r in rows:
        assert r["engine"] == "InnoDB", r["table_name"]
        assert r["table_collation"].startswith("utf8mb4"), r["table_name"]


def test_roles_are_reference_data(clean_db: DatabaseManager) -> None:
    names = {role.name for role in RoleDAO(clean_db).list_all()}
    assert names == {RoleName.VOLUNTEER, RoleName.ADMIN}


# ---- FR-8: errors are handled, not crashes ----
def test_duplicate_username_becomes_conflict_error(clean_db: DatabaseManager) -> None:
    make_volunteer(clean_db, "dup")
    with pytest.raises(ConflictError):
        make_volunteer(clean_db, "dup")


def test_check_constraint_becomes_validation_error(clean_db: DatabaseManager) -> None:
    admin = make_admin(clean_db)
    with pytest.raises(ValidationError):
        make_activity(clean_db, admin, max_volunteers=0)


def test_foreign_key_violation_becomes_conflict_error(clean_db: DatabaseManager) -> None:
    admin = make_admin(clean_db)
    with pytest.raises(ConflictError):
        make_activity(clean_db, admin, location_id=999_999)


def test_lost_connection_becomes_database_error(clean_db: DatabaseManager) -> None:
    clean_db.configure(database=clean_db.database_name, port=1)  # nothing listens here
    try:
        with pytest.raises(DatabaseError):
            RoleDAO(clean_db).list_all()
    finally:
        clean_db.configure(database=clean_db.database_name)


def test_transaction_rolls_back_everything_on_error(clean_db: DatabaseManager) -> None:
    users = UserDAO(clean_db)
    with pytest.raises(ConflictError), clean_db.transaction():
        make_volunteer(clean_db, "first")
        make_volunteer(clean_db, "first")  # duplicate -> whole transaction rolls back
    assert users.find_by_username("first") is None


# ---- DAO round trips ----
def test_user_and_profile_round_trip(clean_db: DatabaseManager) -> None:
    volunteer = make_volunteer(clean_db)
    VolunteerProfileDAO(clean_db).insert(
        VolunteerProfile(user_id=volunteer.id or 0, address="Home", birth_date=date(2001, 5, 6))
    )
    loaded = UserDAO(clean_db).find_by_username("vol_t")
    assert isinstance(loaded, Volunteer)
    assert loaded.profile is not None
    assert loaded.profile.address == "Home"
    assert loaded.profile.birth_date == date(2001, 5, 6)


def test_available_slots_are_computed_from_registrations(clean_db: DatabaseManager) -> None:
    admin = make_admin(clean_db)
    activity = make_activity(clean_db, admin, max_volunteers=3)
    v1, v2, v3 = (make_volunteer(clean_db, f"v{i}") for i in range(3))
    regs = RegistrationDAO(clean_db)
    regs.insert(Registration(activity_id=activity.id or 0, user_id=v1.id or 0))
    r2 = Registration(activity_id=activity.id or 0, user_id=v2.id or 0)
    regs.insert(r2)
    regs.set_status(r2.id or 0, RegistrationStatus.APPROVED)
    r3 = Registration(activity_id=activity.id or 0, user_id=v3.id or 0)
    regs.insert(r3)
    regs.set_status(r3.id or 0, RegistrationStatus.CANCELLED)  # does not take a slot

    loaded = ActivityDAO(clean_db).find_by_id(activity.id or 0)
    assert loaded is not None
    assert loaded.taken_slots == 2
    assert loaded.available_slots == 1
    assert regs.count_slot_taking(activity.id or 0) == 2


def test_duplicate_registration_rejected_and_reopen_reuses_row(clean_db: DatabaseManager) -> None:
    admin = make_admin(clean_db)
    activity = make_activity(clean_db, admin)
    volunteer = make_volunteer(clean_db)
    regs = RegistrationDAO(clean_db)
    reg = Registration(activity_id=activity.id or 0, user_id=volunteer.id or 0)
    regs.insert(reg)
    with pytest.raises(ConflictError):
        regs.insert(Registration(activity_id=activity.id or 0, user_id=volunteer.id or 0))
    regs.set_status(reg.id or 0, RegistrationStatus.CANCELLED)
    assert regs.reopen(reg.id or 0)
    again = regs.find_by_activity_and_user(activity.id or 0, volunteer.id or 0)
    assert again is not None and again.id == reg.id
    assert again.status == RegistrationStatus.PENDING


# ---- web layer ----
def test_health_endpoint_reaches_database(client: FlaskClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_health_shows_friendly_page_when_database_is_down(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    clean_db.configure(database=clean_db.database_name, port=1)
    try:
        response = client.get("/health")
    finally:
        clean_db.configure(database=clean_db.database_name)
    assert response.status_code == 503
    assert b"Is MySQL running in XAMPP?" in response.data
