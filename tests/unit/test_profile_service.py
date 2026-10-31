"""Unit tests for ProfileService (FR-2 role check, FR-4 validation, FR-6 audit entries).

No database: the DAOs are small in-memory fakes, like tests/unit/test_auth_service.py.
Photo tests write to pytest's tmp_path, never to app/static.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.auth.passwords import hash_password, verify_password
from app.errors import DatabaseError, ForbiddenError, NotFoundError, ValidationError
from app.models import Admin, AuditLog, Person, RoleName, Volunteer, VolunteerProfile
from app.services.profile_service import ProfileService, check_photo, detect_photo_type

PASSWORD = "Secret123"
PASSWORD_HASH = hash_password(PASSWORD)  # bcrypt is slow; hash once for the whole module

# Only the first bytes matter to the checker; a real 1x1 image is not needed here.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 64


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
        self.contact_updates: list[tuple[int, str, str, str | None]] = []
        self.photo_updates: list[tuple[int, str | None]] = []
        self.password_updates: list[tuple[int, str]] = []
        self.fail_with: Exception | None = None  # raised by update_photo when set

    def find_by_id(self, user_id: int) -> Person | None:
        return next((u for u in self.users if u.id == user_id), None)

    def update_contact(
        self, user_id: int, *, first_name: str, last_name: str, phone: str | None
    ) -> bool:
        self.contact_updates.append((user_id, first_name, last_name, phone))
        return True

    def update_photo(self, user_id: int, photo_path: str | None) -> bool:
        if self.fail_with is not None:
            raise self.fail_with
        self.photo_updates.append((user_id, photo_path))
        return True

    def update_password(self, user_id: int, password_hash: str) -> bool:
        self.password_updates.append((user_id, password_hash))
        return True


class FakeProfileDAO:
    def __init__(self) -> None:
        self.inserted: list[VolunteerProfile] = []
        self.updated: list[VolunteerProfile] = []

    def insert(self, profile: VolunteerProfile) -> int:
        profile.id = 900 + len(self.inserted)
        self.inserted.append(profile)
        return profile.id

    def update(self, profile: VolunteerProfile) -> bool:
        self.updated.append(profile)
        return True


class FakeAuditDAO:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def insert(self, entry: AuditLog) -> int:
        entry.id = len(self.entries) + 1
        self.entries.append(entry)
        return entry.id


def make_volunteer(*, with_profile: bool = True, **overrides: Any) -> Volunteer:
    fields: dict[str, Any] = {
        "id": 5,
        "role_id": 1,
        "role_name": RoleName.VOLUNTEER,
        "username": "maria",
        "email": "maria@example.com",
        "password_hash": PASSWORD_HASH,
        "first_name": "Maria",
        "last_name": "Santos",
        "phone": "0917 123 4567",
    }
    fields.update(overrides)
    volunteer = Volunteer(**fields)
    if with_profile:
        volunteer.profile = VolunteerProfile(
            id=9, user_id=5, address="1 Green St", birth_date=date(2000, 1, 31)
        )
    return volunteer


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


def make_service(
    *users: Person, upload_folder: Path | None = None
) -> tuple[ProfileService, FakeDB, FakeUserDAO, FakeProfileDAO, FakeAuditDAO]:
    db = FakeDB()
    user_dao = FakeUserDAO(*users)
    profile_dao = FakeProfileDAO()
    audit_dao = FakeAuditDAO()
    service = ProfileService(
        db=db,  # type: ignore[arg-type]
        users=user_dao,  # type: ignore[arg-type]
        profiles=profile_dao,  # type: ignore[arg-type]
        audit=audit_dao,  # type: ignore[arg-type]
        upload_folder=upload_folder or Path("unused"),
    )
    return service, db, user_dao, profile_dao, audit_dao


def profile_form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "first_name": "Maria",
        "last_name": "Santos",
        "phone": "0917 123 4567",
        "address": "1 Green St",
        "birth_date": "2000-01-31",
        "emergency_contact_name": "",
        "emergency_contact_phone": "",
    }
    form.update(overrides)
    return form


def password_form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "current_password": PASSWORD,
        "new_password": "Fresh4567",
        "confirm_password": "Fresh4567",
    }
    form.update(overrides)
    return form


def fake_upload(filename: str | None, data: bytes) -> Any:
    """Stand-in for werkzeug's FileStorage: the service only uses .filename and .read()."""
    return SimpleNamespace(filename=filename, read=lambda: data)


# ------------------------------------------------------------- get_profile
def test_get_profile_reloads_the_volunteer_from_the_database() -> None:
    fresh = make_volunteer(first_name="Updated")
    service, _, _, _, _ = make_service(fresh)
    stale_actor = make_volunteer(first_name="Old")  # what the session still holds

    assert service.get_profile(stale_actor) is fresh


def test_get_profile_raises_not_found_when_the_user_is_gone() -> None:
    service, _, _, _, _ = make_service()
    with pytest.raises(NotFoundError):
        service.get_profile(make_volunteer())


@pytest.mark.parametrize("method", ["get_profile", "update_profile", "change_password"])
def test_admins_are_refused_before_anything_is_read_or_written(method: str) -> None:
    service, db, users, _, audit = make_service(make_admin())
    call = getattr(service, method)
    args: list[Any] = [make_admin()] + ([{}] if method != "get_profile" else [])

    with pytest.raises(ForbiddenError):
        call(*args)
    assert db.transactions == 0 and audit.entries == []


def test_update_photo_refuses_admins(tmp_path: Path) -> None:
    service, _, _, _, _ = make_service(make_admin(), upload_folder=tmp_path)
    with pytest.raises(ForbiddenError):
        service.update_photo(make_admin(), fake_upload("me.png", PNG_BYTES))
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------- update_profile
def test_update_profile_saves_both_rows_and_audits_field_names_only() -> None:
    user = make_volunteer()
    service, db, users, profiles, audit = make_service(user)

    result = service.update_profile(
        user, profile_form(phone="0918 000 0000", emergency_contact_name="Ana Santos")
    )

    assert db.transactions == 1
    assert users.contact_updates == [(5, "Maria", "Santos", "0918 000 0000")]
    assert profiles.updated == [result.profile] and profiles.inserted == []
    assert result.profile is not None and result.profile.emergency_contact_name == "Ana Santos"
    assert result.profile.address == "1 Green St"  # unchanged values are kept
    entry = audit.entries[0]
    assert (entry.action, entry.entity, entry.record_reference) == (
        "PROFILE_UPDATED",
        "volunteer_profile",
        9,
    )
    assert entry.details is not None
    assert "phone" in entry.details and "emergency_contact_name" in entry.details
    assert "0918" not in entry.details and "Ana" not in entry.details  # names, never values


def test_update_profile_inserts_a_profile_row_when_none_exists() -> None:
    user = make_volunteer(with_profile=False)
    service, _, _, profiles, audit = make_service(user)

    result = service.update_profile(user, profile_form())

    assert len(profiles.inserted) == 1 and profiles.updated == []
    assert result.profile is profiles.inserted[0]
    assert result.profile.user_id == 5 and result.profile.address == "1 Green St"
    assert audit.entries[0].record_reference == result.profile.id


def test_update_profile_with_no_changes_writes_nothing() -> None:
    user = make_volunteer()
    service, db, users, profiles, audit = make_service(user)

    service.update_profile(user, profile_form())

    assert db.transactions == 0 and users.contact_updates == []
    assert profiles.updated == [] and audit.entries == []


def test_update_profile_rejects_invalid_form_before_touching_the_database() -> None:
    user = make_volunteer()
    service, db, users, _, audit = make_service(user)

    with pytest.raises(ValidationError) as exc_info:
        service.update_profile(user, profile_form(first_name="", phone="abc"))

    assert set(exc_info.value.errors) == {"first_name", "phone"}
    assert db.transactions == 0 and users.contact_updates == [] and audit.entries == []


# --------------------------------------------------------- change_password
def test_change_password_stores_a_new_hash_and_audits() -> None:
    user = make_volunteer()
    service, db, users, _, audit = make_service(user)

    service.change_password(user, password_form())

    assert db.transactions == 1
    (user_id, new_hash), *_ = users.password_updates
    assert user_id == 5 and new_hash != "Fresh4567"  # never stored in plain text
    assert verify_password("Fresh4567", new_hash)
    assert user.password_hash == new_hash
    assert [(e.action, e.entity, e.record_reference) for e in audit.entries] == [
        ("PASSWORD_CHANGED", "user", 5)
    ]
    assert audit.entries[0].details is not None and "Fresh4567" not in audit.entries[0].details


def test_change_password_rejects_wrong_current_password() -> None:
    user = make_volunteer()
    service, db, users, _, audit = make_service(user)

    with pytest.raises(ValidationError) as exc_info:
        service.change_password(user, password_form(current_password="WrongOne1"))

    assert exc_info.value.errors == {"current_password": "Current password is incorrect."}
    assert db.transactions == 0 and users.password_updates == [] and audit.entries == []


def test_change_password_rejects_same_password_as_current() -> None:
    user = make_volunteer()
    service, _, users, _, _ = make_service(user)

    with pytest.raises(ValidationError) as exc_info:
        service.change_password(
            user, password_form(new_password=PASSWORD, confirm_password=PASSWORD)
        )

    assert "different" in exc_info.value.errors["new_password"]
    assert users.password_updates == []


# ------------------------------------------------------------ check_photo
def test_detect_photo_type_reads_magic_bytes() -> None:
    assert detect_photo_type(PNG_BYTES) == "png"
    assert detect_photo_type(JPEG_BYTES) == "jpg"
    assert detect_photo_type(WEBP_BYTES) == "webp"
    assert detect_photo_type(b"GIF89a" + b"\x00" * 10) is None


@pytest.mark.parametrize(
    ("filename", "data", "expected"),
    [
        ("me.png", PNG_BYTES, "png"),
        ("Photo.JPG", JPEG_BYTES, "jpg"),
        ("photo.jpeg", JPEG_BYTES, "jpg"),  # .jpeg is normalised to jpg
        ("me.webp", WEBP_BYTES, "webp"),
    ],
    ids=["png", "jpg-upper", "jpeg", "webp"],
)
def test_check_photo_accepts_matching_extension_and_content(
    filename: str, data: bytes, expected: str
) -> None:
    assert check_photo(filename, data) == expected


@pytest.mark.parametrize(
    ("filename", "data", "fragment"),
    [
        ("", PNG_BYTES, "choose a file"),
        (None, PNG_BYTES, "choose a file"),
        ("virus.exe", PNG_BYTES, "Only PNG, JPG and WEBP"),
        ("me.gif", b"GIF89a" + b"\x00" * 10, "Only PNG, JPG and WEBP"),
        ("me.png", b"", "empty"),
        ("me.png", JPEG_BYTES, "does not match"),  # extension and content disagree
        ("me.jpg", b"<html>not an image</html>", "not a PNG, JPG or WEBP"),
        ("me.png", PNG_BYTES + b"\x00" * (2 * 1024 * 1024), "too large (max 2 MB)"),
    ],
    # Explicit ids: the default ids would contain the (2 MB) file bytes.
    ids=[
        "empty-name",
        "no-name",
        "exe",
        "gif",
        "empty-file",
        "png-name-jpeg-bytes",
        "html-not-image",
        "too-large",
    ],
)
def test_check_photo_rejects_bad_files(filename: str | None, data: bytes, fragment: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        check_photo(filename, data)
    assert fragment in exc_info.value.errors["photo"]
    assert exc_info.value.message == exc_info.value.errors["photo"]


def test_check_photo_max_size_is_configurable() -> None:
    with pytest.raises(ValidationError, match="too large"):
        check_photo("me.png", PNG_BYTES, max_bytes=16)


# ----------------------------------------------------------- update_photo
def test_update_photo_saves_file_updates_path_and_audits(tmp_path: Path) -> None:
    user = make_volunteer()
    service, db, users, _, audit = make_service(user, upload_folder=tmp_path)

    path = service.update_photo(user, fake_upload("holiday.PNG", PNG_BYTES))

    assert path == "avatars/user_5.png"
    assert (tmp_path / "avatars" / "user_5.png").read_bytes() == PNG_BYTES
    assert users.photo_updates == [(5, path)] and db.transactions == 1
    assert user.photo_path == path
    assert [(e.action, e.entity, e.record_reference) for e in audit.entries] == [
        ("PHOTO_UPDATED", "user", 5)
    ]


def test_update_photo_removes_the_old_avatar_with_a_different_extension(tmp_path: Path) -> None:
    user = make_volunteer(photo_path="avatars/user_5.jpg")
    old_file = tmp_path / "avatars" / "user_5.jpg"
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(JPEG_BYTES)
    service, _, _, _, _ = make_service(user, upload_folder=tmp_path)

    service.update_photo(user, fake_upload("new.webp", WEBP_BYTES))

    assert not old_file.exists()  # the only deletion in the app: the user's own old avatar
    assert sorted(p.name for p in old_file.parent.iterdir()) == ["user_5.webp"]


def test_update_photo_keeps_the_old_file_when_the_database_fails(tmp_path: Path) -> None:
    """The file is written inside the transaction, after the SQL: no row, no file change."""
    user = make_volunteer(photo_path="avatars/user_5.png")
    old_file = tmp_path / "avatars" / "user_5.png"
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(PNG_BYTES)
    service, _, users, _, audit = make_service(user, upload_folder=tmp_path)
    users.fail_with = DatabaseError("Database is not available.")

    with pytest.raises(DatabaseError):
        service.update_photo(user, fake_upload("new.png", PNG_BYTES + b"NEW"))

    assert old_file.read_bytes() == PNG_BYTES  # the live avatar was not replaced
    assert audit.entries == [] and user.photo_path == "avatars/user_5.png"


def test_update_photo_rejects_bad_file_without_writing_anything(tmp_path: Path) -> None:
    user = make_volunteer()
    service, db, users, _, audit = make_service(user, upload_folder=tmp_path)

    with pytest.raises(ValidationError) as exc_info:
        service.update_photo(user, fake_upload("me.png", JPEG_BYTES))

    assert "photo" in exc_info.value.errors
    assert list(tmp_path.iterdir()) == [] and users.photo_updates == []
    assert db.transactions == 0 and audit.entries == []
