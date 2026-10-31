"""Unit tests for the DAO classes using FakeDatabaseManager (no MySQL).

Each DAO gets at least one happy-path and one failure-path test. The fake
records the SQL and parameters, so we can prove values go through %s
placeholders and never into the SQL text.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from app.dao import (
    ActivityDAO,
    AuditLogDAO,
    LocationDAO,
    NotificationDAO,
    RegistrationDAO,
    RoleDAO,
    UserDAO,
    VolunteerProfileDAO,
)
from app.errors import DatabaseError, NotFoundError
from app.models import (
    ActivityStatus,
    Admin,
    AuditLog,
    Location,
    Notification,
    Registration,
    RegistrationStatus,
    RoleName,
    Volunteer,
    VolunteerProfile,
)
from tests.conftest import FakeDatabaseManager

NOW = datetime(2030, 1, 1, 10, 0)


def user_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": 5,
        "role_id": 1,
        "role_name": "VOLUNTEER",
        "username": "maria",
        "email": "maria@example.com",
        "password_hash": "$2b$12$x",
        "first_name": "Maria",
        "last_name": "Santos",
        "phone": None,
        "photo_path": None,
        "status": "ACTIVE",
        "failed_login_attempts": 0,
        "locked_until": None,
        "created_at": NOW,
        "updated_at": NOW,
        "profile_id": 9,
        "address": "Street 1",
        "birth_date": date(2000, 1, 1),
        "emergency_contact_name": "Mom",
        "emergency_contact_phone": "123",
        "profile_created_at": NOW,
        "profile_updated_at": NOW,
    }
    row.update(overrides)
    return row


# ---- RoleDAO ----
def test_role_find_by_name_uses_placeholder(fake_db: FakeDatabaseManager) -> None:
    fake_db.rows = [{"id": 2, "name": "ADMIN"}]
    role = RoleDAO(fake_db).find_by_name(RoleName.ADMIN)  # type: ignore[arg-type]
    assert role.name == RoleName.ADMIN
    assert fake_db.last_params == ("ADMIN",)
    assert "ADMIN" not in fake_db.last_sql


def test_role_missing_raises_not_found(fake_db: FakeDatabaseManager) -> None:
    with pytest.raises(NotFoundError):
        RoleDAO(fake_db).find_by_name(RoleName.ADMIN)  # type: ignore[arg-type]


# ---- UserDAO ----
def test_user_dao_builds_volunteer_with_profile(fake_db: FakeDatabaseManager) -> None:
    fake_db.rows = [user_row()]
    person = UserDAO(fake_db).find_by_username("maria")  # type: ignore[arg-type]
    assert isinstance(person, Volunteer)
    assert person.profile is not None and person.profile.address == "Street 1"
    assert fake_db.last_params == ("maria",)


def test_user_dao_builds_admin_without_profile(fake_db: FakeDatabaseManager) -> None:
    fake_db.rows = [user_row(role_name="ADMIN", profile_id=None)]
    person = UserDAO(fake_db).find_by_id(5)  # type: ignore[arg-type]
    assert isinstance(person, Admin)


def test_user_dao_returns_none_when_missing(fake_db: FakeDatabaseManager) -> None:
    assert UserDAO(fake_db).find_by_email("nobody@x.y") is None  # type: ignore[arg-type]


def test_user_dao_insert_sets_id_and_binds_values(fake_db: FakeDatabaseManager) -> None:
    volunteer = Volunteer(
        role_id=1,
        role_name=RoleName.VOLUNTEER,
        username="new'; DROP TABLE users; --",
        email="n@x.y",
        password_hash="h",
        first_name="N",
        last_name="U",
    )
    new_id = UserDAO(fake_db).insert(volunteer)  # type: ignore[arg-type]
    assert new_id == 1 and volunteer.id == 1
    assert "DROP TABLE" not in fake_db.last_sql  # the injection text stayed a parameter
    assert fake_db.last_params[1] == "new'; DROP TABLE users; --"


def test_user_dao_update_photo_and_password_bind_values(fake_db: FakeDatabaseManager) -> None:
    dao = UserDAO(fake_db)  # type: ignore[arg-type]
    assert dao.update_photo(5, "avatars/user_5.png") is True
    assert fake_db.last_params == ("avatars/user_5.png", 5)
    assert dao.update_password(5, "$2b$12$new") is True
    assert "password_hash = %s" in fake_db.last_sql
    assert fake_db.last_params == ("$2b$12$new", 5)


def test_user_dao_propagates_database_error(fake_db: FakeDatabaseManager) -> None:
    fake_db.fail_with = DatabaseError()
    with pytest.raises(DatabaseError):
        UserDAO(fake_db).find_by_id(1)  # type: ignore[arg-type]


# ---- VolunteerProfileDAO ----
def test_profile_insert_and_update(fake_db: FakeDatabaseManager) -> None:
    dao = VolunteerProfileDAO(fake_db)  # type: ignore[arg-type]
    profile = VolunteerProfile(user_id=5, address="A")
    assert dao.insert(profile) == 1
    assert dao.update(profile) is True
    assert fake_db.last_params[-1] == 5  # WHERE user_id = %s


def test_profile_missing_returns_none(fake_db: FakeDatabaseManager) -> None:
    assert VolunteerProfileDAO(fake_db).find_by_user_id(99) is None  # type: ignore[arg-type]


# ---- LocationDAO ----
def test_location_round_trip(fake_db: FakeDatabaseManager) -> None:
    dao = LocationDAO(fake_db)  # type: ignore[arg-type]
    loc = Location(location_name="Park", address="Main")
    assert dao.insert(loc) == 1
    fake_db.rows = [{"id": 1, "location_name": "Park", "address": "Main", "details": None}]
    assert dao.find_by_id(1) == loc


def test_location_delete_returns_false_when_nothing_deleted(fake_db: FakeDatabaseManager) -> None:
    dao = LocationDAO(fake_db)  # type: ignore[arg-type]
    fake_db.execute = lambda sql, params=(): 0  # type: ignore[method-assign]
    assert dao.delete(42) is False


# ---- ActivityDAO ----
def activity_row() -> dict[str, Any]:
    return {
        "id": 3,
        "created_by": 1,
        "location_id": 2,
        "title": "Planting",
        "description": None,
        "activity_date": date(2030, 1, 1),
        "start_time": timedelta(hours=7),  # PyMySQL gives TIME as timedelta
        "end_time": timedelta(hours=11),
        "max_volunteers": 10,
        "requirements": None,
        "status": "OPEN",
        "created_at": NOW,
        "updated_at": NOW,
        "location_name": "Park",
        "taken_slots": 4,
    }


def test_activity_search_binds_keyword_with_like(fake_db: FakeDatabaseManager) -> None:
    fake_db.rows = [activity_row()]
    results = ActivityDAO(fake_db).search(keyword="plant", location_id=2)  # type: ignore[arg-type]
    assert results[0].available_slots == 6
    assert results[0].start_time.hour == 7
    assert "LIKE %s" in fake_db.last_sql
    assert fake_db.last_params == ("OPEN", 2, "%plant%", "%plant%", 12, 0)


def test_activity_search_date_from_binds_value(fake_db: FakeDatabaseManager) -> None:
    today = date(2030, 6, 15)
    ActivityDAO(fake_db).search(date_from=today, limit=12, offset=12)  # type: ignore[arg-type]
    assert "a.activity_date >= %s" in fake_db.last_sql
    assert "a.activity_date = %s" not in fake_db.last_sql  # exact-day filter not added
    assert "2030" not in fake_db.last_sql  # the date is a parameter, not SQL text
    assert fake_db.last_params == ("OPEN", today, 12, 12)
    assert "ORDER BY a.activity_date, a.start_time, a.id LIMIT %s OFFSET %s" in fake_db.last_sql


def test_activity_count_search_matches_search_filters(fake_db: FakeDatabaseManager) -> None:
    fake_db.rows = [{"n": 13}]
    today = date(2030, 6, 15)
    n = ActivityDAO(fake_db).count_search(  # type: ignore[arg-type]
        keyword="plant", location_id=2, activity_date=today, date_from=today
    )
    assert n == 13
    assert fake_db.last_sql.startswith("SELECT COUNT(*) AS n FROM activities a WHERE 1 = 1")
    assert "a.activity_date >= %s" in fake_db.last_sql
    assert fake_db.last_params == ("OPEN", 2, today, today, "%plant%", "%plant%")


def test_activity_count_search_without_filters_has_only_status(
    fake_db: FakeDatabaseManager,
) -> None:
    ActivityDAO(fake_db).count_search()  # type: ignore[arg-type]
    assert fake_db.last_params == ("OPEN",)
    assert "LIKE" not in fake_db.last_sql


def test_activity_list_upcoming_open(fake_db: FakeDatabaseManager) -> None:
    fake_db.rows = [activity_row()]
    today = date(2030, 6, 15)
    items = ActivityDAO(fake_db).list_upcoming_open(limit=3, today=today)  # type: ignore[arg-type]
    assert items[0].available_slots == 6
    assert "WHERE a.status = %s AND a.activity_date >= %s" in fake_db.last_sql
    assert fake_db.last_sql.endswith("ORDER BY a.activity_date, a.start_time, a.id LIMIT %s")
    assert fake_db.last_params == ("OPEN", today, 3)


def test_activity_list_upcoming_open_defaults_to_today(fake_db: FakeDatabaseManager) -> None:
    ActivityDAO(fake_db).list_upcoming_open()  # type: ignore[arg-type]
    assert fake_db.last_params == ("OPEN", date.today(), 3)


def test_activity_lock_for_update_uses_for_update(fake_db: FakeDatabaseManager) -> None:
    fake_db.rows = [activity_row()]
    ActivityDAO(fake_db).lock_for_update(3)  # type: ignore[arg-type]
    assert fake_db.last_sql.endswith("FOR UPDATE")


def test_activity_missing_returns_none(fake_db: FakeDatabaseManager) -> None:
    assert ActivityDAO(fake_db).find_by_id(404) is None  # type: ignore[arg-type]


def test_activity_set_status(fake_db: FakeDatabaseManager) -> None:
    assert ActivityDAO(fake_db).set_status(3, ActivityStatus.CANCELLED)  # type: ignore[arg-type]
    assert fake_db.last_params == ("CANCELLED", 3)


# ---- RegistrationDAO ----
def test_registration_count_slot_taking(fake_db: FakeDatabaseManager) -> None:
    fake_db.rows = [{"n": 2}]
    assert RegistrationDAO(fake_db).count_slot_taking(3) == 2  # type: ignore[arg-type]
    assert "'PENDING', 'APPROVED'" in fake_db.last_sql


def test_registration_count_slot_taking_for_update_is_a_locking_read(
    fake_db: FakeDatabaseManager,
) -> None:
    fake_db.rows = [{"n": 4}]
    dao = RegistrationDAO(fake_db)  # type: ignore[arg-type]
    assert dao.count_slot_taking(3, for_update=True) == 4
    assert fake_db.last_sql.endswith("LOCK IN SHARE MODE") and fake_db.last_params == (3,)
    dao.count_slot_taking(3)
    assert "LOCK IN SHARE MODE" not in fake_db.last_sql  # plain read by default


def test_registration_search_and_count_share_the_status_filter(
    fake_db: FakeDatabaseManager,
) -> None:
    dao = RegistrationDAO(fake_db)  # type: ignore[arg-type]
    dao.search(status=RegistrationStatus.PENDING, limit=20, offset=40)
    search_sql, search_params = fake_db.calls[-1]
    assert "WHERE g.status = %s" in search_sql
    assert "ORDER BY g.registration_date, g.id LIMIT %s OFFSET %s" in search_sql
    assert search_params == ("PENDING", 20, 40)

    fake_db.rows = [{"n": 3}]
    assert dao.count_search(status=RegistrationStatus.PENDING) == 3
    count_sql, count_params = fake_db.calls[-1]
    assert count_sql.endswith("WHERE g.status = %s") and count_params == ("PENDING",)

    fake_db.rows = []  # the count row above is not a registration row
    dao.search(status=None)
    assert "WHERE" not in fake_db.calls[-1][0]  # every status
    fake_db.rows = [{"n": 3}]
    assert dao.count_search() == 3 and fake_db.calls[-1][1] == ()


def test_registration_count_for_activity_binds_statuses_and_can_lock(
    fake_db: FakeDatabaseManager,
) -> None:
    fake_db.rows = [{"n": 2}]
    dao = RegistrationDAO(fake_db)  # type: ignore[arg-type]
    assert dao.count_for_activity(9, [RegistrationStatus.APPROVED], for_update=True) == 2
    assert "status IN (%s) LOCK IN SHARE MODE" in fake_db.last_sql
    assert fake_db.last_params == (9, "APPROVED")
    assert dao.count_for_activity(9, []) == 0  # no statuses: no query
    assert fake_db.last_params == (9, "APPROVED")  # unchanged, nothing was run


def test_registration_reopen_resets_review_fields(fake_db: FakeDatabaseManager) -> None:
    assert RegistrationDAO(fake_db).reopen(7)  # type: ignore[arg-type]
    assert "reviewed_by = NULL" in fake_db.last_sql
    assert fake_db.last_params == (7,)


def test_registration_review_binds_all_fields(fake_db: FakeDatabaseManager) -> None:
    RegistrationDAO(fake_db).review(  # type: ignore[arg-type]
        7, status=RegistrationStatus.REJECTED, reviewed_by=1, reviewed_at=NOW, remarks="Full"
    )
    assert fake_db.last_params == ("REJECTED", 1, NOW, "Full", 7)


def test_registration_missing_returns_none(fake_db: FakeDatabaseManager) -> None:
    assert RegistrationDAO(fake_db).find_by_activity_and_user(1, 1) is None  # type: ignore[arg-type]


def test_registration_insert_defaults_to_pending(fake_db: FakeDatabaseManager) -> None:
    reg = Registration(activity_id=3, user_id=5)
    RegistrationDAO(fake_db).insert(reg)  # type: ignore[arg-type]
    assert fake_db.last_params == (3, 5, "PENDING")


# ---- NotificationDAO ----
def test_notification_mark_read_is_scoped_to_user(fake_db: FakeDatabaseManager) -> None:
    NotificationDAO(fake_db).mark_read(10, 5)  # type: ignore[arg-type]
    assert "user_id = %s" in fake_db.last_sql
    assert fake_db.last_params == (10, 5)


def test_notification_insert_many_counts(fake_db: FakeDatabaseManager) -> None:
    n = NotificationDAO(fake_db).insert_many([1, 2, 3], "REGISTRATION", "New")  # type: ignore[arg-type]
    assert n == 3
    assert len(fake_db.calls) == 3


def test_notification_list_maps_is_read_to_bool(fake_db: FakeDatabaseManager) -> None:
    fake_db.rows = [
        {"id": 1, "user_id": 5, "type": "T", "message": "m", "is_read": 1, "created_at": NOW}
    ]
    items = NotificationDAO(fake_db).list_by_user(5)  # type: ignore[arg-type]
    assert items[0] == Notification(
        id=1, user_id=5, type="T", message="m", is_read=True, created_at=NOW
    )


# ---- AuditLogDAO ----
def test_audit_insert(fake_db: FakeDatabaseManager) -> None:
    entry = AuditLog(user_id=1, action="CREATE", entity="activity", record_reference=3)
    assert AuditLogDAO(fake_db).insert(entry) == 1  # type: ignore[arg-type]
    assert fake_db.last_params == (1, "CREATE", "activity", 3, None)


def test_audit_search_adds_only_given_filters(fake_db: FakeDatabaseManager) -> None:
    AuditLogDAO(fake_db).search(action="CREATE", date_from=date(2030, 1, 1))  # type: ignore[arg-type]
    assert "l.action = %s" in fake_db.last_sql
    assert "l.user_id = %s" not in fake_db.last_sql
    assert fake_db.last_params == ("CREATE", date(2030, 1, 1), 50, 0)


def test_audit_search_and_count_share_filters_including_username(
    fake_db: FakeDatabaseManager,
) -> None:
    dao = AuditLogDAO(fake_db)  # type: ignore[arg-type]
    dao.search(action="LOGIN", username="ad", date_to=date(2030, 1, 31), limit=25, offset=25)
    search_sql, search_params = fake_db.calls[-1]
    assert "u.username LIKE %s" in search_sql and "DATE_ADD(%s, INTERVAL 1 DAY)" in search_sql
    assert search_params == ("LOGIN", "%ad%", date(2030, 1, 31), 25, 25)  # wildcard in the value

    fake_db.rows = [{"n": 4}]
    assert dao.count_search(action="LOGIN", username="ad", date_to=date(2030, 1, 31)) == 4
    count_sql, count_params = fake_db.calls[-1]
    assert count_sql.startswith("SELECT COUNT(*) AS n FROM audit_logs l JOIN users u")
    assert "u.username LIKE %s" in count_sql and count_params == (
        "LOGIN",
        "%ad%",
        date(2030, 1, 31),
    )

    fake_db.rows = [{"action": "LOGIN"}, {"action": "SIGN_UP"}]
    assert dao.list_actions() == ["LOGIN", "SIGN_UP"]
    assert "DISTINCT action" in fake_db.calls[-1][0]


def test_activity_report_rows_adds_only_given_filters(fake_db: FakeDatabaseManager) -> None:
    ActivityDAO(fake_db).report_rows(date_from=date(2030, 6, 1), status=ActivityStatus.OPEN)  # type: ignore[arg-type]
    sql, params = fake_db.calls[-1]
    assert "LEFT JOIN registrations r" in sql and "SUM(r.status = 'PENDING')" in sql
    assert "a.activity_date >= %s" in sql and "a.activity_date <= %s" not in sql
    assert "GROUP BY a.id" in sql and params == (date(2030, 6, 1), "OPEN")


def test_registration_report_rows_joins_users_and_activities(fake_db: FakeDatabaseManager) -> None:
    RegistrationDAO(fake_db).report_rows(date_to=date(2030, 6, 30))  # type: ignore[arg-type]
    sql, params = fake_db.calls[-1]
    assert "JOIN users u" in sql and "JOIN activities a" in sql
    assert "a.activity_date <= %s" in sql and params == (date(2030, 6, 30),)


# ---- Phase 3 additions: admin lists ----
def test_user_dao_search_volunteers_puts_the_wildcard_in_the_value(
    fake_db: FakeDatabaseManager,
) -> None:
    dao = UserDAO(fake_db)  # type: ignore[arg-type]
    fake_db.rows = [user_row()]

    people = dao.search_volunteers("ana", limit=20, offset=40)

    assert len(people) == 1 and isinstance(people[0], Volunteer)
    sql, params = fake_db.calls[-1]
    assert "r.name = %s" in sql and "u.first_name LIKE %s" in sql and "u.email LIKE %s" in sql
    assert "%ana%" not in sql  # the wildcard travels as a parameter, never in the SQL text
    assert params == ("VOLUNTEER", "%ana%", "%ana%", "%ana%", "%ana%", 20, 40)


def test_user_dao_count_volunteers_without_search_has_no_like(
    fake_db: FakeDatabaseManager,
) -> None:
    dao = UserDAO(fake_db)  # type: ignore[arg-type]
    fake_db.rows = [{"n": 7}]

    assert dao.count_volunteers("   ") == 7
    sql, params = fake_db.calls[-1]
    assert "LIKE" not in sql and params == ("VOLUNTEER",)


def test_location_dao_list_with_activity_counts_fills_the_extra_field(
    fake_db: FakeDatabaseManager,
) -> None:
    dao = LocationDAO(fake_db)  # type: ignore[arg-type]
    fake_db.rows = [
        {"id": 1, "location_name": "Park", "address": "Main", "details": None, "activity_count": 3},
        {"id": 2, "location_name": "Hill", "address": "Top", "details": None, "activity_count": 0},
    ]

    locations = dao.list_with_activity_counts()

    assert [(loc.id, loc.activity_count) for loc in locations] == [(1, 3), (2, 0)]
    assert "LEFT JOIN activities" in fake_db.last_sql and "COUNT(a.id)" in fake_db.last_sql


def test_registration_dao_list_user_ids_by_activity_binds_each_status(
    fake_db: FakeDatabaseManager,
) -> None:
    dao = RegistrationDAO(fake_db)  # type: ignore[arg-type]
    fake_db.rows = [{"user_id": 11}, {"user_id": 12}]

    ids = dao.list_user_ids_by_activity(
        40, [RegistrationStatus.PENDING, RegistrationStatus.APPROVED]
    )

    assert ids == [11, 12]
    sql, params = fake_db.calls[-1]
    assert "status IN (%s, %s)" in sql
    assert params == (40, "PENDING", "APPROVED")


def test_registration_dao_list_user_ids_with_no_statuses_skips_the_query(
    fake_db: FakeDatabaseManager,
) -> None:
    dao = RegistrationDAO(fake_db)  # type: ignore[arg-type]
    assert dao.list_user_ids_by_activity(40, []) == []
    assert fake_db.calls == []
