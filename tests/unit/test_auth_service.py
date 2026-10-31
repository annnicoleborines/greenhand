"""Unit tests for AuthService (FR-1 login rules, FR-4 validation, FR-6 audit entries).

No database: the DAOs are replaced with small in-memory fakes so each rule in the
service can be checked on its own. The integration tests in
tests/integration/test_auth_flow.py cover the same rules against real MySQL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.auth.passwords import hash_password, verify_password
from app.errors import ConflictError, ForbiddenError, ValidationError
from app.models import AuditLog, Person, RoleName, UserStatus, Volunteer, VolunteerProfile
from app.services.auth_service import (
    GENERIC_LOGIN_ERROR,
    LOCKOUT_MINUTES,
    MAX_FAILED_ATTEMPTS,
    AuthService,
)

NOW = datetime(2030, 1, 1, 10, 0)
PASSWORD = "Secret123"
PASSWORD_HASH = hash_password(PASSWORD)  # bcrypt is slow; hash once for the whole module


# ----------------------------------------------------------------- fakes
class FakeDB:
    """Only the part of DatabaseManager the service uses: transaction()."""

    def __init__(self) -> None:
        self.transactions = 0
        self.rolled_back = False

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.transactions += 1
        try:
            yield None
        except Exception:
            self.rolled_back = True
            raise


class FakeUserDAO:
    def __init__(self, *users: Person) -> None:
        self.users = list(users)
        self.inserted: list[Person] = []
        self.failures: list[tuple[int, int, datetime | None]] = []
        self.resets: list[int] = []
        self.fresh_state: tuple[int, datetime | None] | None = None  # what the DB row says now

    def username_exists(self, username: str) -> bool:
        return any(u.username == username for u in self.users)

    def email_exists(self, email: str) -> bool:
        return any(u.email == email for u in self.users)

    def find_by_username(self, username: str) -> Person | None:
        return next((u for u in self.users if u.username == username), None)

    def insert(self, person: Person) -> int:
        person.id = 100 + len(self.inserted)
        self.inserted.append(person)
        return person.id

    def record_failed_login(
        self, user_id: int, attempts: int, locked_until: datetime | None
    ) -> None:
        self.failures.append((user_id, attempts, locked_until))

    def reset_failed_logins(self, user_id: int) -> None:
        self.resets.append(user_id)

    def lock_login_state(self, user_id: int) -> tuple[int, datetime | None] | None:
        if self.fresh_state is not None:
            return self.fresh_state
        user = next((u for u in self.users if u.id == user_id), None)
        return (user.failed_login_attempts, user.locked_until) if user else None


class FakeProfileDAO:
    def __init__(self) -> None:
        self.inserted: list[VolunteerProfile] = []

    def insert(self, profile: VolunteerProfile) -> int:
        profile.id = 900 + len(self.inserted)
        self.inserted.append(profile)
        return profile.id


class FakeRoleDAO:
    def find_by_name(self, name: RoleName) -> Any:
        return SimpleNamespace(id=1 if name == RoleName.VOLUNTEER else 2, name=name)


class FakeAuditDAO:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def insert(self, entry: AuditLog) -> int:
        entry.id = len(self.entries) + 1
        self.entries.append(entry)
        return entry.id


def make_volunteer(**overrides: Any) -> Volunteer:
    fields: dict[str, Any] = {
        "id": 5,
        "role_id": 1,
        "role_name": RoleName.VOLUNTEER,
        "username": "maria",
        "email": "maria@example.com",
        "password_hash": PASSWORD_HASH,
        "first_name": "Maria",
        "last_name": "Santos",
    }
    fields.update(overrides)
    return Volunteer(**fields)


def make_service(
    *users: Person,
) -> tuple[AuthService, FakeDB, FakeUserDAO, FakeProfileDAO, FakeAuditDAO]:
    db = FakeDB()
    user_dao = FakeUserDAO(*users)
    profile_dao = FakeProfileDAO()
    audit_dao = FakeAuditDAO()
    service = AuthService(
        db=db,  # type: ignore[arg-type]
        users=user_dao,  # type: ignore[arg-type]
        profiles=profile_dao,  # type: ignore[arg-type]
        roles=FakeRoleDAO(),  # type: ignore[arg-type]
        audit=audit_dao,  # type: ignore[arg-type]
    )
    return service, db, user_dao, profile_dao, audit_dao


def signup_form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "username": "NewVol",
        "email": "New@Example.com",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
        "first_name": "Nina",
        "last_name": "Vol",
        "phone": "",
        "address": "1 Green St",
    }
    form.update(overrides)
    return form


# --------------------------------------------------------------- sign-up
def test_register_creates_user_profile_and_audit_in_one_transaction() -> None:
    service, db, users, profiles, audit = make_service()

    volunteer = service.register_volunteer(signup_form())

    assert db.transactions == 1 and not db.rolled_back
    assert users.inserted == [volunteer]
    assert volunteer.username == "newvol" and volunteer.email == "new@example.com"
    assert volunteer.role_name == RoleName.VOLUNTEER and volunteer.role_id == 1
    assert volunteer.password_hash != PASSWORD  # never stored in plain text
    assert verify_password(PASSWORD, volunteer.password_hash)
    assert volunteer.phone is None  # blank optional field saved as NULL
    assert profiles.inserted == [volunteer.profile]
    assert volunteer.profile is not None and volunteer.profile.user_id == volunteer.id
    assert volunteer.profile.address == "1 Green St"
    assert [(e.action, e.entity, e.record_reference) for e in audit.entries] == [
        ("SIGN_UP", "user", volunteer.id)
    ]


def test_register_rejects_invalid_form_before_touching_the_database() -> None:
    service, db, users, _, audit = make_service()

    with pytest.raises(ValidationError) as exc_info:
        service.register_volunteer(signup_form(email="nope", confirm_password="other1X"))

    assert set(exc_info.value.errors) == {"email", "confirm_password"}
    assert db.transactions == 0 and users.inserted == [] and audit.entries == []


def test_register_rejects_taken_username_or_email_with_field_errors() -> None:
    existing = make_volunteer(username="newvol", email="new@example.com")
    service, db, users, _, _ = make_service(existing)

    with pytest.raises(ConflictError) as exc_info:
        service.register_volunteer(signup_form())

    assert exc_info.value.status_code == 409
    assert set(exc_info.value.errors) == {"username", "email"}
    assert db.transactions == 0 and users.inserted == []


# ------------------------------------------------------------------ login
def test_login_success_returns_person_and_clears_failed_attempts() -> None:
    user = make_volunteer(failed_login_attempts=3)
    service, _, users, _, _ = make_service(user)

    result = service.login({"username": "  MARIA ", "password": PASSWORD}, now=NOW)

    assert result is user  # username is trimmed and lower-cased before lookup
    assert users.resets == [5] and user.failed_login_attempts == 0


def test_login_success_with_clean_record_skips_the_reset_query() -> None:
    service, _, users, _, _ = make_service(make_volunteer())
    service.login({"username": "maria", "password": PASSWORD}, now=NOW)
    assert users.resets == []


@pytest.mark.parametrize(
    "form",
    [
        {"username": "nobody", "password": PASSWORD},  # unknown user
        {"username": "maria", "password": "wrong-pass"},  # wrong password
        {"username": "", "password": ""},  # empty form
    ],
)
def test_login_failures_share_one_generic_message(form: dict[str, str]) -> None:
    service, _, _, _, _ = make_service(make_volunteer())
    with pytest.raises(ValidationError) as exc_info:
        service.login(form, now=NOW)
    assert exc_info.value.message == GENERIC_LOGIN_ERROR  # no hint whether the user exists


def test_wrong_password_increments_the_failure_counter() -> None:
    user = make_volunteer(failed_login_attempts=1)
    service, _, users, _, audit = make_service(user)

    with pytest.raises(ValidationError):
        service.login({"username": "maria", "password": "wrong-pass"}, now=NOW)

    assert users.failures == [(5, 2, None)]
    assert user.failed_login_attempts == 2 and user.locked_until is None
    assert audit.entries == []  # not locked yet, nothing to audit


def test_fifth_failure_locks_for_15_minutes_and_is_audited() -> None:
    user = make_volunteer(failed_login_attempts=MAX_FAILED_ATTEMPTS - 1)
    service, _, users, _, audit = make_service(user)

    with pytest.raises(ForbiddenError) as exc_info:
        service.login({"username": "maria", "password": "wrong-pass"}, now=NOW)

    expected_until = NOW + timedelta(minutes=LOCKOUT_MINUTES)
    assert "Too many failed attempts" in exc_info.value.message
    assert f"{LOCKOUT_MINUTES} minute" in exc_info.value.message
    assert users.failures == [(5, MAX_FAILED_ATTEMPTS, expected_until)]
    assert user.locked_until == expected_until
    assert [e.action for e in audit.entries] == ["ACCOUNT_LOCKED"]


def test_locked_user_is_refused_even_with_the_right_password() -> None:
    user = make_volunteer(
        failed_login_attempts=5, locked_until=NOW + timedelta(minutes=4, seconds=30)
    )
    service, _, users, _, _ = make_service(user)

    with pytest.raises(ForbiddenError) as exc_info:
        service.login({"username": "maria", "password": PASSWORD}, now=NOW)

    assert exc_info.value.status_code == 403
    assert "5 minute" in exc_info.value.message  # 4m30s left rounds up to 5
    assert users.failures == []  # an attempt during lockout does not extend it


def test_expired_lockout_starts_a_fresh_count() -> None:
    user = make_volunteer(failed_login_attempts=5, locked_until=NOW - timedelta(seconds=1))
    service, _, users, _, _ = make_service(user)

    with pytest.raises(ValidationError):
        service.login({"username": "maria", "password": "wrong-pass"}, now=NOW)

    assert users.failures == [(5, 1, None)]  # back to attempt 1, not 6


def test_expired_lockout_allows_login_with_the_right_password() -> None:
    user = make_volunteer(failed_login_attempts=5, locked_until=NOW - timedelta(minutes=1))
    service, _, users, _, _ = make_service(user)

    assert service.login({"username": "maria", "password": PASSWORD}, now=NOW) is user
    assert users.resets == [5] and user.locked_until is None


def test_inactive_account_cannot_log_in() -> None:
    user = make_volunteer(status=UserStatus.INACTIVE)
    service, _, users, _, _ = make_service(user)

    with pytest.raises(ForbiddenError) as exc_info:
        service.login({"username": "maria", "password": PASSWORD}, now=NOW)

    assert "inactive" in exc_info.value.message.lower()
    assert users.failures == []  # a correct password is not a "failed attempt"


def test_failure_count_comes_from_the_locked_row_not_the_stale_object() -> None:
    """Regression: parallel guesses used to each write back the same old count."""
    user = make_volunteer(failed_login_attempts=0)  # loaded before the slow bcrypt check...
    service, db, users, _, audit = make_service(user)
    users.fresh_state = (MAX_FAILED_ATTEMPTS - 1, None)  # ...while other requests pushed it to 4

    with pytest.raises(ForbiddenError):
        service.login({"username": "maria", "password": "wrong-pass"}, now=NOW)

    assert db.transactions == 1  # the read and the write happen under one row lock
    assert users.failures == [(5, MAX_FAILED_ATTEMPTS, NOW + timedelta(minutes=LOCKOUT_MINUTES))]
    assert [e.action for e in audit.entries] == ["ACCOUNT_LOCKED"]


def test_lock_set_by_a_parallel_request_is_kept_not_extended() -> None:
    user = make_volunteer(failed_login_attempts=3)
    service, _, users, _, audit = make_service(user)
    other_lock = NOW + timedelta(minutes=10)
    users.fresh_state = (MAX_FAILED_ATTEMPTS, other_lock)

    with pytest.raises(ForbiddenError) as exc_info:
        service.login({"username": "maria", "password": "wrong-pass"}, now=NOW)

    assert users.failures == [] and audit.entries == []  # nothing rewritten
    assert user.locked_until == other_lock
    assert "10 minute" in exc_info.value.message
