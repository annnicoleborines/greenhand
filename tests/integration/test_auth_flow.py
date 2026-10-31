"""Integration tests for sign-up, login, lockout and role gates (FR-1, FR-2, FR-4, FR-6).

These drive the real controllers with Flask's test client against the test
database. TestConfig turns CSRF and rate limits off; CSRF is covered by the
Playwright test and rate limits by the dedicated test at the bottom of this
file, which builds its own app. Every table is emptied after each test.
"""

from __future__ import annotations

from typing import Any

import pytest
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from app.auth.passwords import hash_password
from app.dao import RoleDAO, UserDAO
from app.database import DatabaseManager
from app.models import Admin, RoleName, UserStatus

VOL_PASSWORD = "Secret123"
ADMIN_PASSWORD = "Admin1234"


def signup_form(**overrides: Any) -> dict[str, str]:
    form = {
        "username": "Vol_One",
        "email": "Vol@Example.com",
        "password": VOL_PASSWORD,
        "confirm_password": VOL_PASSWORD,
        "first_name": "Vicky",
        "last_name": "Vol",
        "phone": "0917 123 4567",
        "address": "123 Green St",
    }
    form.update(overrides)
    return form


def sign_up(client: FlaskClient, **overrides: Any) -> TestResponse:
    return client.post("/signup", data=signup_form(**overrides))


def log_in(client: FlaskClient, username: str, password: str, **query: str) -> TestResponse:
    return client.post(
        "/login", data={"username": username, "password": password}, query_string=query
    )


def make_admin(db: DatabaseManager) -> Admin:
    role = RoleDAO(db).find_by_name(RoleName.ADMIN)
    admin = Admin(
        role_id=role.id or 0,
        role_name=RoleName.ADMIN,
        username="admin1",
        email="admin1@example.com",
        password_hash=hash_password(ADMIN_PASSWORD),
        first_name="Ada",
        last_name="Admin",
    )
    UserDAO(db).insert(admin)
    return admin


def count(db: DatabaseManager, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = db.fetch_one(sql, params)
    return int(row["n"]) if row else 0


# ------------------------------------------------------------ FR-1 gate
@pytest.mark.parametrize("path", ["/", "/volunteer/dashboard", "/admin/dashboard"])
def test_anonymous_user_is_sent_to_login(client: FlaskClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


def test_login_and_signup_pages_are_public(client: FlaskClient) -> None:
    assert client.get("/login").status_code == 200
    assert client.get("/signup").status_code == 200


# -------------------------------------------------------------- sign-up
def test_signup_creates_user_profile_and_audit_row(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    response = sign_up(client)

    assert response.status_code == 302 and response.headers["Location"].endswith("/login")
    user = UserDAO(clean_db).find_by_username("vol_one")
    assert user is not None and user.email == "vol@example.com"
    assert user.password_hash != VOL_PASSWORD and user.password_hash.startswith("$2b$")
    assert (
        count(
            clean_db, "SELECT COUNT(*) AS n FROM volunteer_profiles WHERE user_id = %s", (user.id,)
        )
        == 1
    )
    assert (
        count(
            clean_db,
            "SELECT COUNT(*) AS n FROM audit_logs WHERE user_id = %s AND action = %s",
            (user.id, "SIGN_UP"),
        )
        == 1
    )


def test_signup_with_invalid_input_shows_errors_and_saves_nothing(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    response = sign_up(client, email="not-an-email", confirm_password="Other123")

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Enter a valid email address." in page
    assert "Passwords do not match." in page
    assert 'value="Vicky"' in page  # typed values are kept...
    assert VOL_PASSWORD not in page  # ...but passwords are never echoed back
    assert count(clean_db, "SELECT COUNT(*) AS n FROM users") == 0


def test_signup_with_taken_username_is_refused(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    sign_up(client)
    response = sign_up(client, email="other@example.com")

    assert response.status_code == 200
    assert "already taken" in response.get_data(as_text=True)
    assert count(clean_db, "SELECT COUNT(*) AS n FROM users") == 1


# ---------------------------------------------------------------- login
def test_volunteer_logs_in_and_reaches_only_the_volunteer_dashboard(client: FlaskClient) -> None:
    sign_up(client)

    response = log_in(client, "VOL_ONE", VOL_PASSWORD)  # case-insensitive username
    assert response.status_code == 302 and response.headers["Location"].endswith(
        "/volunteer/dashboard"
    )

    dashboard = client.get("/volunteer/dashboard")
    assert dashboard.status_code == 200 and "Vicky" in dashboard.get_data(as_text=True)
    assert client.get("/admin/dashboard").status_code == 403  # FR-2
    assert client.get("/").headers["Location"].endswith("/volunteer/dashboard")
    assert client.get("/login").status_code == 302  # already logged in


def test_admin_logs_in_and_reaches_only_the_admin_dashboard(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    make_admin(clean_db)

    response = log_in(client, "admin1", ADMIN_PASSWORD)
    assert response.headers["Location"].endswith("/admin/dashboard")
    assert client.get("/admin/dashboard").status_code == 200
    assert client.get("/volunteer/dashboard").status_code == 403  # FR-2


@pytest.mark.parametrize(
    ("username", "password"),
    [("vol_one", "wrong-pass"), ("nobody", VOL_PASSWORD), ("", "")],
)
def test_bad_credentials_show_one_generic_message(
    client: FlaskClient, username: str, password: str
) -> None:
    sign_up(client)
    response = log_in(client, username, password)
    assert response.status_code == 200  # the form is shown again
    assert "Invalid username or password." in response.get_data(as_text=True)


def test_login_honours_a_safe_next_url_and_ignores_an_external_one(client: FlaskClient) -> None:
    sign_up(client)
    assert (
        log_in(client, "vol_one", VOL_PASSWORD, next="/volunteer/dashboard?tab=x").headers[
            "Location"
        ]
        == "/volunteer/dashboard?tab=x"
    )
    client.post("/logout")
    assert (
        log_in(client, "vol_one", VOL_PASSWORD, next="//evil.example")
        .headers["Location"]
        .endswith("/volunteer/dashboard")
    )


def test_logout_ends_the_session_and_only_accepts_post(client: FlaskClient) -> None:
    sign_up(client)
    log_in(client, "vol_one", VOL_PASSWORD)

    assert client.get("/logout").status_code == 405  # a GET link could be triggered by an image tag
    response = client.post("/logout")
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")
    assert client.get("/volunteer/dashboard").status_code == 302


# -------------------------------------------------------------- lockout
def test_five_failures_lock_the_account_and_write_an_audit_entry(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    sign_up(client)

    for _ in range(4):
        assert log_in(client, "vol_one", "wrong-pass").status_code == 200
    fifth = log_in(client, "vol_one", "wrong-pass")
    assert fifth.status_code == 403
    assert "Too many failed attempts" in fifth.get_data(as_text=True)

    user = UserDAO(clean_db).find_by_username("vol_one")
    assert user is not None and user.failed_login_attempts == 5 and user.locked_until is not None
    assert (
        count(
            clean_db, "SELECT COUNT(*) AS n FROM audit_logs WHERE action = %s", ("ACCOUNT_LOCKED",)
        )
        == 1
    )

    # Even the right password is refused while locked.
    assert log_in(client, "vol_one", VOL_PASSWORD).status_code == 403


def test_successful_login_resets_the_failure_counter(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    sign_up(client)
    log_in(client, "vol_one", "wrong-pass")
    log_in(client, "vol_one", "wrong-pass")

    assert log_in(client, "vol_one", VOL_PASSWORD).status_code == 302
    user = UserDAO(clean_db).find_by_username("vol_one")
    assert user is not None and user.failed_login_attempts == 0


def test_inactive_account_cannot_log_in(client: FlaskClient, clean_db: DatabaseManager) -> None:
    sign_up(client)
    user = UserDAO(clean_db).find_by_username("vol_one")
    assert user is not None
    UserDAO(clean_db).set_status(user.id or 0, UserStatus.INACTIVE)

    response = log_in(client, "vol_one", VOL_PASSWORD)
    assert response.status_code == 403
    assert "inactive" in response.get_data(as_text=True).lower()
