"""Integration tests for the volunteer profile pages (FR-2, FR-3, FR-4, FR-6).

They drive the real `profile` controller with Flask's test client against the
test database: view, edit, change password and change photo. Photo tests use a
Flask app whose UPLOAD_FOLDER points at pytest's tmp_path, so nothing is ever
written under app/static.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from app import create_app
from app.config import TestConfig
from app.dao import UserDAO
from app.database import DatabaseManager
from app.models import Volunteer
from tests.integration.test_auth_flow import VOL_PASSWORD, count, log_in, make_admin, sign_up

NEW_PASSWORD = "Fresh4567"


def tiny_png() -> bytes:
    """A real 1x1 PNG (one brand-green pixel), built from its three chunks."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8-bit RGB
    pixel = zlib.compress(b"\x00" + bytes.fromhex("1e6b3a"))  # filter byte + RGB
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")
    )


def profile_form(**overrides: Any) -> dict[str, str]:
    form = {
        "first_name": "Vicky",
        "last_name": "Vol",
        "phone": "0917 999 0000",
        "address": "456 Forest Ave",
        "birth_date": "1998-05-20",
        "emergency_contact_name": "Victor Vol",
        "emergency_contact_phone": "0918 111 2222",
    }
    form.update(overrides)
    return form


def logged_in_volunteer(client: FlaskClient, db: DatabaseManager) -> Volunteer:
    sign_up(client)
    log_in(client, "vol_one", VOL_PASSWORD)
    user = UserDAO(db).find_by_username("vol_one")
    assert isinstance(user, Volunteer)
    return user


def upload_photo(client: FlaskClient, filename: str, data: bytes) -> TestResponse:
    return client.post(
        "/profile/photo",
        data={"photo": (BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


@pytest.fixture
def upload_app(clean_db: DatabaseManager, tmp_path: Path) -> Iterator[Flask]:
    """Like the shared `app` fixture, but uploads land in a temporary folder."""
    flask_app = create_app(TestConfig, overrides={"UPLOAD_FOLDER": str(tmp_path)})
    with flask_app.app_context():
        yield flask_app


@pytest.fixture
def upload_client(upload_app: Flask) -> FlaskClient:
    return upload_app.test_client()


# ------------------------------------------------------------- access (FR-2)
def test_profile_pages_require_login(client: FlaskClient) -> None:
    for path in ("/profile/", "/profile/edit", "/profile/password", "/profile/photo/avatars/x.png"):
        response = client.get(path)
        assert response.status_code == 302 and response.headers["Location"].startswith("/login")


def test_admin_has_no_profile_and_gets_403(client: FlaskClient, clean_db: DatabaseManager) -> None:
    make_admin(clean_db)
    log_in(client, "admin1", "Admin1234")

    assert client.get("/profile/").status_code == 403
    assert client.get("/profile/edit").status_code == 403
    assert client.get("/profile/password").status_code == 403
    assert upload_photo(client, "me.png", tiny_png()).status_code == 403


# ----------------------------------------------------------------- view page
def test_profile_page_shows_details_and_placeholders(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_volunteer(client, clean_db)

    response = client.get("/profile/")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Vicky Vol" in page and "vol@example.com" in page and "0917 123 4567" in page
    assert "Not provided" in page  # birth date and emergency contact are still empty
    assert "Edit Profile" in page and "Change Password" in page and "Change Photo" in page
    assert 'aria-current="page"' in page  # "My Profile" is highlighted in the sidebar


def test_dashboard_card_links_to_the_profile(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_volunteer(client, clean_db)
    assert 'href="/profile/"' in client.get("/volunteer/dashboard").get_data(as_text=True)


# ---------------------------------------------------------------- edit (FR-3)
def test_edit_form_is_prefilled_from_the_database(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_volunteer(client, clean_db)

    page = client.get("/profile/edit").get_data(as_text=True)
    assert 'value="Vicky"' in page and 'value="123 Green St"' in page
    assert 'type="date"' in page and 'aria-current="page"' in page


def test_edit_profile_updates_users_profiles_and_audit(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    user = logged_in_volunteer(client, clean_db)

    response = client.post("/profile/edit", data=profile_form(first_name="Victoria"))

    assert response.status_code == 302 and response.headers["Location"].endswith("/profile/")
    saved = UserDAO(clean_db).find_by_id(user.id or 0)
    assert isinstance(saved, Volunteer) and saved.profile is not None
    assert saved.first_name == "Victoria" and saved.phone == "0917 999 0000"
    assert saved.profile.address == "456 Forest Ave"
    assert str(saved.profile.birth_date) == "1998-05-20"
    assert saved.profile.emergency_contact_name == "Victor Vol"

    row = clean_db.fetch_one(
        "SELECT details FROM audit_logs WHERE user_id = %s AND action = %s",
        (user.id, "PROFILE_UPDATED"),
    )
    assert row is not None
    details = str(row["details"])
    assert "first_name" in details and "phone" in details and "birth_date" in details
    assert "Victoria" not in details and "0917 999 0000" not in details  # names only, no values

    page = client.get("/profile/").get_data(as_text=True)
    assert "Victoria Vol" in page and "May 20, 1998" in page and "Victor Vol" in page


def test_edit_profile_with_invalid_input_shows_errors_and_saves_nothing(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    user = logged_in_volunteer(client, clean_db)

    response = client.post(
        "/profile/edit",
        data=profile_form(first_name="", phone="abc", birth_date="2020-01-01"),
    )

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Enter a valid phone number." in page
    assert "Volunteers must be at least 13 years old." in page  # the error, not the form hint
    assert 'id="birth_date-error"' in page
    assert 'value="456 Forest Ave"' in page  # typed values are kept
    saved = UserDAO(clean_db).find_by_id(user.id or 0)
    assert isinstance(saved, Volunteer) and saved.first_name == "Vicky"
    assert saved.phone == "0917 123 4567"
    assert (
        count(
            clean_db, "SELECT COUNT(*) AS n FROM audit_logs WHERE action = %s", ("PROFILE_UPDATED",)
        )
        == 0
    )


# ------------------------------------------------------------------ password
def test_change_password_then_only_the_new_password_logs_in(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    user = logged_in_volunteer(client, clean_db)

    response = client.post(
        "/profile/password",
        data={
            "current_password": VOL_PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 302 and response.headers["Location"].endswith("/profile/")
    assert (
        count(
            clean_db,
            "SELECT COUNT(*) AS n FROM audit_logs WHERE user_id = %s AND action = %s",
            (user.id, "PASSWORD_CHANGED"),
        )
        == 1
    )

    client.post("/logout")
    assert log_in(client, "vol_one", VOL_PASSWORD).status_code == 200  # old: refused
    assert log_in(client, "vol_one", NEW_PASSWORD).status_code == 302  # new: works


def test_change_password_with_wrong_current_password_is_refused(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    user = logged_in_volunteer(client, clean_db)

    response = client.post(
        "/profile/password",
        data={
            "current_password": "not-my-password",
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
    )

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Current password is incorrect." in page
    assert NEW_PASSWORD not in page  # passwords are never echoed back
    saved = UserDAO(clean_db).find_by_id(user.id or 0)
    assert saved is not None and saved.password_hash == user.password_hash


@pytest.mark.parametrize(
    ("new_password", "confirm_password", "message"),
    [
        ("onlyletters", "onlyletters", "at least one letter and one number"),
        (NEW_PASSWORD, "Different1", "Passwords do not match."),
        (VOL_PASSWORD, VOL_PASSWORD, "must be different from the current one"),
    ],
    ids=["weak", "mismatch", "same-as-current"],
)
def test_change_password_shows_inline_errors(
    client: FlaskClient,
    clean_db: DatabaseManager,
    new_password: str,
    confirm_password: str,
    message: str,
) -> None:
    logged_in_volunteer(client, clean_db)

    response = client.post(
        "/profile/password",
        data={
            "current_password": VOL_PASSWORD,
            "new_password": new_password,
            "confirm_password": confirm_password,
        },
    )

    assert response.status_code == 200
    assert message in response.get_data(as_text=True)


# --------------------------------------------------------------------- photo
def test_photo_upload_saves_the_file_and_sets_photo_path(
    upload_client: FlaskClient, clean_db: DatabaseManager, tmp_path: Path
) -> None:
    user = logged_in_volunteer(upload_client, clean_db)

    response = upload_photo(upload_client, "me.PNG", tiny_png())

    assert response.status_code == 302 and response.headers["Location"].endswith("/profile/")
    saved_file = tmp_path / "avatars" / f"user_{user.id}.png"
    assert saved_file.read_bytes() == tiny_png()
    saved = UserDAO(clean_db).find_by_id(user.id or 0)
    assert saved is not None and saved.photo_path == f"avatars/user_{user.id}.png"
    assert (
        count(
            clean_db,
            "SELECT COUNT(*) AS n FROM audit_logs WHERE user_id = %s AND action = %s",
            (user.id, "PHOTO_UPDATED"),
        )
        == 1
    )

    page = upload_client.get("/profile/").get_data(as_text=True)
    assert "Your photo has been updated." in page
    photo_url = f"/profile/photo/avatars/user_{user.id}.png"
    assert f'src="{photo_url}"' in page  # header + profile card
    assert "/static/" not in photo_url  # never served as a public static file

    served = upload_client.get(photo_url)
    assert served.status_code == 200 and served.mimetype == "image/png"
    assert served.get_data() == tiny_png()


def test_photos_are_not_public(
    upload_client: FlaskClient, clean_db: DatabaseManager, tmp_path: Path
) -> None:
    """FR-1: anyone could guess user_<id>.png, so the photo route needs a login."""
    user = logged_in_volunteer(upload_client, clean_db)
    upload_photo(upload_client, "me.png", tiny_png())
    photo_url = f"/profile/photo/avatars/user_{user.id}.png"
    upload_client.post("/logout")

    response = upload_client.get(photo_url)
    assert response.status_code == 302 and response.headers["Location"].startswith("/login")
    assert upload_client.get("/static/uploads/avatars/user_1.png").status_code == 404


def test_missing_or_escaping_photo_path_is_404(
    upload_client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_volunteer(upload_client, clean_db)
    assert upload_client.get("/profile/photo/avatars/user_999.png").status_code == 404
    assert upload_client.get("/profile/photo/..%2F..%2F.env").status_code == 404


@pytest.mark.parametrize(
    ("filename", "data", "message"),
    [
        ("notes.txt", b"hello", "Only PNG, JPG and WEBP images are allowed."),
        ("fake.png", b"\xff\xd8\xff\xe0" + b"\x00" * 16, "does not match its extension"),
        ("empty.png", b"", "The file is empty."),
    ],
    ids=["wrong-extension", "extension-mismatch", "empty"],
)
def test_bad_photo_is_rejected_with_a_message(
    upload_client: FlaskClient,
    clean_db: DatabaseManager,
    tmp_path: Path,
    filename: str,
    data: bytes,
    message: str,
) -> None:
    user = logged_in_volunteer(upload_client, clean_db)

    response = upload_photo(upload_client, filename, data)

    assert response.status_code == 302
    assert message in upload_client.get("/profile/").get_data(as_text=True)
    assert not (tmp_path / "avatars").exists() or not any((tmp_path / "avatars").iterdir())
    saved = UserDAO(clean_db).find_by_id(user.id or 0)
    assert saved is not None and saved.photo_path is None


def test_missing_photo_shows_a_message(client: FlaskClient, clean_db: DatabaseManager) -> None:
    logged_in_volunteer(client, clean_db)

    response = client.post("/profile/photo", data={}, content_type="multipart/form-data")

    assert response.status_code == 302
    assert "Please choose a file." in client.get("/profile/").get_data(as_text=True)


def test_oversized_upload_gets_a_friendly_413_page(
    upload_client: FlaskClient, clean_db: DatabaseManager, tmp_path: Path
) -> None:
    logged_in_volunteer(upload_client, clean_db)
    big = tiny_png() + b"\x00" * (3 * 1024 * 1024)  # 3 MB: more than MAX_CONTENT_LENGTH

    response = upload_photo(upload_client, "big.png", big)

    assert response.status_code == 413
    assert "The file is too large (max 2 MB)." in response.get_data(as_text=True)
    assert not (tmp_path / "avatars").exists()
