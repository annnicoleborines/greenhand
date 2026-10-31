"""ProfileService: a volunteer views and edits their own profile (business logic, no SQL).

Rules from the brief:
- Only volunteers have a profile; admins get ForbiddenError (FR-2, checked here too).
- Every change is validated first (FR-4) and written in one transaction with an
  audit entry (FR-6). Audit details name the changed fields, never their values.
- A photo is accepted only when its extension AND its first bytes say PNG, JPEG
  or WEBP, and it is at most 2 MB. Photos live under UPLOAD_FOLDER (outside
  app/static) and are served by a login-protected route, never as public files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.auth.passwords import hash_password, verify_password
from app.auth.roles import require_role
from app.config import Config
from app.dao import AuditLogDAO, UserDAO, VolunteerProfileDAO
from app.database import DatabaseManager
from app.errors import NotFoundError, ValidationError
from app.models import AuditLog, Person, RoleName, Volunteer, VolunteerProfile
from app.schemas.base import validate
from app.schemas.profile import ChangePasswordSchema, ProfileSchema

if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage

log = logging.getLogger(__name__)

MAX_PHOTO_BYTES: int = Config.MAX_PHOTO_BYTES
AVATAR_SUBFOLDER = "avatars"

# Extension -> the bytes a real file of that type starts with ("magic bytes").
# A renamed .exe fails this check even though its extension looks fine.
_PNG_MAGIC = b"\x89PNG"
_JPEG_MAGIC = b"\xff\xd8\xff"
PHOTO_TYPES: dict[str, str] = {"png": "png", "jpg": "jpg", "jpeg": "jpg", "webp": "webp"}

PROFILE_FIELDS = ("address", "birth_date", "emergency_contact_name", "emergency_contact_phone")
CONTACT_FIELDS = ("first_name", "last_name", "phone")


def detect_photo_type(data: bytes) -> str | None:
    """Return "png", "jpg" or "webp" from the file's first bytes, or None."""
    if data.startswith(_PNG_MAGIC):
        return "png"
    if data.startswith(_JPEG_MAGIC):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def check_photo(filename: str | None, data: bytes, *, max_bytes: int = MAX_PHOTO_BYTES) -> str:
    """Validate an uploaded photo; return its normalised extension (png/jpg/webp).

    Pure function (no Flask, no database) so it is easy to unit test. Raises
    ValidationError with the message under the "photo" field.
    """
    name = (filename or "").strip()
    if not name:
        raise _photo_error("Please choose a file.")
    extension = PHOTO_TYPES.get(Path(name).suffix.lower().lstrip("."))
    if extension is None:
        raise _photo_error("Only PNG, JPG and WEBP images are allowed.")
    if not data:
        raise _photo_error("The file is empty.")
    if len(data) > max_bytes:
        raise _photo_error(f"The file is too large (max {max_bytes // (1024 * 1024)} MB).")
    detected = detect_photo_type(data)
    if detected is None:
        raise _photo_error("That file is not a PNG, JPG or WEBP image.")
    if detected != extension:
        raise _photo_error("The file content does not match its extension.")
    return extension


def _photo_error(message: str) -> ValidationError:
    return ValidationError(message, {"photo": message})


@dataclass
class ProfileService:
    db: DatabaseManager
    users: UserDAO
    profiles: VolunteerProfileDAO
    audit: AuditLogDAO
    upload_folder: Path = field(default_factory=lambda: Path(Config.UPLOAD_FOLDER))

    @classmethod
    def build(
        cls, db: DatabaseManager | None = None, upload_folder: str | Path | None = None
    ) -> ProfileService:
        """Convenience constructor used by controllers."""
        manager = db or DatabaseManager()
        return cls(
            db=manager,
            users=UserDAO(manager),
            profiles=VolunteerProfileDAO(manager),
            audit=AuditLogDAO(manager),
            upload_folder=Path(upload_folder or Config.UPLOAD_FOLDER),
        )

    # --------------------------------------------------------------- read
    def get_profile(self, actor: Person) -> Volunteer:
        """Reload the volunteer from the database so the page never shows stale data."""
        require_role(actor, RoleName.VOLUNTEER)
        user = self.users.find_by_id(actor.id or 0)
        if not isinstance(user, Volunteer):
            msg = "Profile not found."
            raise NotFoundError(msg)
        return user

    # --------------------------------------------------------------- edit
    def update_profile(self, actor: Person, form: dict[str, Any]) -> Volunteer:
        """Validate, then save users + volunteer_profiles + audit entry together."""
        require_role(actor, RoleName.VOLUNTEER)
        data = validate(ProfileSchema, form)
        user = self.get_profile(actor)

        profile = user.profile or VolunteerProfile(user_id=user.id or 0)
        changed = [f for f in CONTACT_FIELDS if getattr(user, f) != getattr(data, f)]
        changed += [f for f in PROFILE_FIELDS if getattr(profile, f) != getattr(data, f)]
        if not changed and profile.id is not None:
            return user  # nothing to save, nothing to audit

        for name in CONTACT_FIELDS:
            setattr(user, name, getattr(data, name))
        for name in PROFILE_FIELDS:
            setattr(profile, name, getattr(data, name))

        details = ("Changed: " + ", ".join(changed) + ".") if changed else "Profile created."
        with self.db.transaction():  # both rows and the audit entry, or none
            self.users.update_contact(
                user.id or 0,
                first_name=user.first_name,
                last_name=user.last_name,
                phone=user.phone,
            )
            if profile.id is None:
                self.profiles.insert(profile)  # older accounts may have no profile row yet
            else:
                self.profiles.update(profile)
            self.audit.insert(
                AuditLog(
                    user_id=user.id or 0,
                    action="PROFILE_UPDATED",
                    entity="volunteer_profile",
                    record_reference=profile.id,
                    details=details,
                )
            )
        user.profile = profile
        log.info("profile updated", extra={"user_id": user.id, "action": "PROFILE_UPDATED"})
        return user

    # ----------------------------------------------------------- password
    def change_password(self, actor: Person, form: dict[str, Any]) -> None:
        """Require the current password, then store a new bcrypt hash."""
        require_role(actor, RoleName.VOLUNTEER)
        data = validate(ChangePasswordSchema, form)
        user = self.get_profile(actor)

        if not verify_password(data.current_password, user.password_hash):
            msg = "Current password is incorrect."
            raise ValidationError(msg, {"current_password": msg})

        new_hash = hash_password(data.new_password)
        with self.db.transaction():
            self.users.update_password(user.id or 0, new_hash)
            self.audit.insert(
                AuditLog(
                    user_id=user.id or 0,
                    action="PASSWORD_CHANGED",
                    entity="user",
                    record_reference=user.id,
                    details="Password changed by the account owner.",
                )
            )
        actor.password_hash = new_hash  # keep the logged-in object in step with the database
        log.info("password changed", extra={"user_id": user.id, "action": "PASSWORD_CHANGED"})

    # -------------------------------------------------------------- photo
    def update_photo(self, actor: Person, upload: FileStorage) -> str:
        """Validate and save the avatar; return its path relative to UPLOAD_FOLDER."""
        require_role(actor, RoleName.VOLUNTEER)
        user = self.get_profile(actor)

        data: bytes = upload.read()  # at most ~2 MB (MAX_CONTENT_LENGTH stops bigger requests)
        extension = check_photo(upload.filename, data)

        folder = self.upload_folder / AVATAR_SUBFOLDER
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"user_{user.id}.{extension}"
        photo_path = f"{AVATAR_SUBFOLDER}/{filename}"

        with self.db.transaction():
            self.users.update_photo(user.id or 0, photo_path)
            self.audit.insert(
                AuditLog(
                    user_id=user.id or 0,
                    action="PHOTO_UPDATED",
                    entity="user",
                    record_reference=user.id,
                    details=f"Profile photo replaced ({extension}).",
                )
            )
            # Written last, inside the transaction: a database error means the old
            # file is never touched, and a disk error rolls the database back.
            (folder / filename).write_bytes(data)  # same name as before: overwritten

        # The one deletion in the app: a user's previous avatar with another extension.
        old_name = Path(user.photo_path).name if user.photo_path else None
        if old_name and old_name != filename:
            (folder / old_name).unlink(missing_ok=True)

        actor.photo_path = photo_path
        log.info("photo updated", extra={"user_id": user.id, "action": "PHOTO_UPDATED"})
        return photo_path
