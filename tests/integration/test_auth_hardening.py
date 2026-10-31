"""Integration tests added after the Phase 1 code review.

Each test here reproduces one confirmed finding against the real database:
the FR-8 error page while logged in, deactivated accounts with a live session,
rate limits, the `next` redirect, and the 72-byte password limit.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.config import TestConfig
from app.dao import UserDAO
from app.database import DatabaseManager
from app.extensions import limiter
from app.models import UserStatus
from tests.integration.test_auth_flow import VOL_PASSWORD, log_in, sign_up


@pytest.fixture
def plain_client(clean_db: DatabaseManager) -> FlaskClient:
    """A client WITHOUT the shared app context the `client` fixture pushes.

    Flask-Login caches the loaded user on `g`; inside one long-lived app context
    that cache would leak from one request to the next and hide the bugs below.
    """
    return create_app(TestConfig).test_client()


# ---------------------------------------------------- FR-8 while logged in
def test_logged_in_user_gets_the_friendly_503_page_when_database_is_down(
    plain_client: FlaskClient, clean_db: DatabaseManager
) -> None:
    sign_up(plain_client)
    log_in(plain_client, "vol_one", VOL_PASSWORD)
    assert plain_client.get("/volunteer/dashboard").status_code == 200

    clean_db.configure(database=clean_db.database_name, port=1)  # nothing listens on port 1
    try:
        for path in ("/health", "/volunteer/dashboard"):
            response = plain_client.get(path)
            assert response.status_code == 503, path
            assert "Is MySQL running in XAMPP?" in response.get_data(as_text=True), path
    finally:
        clean_db.configure(database=clean_db.database_name)


# ------------------------------------------------- deactivated mid-session
def test_deactivated_user_is_logged_out_on_the_next_request(
    plain_client: FlaskClient, clean_db: DatabaseManager
) -> None:
    sign_up(plain_client)
    log_in(plain_client, "vol_one", VOL_PASSWORD)
    user = UserDAO(clean_db).find_by_username("vol_one")
    assert user is not None
    UserDAO(clean_db).set_status(user.id or 0, UserStatus.INACTIVE)

    response = plain_client.get("/volunteer/dashboard")
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")
    login_page = plain_client.get("/login")
    assert login_page.status_code == 200  # session is gone, so no redirect to a dashboard
    assert "inactive" in login_page.get_data(as_text=True).lower()


# ------------------------------------------------------------ rate limits
@pytest.fixture
def limited_app(clean_db: DatabaseManager) -> Iterator[Flask]:
    app = create_app(TestConfig, overrides={"RATELIMIT_ENABLED": True})
    limiter.reset()  # the in-memory counters live in the shared limiter object
    yield app
    limiter.reset()
    create_app(TestConfig)  # re-initialise the shared limiter with limits off again


def test_login_is_limited_to_ten_posts_per_minute(limited_app: Flask) -> None:
    client = limited_app.test_client()
    for _ in range(10):
        assert (
            client.post("/login", data={"username": "nobody", "password": "x"}).status_code == 200
        )
    blocked = client.post("/login", data={"username": "nobody", "password": "x"})
    assert blocked.status_code == 429
    assert "429" in blocked.get_data(as_text=True)  # friendly error page, not a crash
    assert client.get("/login").status_code == 200  # only POST is limited


def test_signup_is_limited_to_five_posts_per_minute(limited_app: Flask) -> None:
    client = limited_app.test_client()
    for _ in range(5):
        assert client.post("/signup", data={"username": "x"}).status_code == 200
    assert client.post("/signup", data={"username": "x"}).status_code == 429


# ------------------------------------------------------------- next= param
def test_next_url_survives_the_login_form_round_trip(client: FlaskClient) -> None:
    sign_up(client)
    page = client.get("/login?next=/volunteer/dashboard%3Ftab%3Dx").get_data(as_text=True)
    assert 'name="next" value="/volunteer/dashboard?tab=x"' in page

    response = client.post(
        "/login",
        data={
            "username": "vol_one",
            "password": VOL_PASSWORD,
            "next": "/volunteer/dashboard?tab=x",
        },
    )
    assert response.headers["Location"] == "/volunteer/dashboard?tab=x"


@pytest.mark.parametrize(
    "evil", ["//evil.example", "/\\evil.example", "/\\\\evil.example", "http://evil.example/"]
)
def test_unsafe_next_urls_fall_back_to_the_dashboard(client: FlaskClient, evil: str) -> None:
    sign_up(client)
    response = client.post(
        "/login", data={"username": "vol_one", "password": VOL_PASSWORD, "next": evil}
    )
    assert response.headers["Location"].endswith("/volunteer/dashboard")


def test_logged_in_user_is_sent_away_from_signup(client: FlaskClient) -> None:
    sign_up(client)
    log_in(client, "vol_one", VOL_PASSWORD)
    response = client.get("/signup")
    assert response.status_code == 302 and response.headers["Location"].endswith(
        "/volunteer/dashboard"
    )


# ------------------------------------------------------ 72-byte passwords
def test_signup_with_a_72_character_multibyte_password_shows_a_field_error(
    client: FlaskClient,
) -> None:
    long_password = "a1" + "é" * 70  # 72 characters but 142 bytes: bcrypt would refuse it
    response = sign_up(client, password=long_password, confirm_password=long_password)
    assert response.status_code == 200
    assert "too long" in response.get_data(as_text=True)
