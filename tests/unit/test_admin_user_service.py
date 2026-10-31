"""Unit tests for AdminUserService (FR-2 role check, FR-6 audit entries).

No database: the DAOs are small in-memory fakes, like tests/unit/test_profile_service.py.
bcrypt is slow, so the reset-password tests share one service call where they can.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.auth.passwords import verify_password
from app.errors import ConflictError, ForbiddenError, NotFoundError
from app.models import Admin, AuditLog, Notification, Person, RoleName, UserStatus, Volunteer
from app.schemas.auth import check_password_strength
from app.services.admin_user_service import AdminUserService, generate_temporary_password
from app.services.pagination import Page


# ----------------------------------------------------------------- fakes
class FakeDB:
    def __init__(self) -> None:
        self.transactions = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.transactions += 1
        yield None


class FakeUserDAO:
    def __init__(self, *users: Person) -> None:
        self.users = list(users)
        self.status_updates: list[tuple[int, UserStatus]] = []
        self.password_updates: list[tuple[int, str]] = []
        self.lockout_resets: list[int] = []
        self.search_calls: list[tuple[str | None, int, int]] = []

    def find_by_id(self, user_id: int) -> Person | None:
        return next((u for u in self.users if u.id == user_id), None)

    def _volunteers(self, search: str | None) -> list[Person]:
        rows = [u for u in self.users if u.role_name == RoleName.VOLUNTEER]
        if search:
            needle = search.lower()
            rows = [
                u
                for u in rows
                if needle in u.first_name.lower()
                or needle in u.last_name.lower()
                or needle in u.username.lower()
                or needle in u.email.lower()
            ]
        return rows

    def search_volunteers(
        self, search: str | None = None, *, limit: int = 20, offset: int = 0
    ) -> list[Person]:
        self.search_calls.append((search, limit, offset))
        return self._volunteers(search)[offset : offset + limit]

    def count_volunteers(self, search: str | None = None) -> int:
        return len(self._volunteers(search))

    def set_status(self, user_id: int, status: UserStatus) -> bool:
        self.status_updates.append((user_id, status))
        return True

    def update_password(self, user_id: int, password_hash: str) -> bool:
        self.password_updates.append((user_id, password_hash))
        return True

    def reset_failed_logins(self, user_id: int) -> None:
        self.lockout_resets.append(user_id)


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


def make_admin(**overrides: Any) -> Admin:
    fields: dict[str, Any] = {
        "id": 1,
        "role_id": 2,
        "role_name": RoleName.ADMIN,
        "username": "admin",
        "email": "admin@example.com",
        "first_name": "Ada",
        "last_name": "Min",
    }
    fields.update(overrides)
    return Admin(**fields)


def make_volunteer(**overrides: Any) -> Volunteer:
    fields: dict[str, Any] = {
        "id": 5,
        "role_id": 1,
        "role_name": RoleName.VOLUNTEER,
        "username": "maria",
        "email": "maria@example.com",
        "password_hash": "$2b$12$old",
        "first_name": "Maria",
        "last_name": "Santos",
    }
    fields.update(overrides)
    return Volunteer(**fields)


def make_service(
    *users: Person,
) -> tuple[AdminUserService, FakeDB, FakeUserDAO, FakeNotificationDAO, FakeAuditDAO]:
    db = FakeDB()
    user_dao = FakeUserDAO(*users)
    notification_dao = FakeNotificationDAO()
    audit_dao = FakeAuditDAO()
    service = AdminUserService(
        db=db,  # type: ignore[arg-type]
        users=user_dao,  # type: ignore[arg-type]
        notifications=notification_dao,  # type: ignore[arg-type]
        audit=audit_dao,  # type: ignore[arg-type]
    )
    return service, db, user_dao, notification_dao, audit_dao


# ------------------------------------------------------------ role check
@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("list_volunteers_page", ()),
        ("get", (5,)),
        ("set_active", (5, False)),
        ("reset_password", (5,)),
    ],
)
def test_volunteers_are_refused_before_anything_is_read_or_written(
    method: str, args: tuple[Any, ...]
) -> None:
    service, db, users, notifications, audit = make_service(make_volunteer())
    with pytest.raises(ForbiddenError):
        getattr(service, method)(make_volunteer(), *args)
    assert db.transactions == 0 and audit.entries == [] and notifications.sent == []
    assert users.status_updates == [] and users.password_updates == []


# --------------------------------------------------- list_volunteers_page
def test_list_volunteers_page_lists_only_volunteers() -> None:
    maria = make_volunteer()
    juan = make_volunteer(id=6, username="juan", first_name="Juan", email="juan@example.com")
    service, _, _, _, _ = make_service(make_admin(), maria, juan)

    result = service.list_volunteers_page(make_admin())

    assert isinstance(result, Page)
    assert result.items == [maria, juan] and result.total == 2
    assert result.page == 1 and result.per_page == 20


def test_list_volunteers_page_passes_the_trimmed_search_and_paginates() -> None:
    volunteers = [
        make_volunteer(id=10 + i, username=f"vol{i}", email=f"v{i}@example.com") for i in range(25)
    ]
    service, _, users, _, _ = make_service(*volunteers)

    result = service.list_volunteers_page(make_admin(), search="  vol ", page=2, per_page=20)

    assert users.search_calls == [("vol", 20, 20)]
    assert result.total == 25 and result.pages == 2 and len(result.items) == 5


def test_list_volunteers_page_treats_blank_search_as_no_search() -> None:
    service, _, users, _, _ = make_service(make_volunteer())
    service.list_volunteers_page(make_admin(), search="   ", page=0)
    assert users.search_calls == [(None, 20, 0)]


# -------------------------------------------------------------------- get
def test_get_returns_the_volunteer_and_refuses_admins_and_unknown_ids() -> None:
    volunteer = make_volunteer()
    service, _, _, _, _ = make_service(volunteer, make_admin(id=2, username="boss"))

    assert service.get(make_admin(), 5) is volunteer
    with pytest.raises(ConflictError, match="Administrator accounts"):
        service.get(make_admin(), 2)
    with pytest.raises(NotFoundError):
        service.get(make_admin(), 99)


# ------------------------------------------------------------ set_active
def test_deactivate_sets_inactive_and_audits() -> None:
    user = make_volunteer()
    service, db, users, notifications, audit = make_service(user)

    result = service.set_active(make_admin(), 5, False)

    assert result is user and result.status == UserStatus.INACTIVE
    assert db.transactions == 1 and users.status_updates == [(5, UserStatus.INACTIVE)]
    assert notifications.sent == []
    entry = audit.entries[0]
    assert (entry.user_id, entry.action, entry.entity, entry.record_reference) == (
        1,
        "USER_DEACTIVATED",
        "user",
        5,
    )
    assert entry.details is not None and "maria" in entry.details


def test_activate_sets_active_and_audits() -> None:
    user = make_volunteer(status=UserStatus.INACTIVE)
    service, db, users, _, audit = make_service(user)

    service.set_active(make_admin(), 5, True)

    assert user.status == UserStatus.ACTIVE
    assert db.transactions == 1 and users.status_updates == [(5, UserStatus.ACTIVE)]
    assert [e.action for e in audit.entries] == ["USER_ACTIVATED"]


def test_set_active_with_no_change_writes_nothing() -> None:
    service, db, users, _, audit = make_service(make_volunteer())
    service.set_active(make_admin(), 5, True)  # already ACTIVE
    assert db.transactions == 0 and users.status_updates == [] and audit.entries == []


def test_admin_cannot_deactivate_their_own_account() -> None:
    admin = make_admin()
    service, db, users, _, audit = make_service(admin)

    with pytest.raises(ConflictError, match="your own account"):
        service.set_active(admin, admin.id or 0, False)
    assert db.transactions == 0 and users.status_updates == [] and audit.entries == []


def test_other_admin_accounts_are_not_managed_here() -> None:
    other_admin = make_admin(id=2, username="boss")
    service, _, users, _, _ = make_service(other_admin)

    with pytest.raises(ConflictError, match="Administrator accounts"):
        service.set_active(make_admin(), 2, False)
    with pytest.raises(ConflictError, match="Administrator accounts"):
        service.reset_password(make_admin(), 2)
    assert users.status_updates == [] and users.password_updates == []


def test_set_active_unknown_user_raises_not_found() -> None:
    service, _, _, _, _ = make_service()
    with pytest.raises(NotFoundError):
        service.set_active(make_admin(), 99, False)


# -------------------------------------------------------- reset_password
def test_reset_password_stores_a_hash_notifies_and_audits_without_the_password() -> None:
    user = make_volunteer()
    service, db, users, notifications, audit = make_service(user)

    temporary = service.reset_password(make_admin(), 5)

    assert db.transactions == 1
    (user_id, new_hash), *_ = users.password_updates
    assert user_id == 5 and new_hash != temporary  # only the bcrypt hash is stored
    assert verify_password(temporary, new_hash)  # ...and the volunteer can log in with it
    assert user.password_hash == new_hash
    assert users.lockout_resets == [5]  # a locked-out account is usable again

    assert [(n.user_id, n.type, n.message) for n in notifications.sent] == [
        (5, "PASSWORD_RESET", "Your password was reset by an administrator.")
    ]
    assert temporary not in notifications.sent[0].message

    entry = audit.entries[0]
    assert (entry.user_id, entry.action, entry.entity, entry.record_reference) == (
        1,
        "PASSWORD_RESET",
        "user",
        5,
    )
    assert entry.details is not None
    assert "maria" in entry.details and temporary not in entry.details


def test_reset_password_unknown_user_raises_not_found() -> None:
    service, db, users, _, _ = make_service()
    with pytest.raises(NotFoundError):
        service.reset_password(make_admin(), 99)
    assert db.transactions == 0 and users.password_updates == []


# ------------------------------------------- generate_temporary_password
def test_temporary_password_is_12_chars_with_a_letter_and_a_digit() -> None:
    for _ in range(50):  # random output: check the guarantee many times
        password = generate_temporary_password()
        assert len(password) == 12
        assert any(c.isalpha() for c in password) and any(c.isdigit() for c in password)
        assert password.isalnum()
        assert check_password_strength(password) == password  # meets the sign-up rules


def test_temporary_passwords_are_different_each_time() -> None:
    assert len({generate_temporary_password() for _ in range(20)}) == 20


def test_temporary_password_avoids_look_alike_characters() -> None:
    sample = "".join(generate_temporary_password(200) for _ in range(5))
    assert not set("0O1lI") & set(sample)


def test_temporary_password_length_is_adjustable_but_at_least_two() -> None:
    assert len(generate_temporary_password(20)) == 20
    with pytest.raises(ValueError, match="at least two"):
        generate_temporary_password(1)
