"""AuthService: sign-up, login and lockout rules (business logic, no SQL, no Flask).

Rules from the brief:
- Sign-up creates a user AND a volunteer profile in one transaction.
- Wrong username and wrong password give the SAME message.
- 5 failed attempts -> locked for 15 minutes. Counter resets on success.
- Inactive accounts cannot log in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.auth.passwords import hash_password, verify_password
from app.dao import AuditLogDAO, RoleDAO, UserDAO, VolunteerProfileDAO
from app.database import DatabaseManager
from app.errors import ConflictError, ForbiddenError, ValidationError
from app.models import AuditLog, Person, RoleName, Volunteer, VolunteerProfile
from app.schemas.auth import LoginSchema, SignUpSchema
from app.schemas.base import validate

log = logging.getLogger(__name__)

GENERIC_LOGIN_ERROR = "Invalid username or password."
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


@dataclass
class AuthService:
    db: DatabaseManager
    users: UserDAO
    profiles: VolunteerProfileDAO
    roles: RoleDAO
    audit: AuditLogDAO

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> AuthService:
        """Convenience constructor used by controllers."""
        manager = db or DatabaseManager()
        return cls(
            db=manager,
            users=UserDAO(manager),
            profiles=VolunteerProfileDAO(manager),
            roles=RoleDAO(manager),
            audit=AuditLogDAO(manager),
        )

    # ------------------------------------------------------------ sign-up
    def register_volunteer(self, form: dict[str, Any]) -> Volunteer:
        """Validate, check uniqueness, then insert user + profile + audit entry together."""
        data = validate(SignUpSchema, form)

        errors: dict[str, str] = {}
        if self.users.username_exists(data.username):
            errors["username"] = "That username is already taken."
        if self.users.email_exists(data.email):
            errors["email"] = "That email is already registered."
        if errors:
            raise ConflictError("Please choose a different username or email.", errors)

        role = self.roles.find_by_name(RoleName.VOLUNTEER)
        volunteer = Volunteer(
            role_id=role.id or 0,
            role_name=RoleName.VOLUNTEER,
            username=data.username,
            email=data.email,
            password_hash=hash_password(data.password),
            first_name=data.first_name,
            last_name=data.last_name,
            phone=data.phone,
        )
        with self.db.transaction():  # all three rows, or none (FR-8 duplicates roll back too)
            self.users.insert(volunteer)
            profile = VolunteerProfile(user_id=volunteer.id or 0, address=data.address)
            self.profiles.insert(profile)
            volunteer.profile = profile
            self.audit.insert(
                AuditLog(
                    user_id=volunteer.id or 0,
                    action="SIGN_UP",
                    entity="user",
                    record_reference=volunteer.id,
                    details=f"Volunteer account created for {volunteer.username}.",
                )
            )
        log.info("volunteer registered", extra={"user_id": volunteer.id, "action": "SIGN_UP"})
        return volunteer

    # -------------------------------------------------------------- login
    def login(self, form: dict[str, Any], *, now: datetime | None = None) -> Person:
        """Return the Person on success; raise a typed error otherwise."""
        now = now or datetime.now()
        try:
            data = validate(LoginSchema, form)
        except ValidationError as exc:
            raise ValidationError(GENERIC_LOGIN_ERROR) from exc

        user = self.users.find_by_username(data.username.lower())
        if user is None:
            raise ValidationError(GENERIC_LOGIN_ERROR)

        if user.is_locked(now):
            raise self._locked_error(user, now)

        if not verify_password(data.password, user.password_hash):
            self._record_failure(user, now)
            if user.is_locked(now):  # this attempt triggered the lock: say so now
                raise self._locked_error(user, now)
            raise ValidationError(GENERIC_LOGIN_ERROR)

        if not user.is_active:
            msg = "This account is inactive. Please contact an administrator."
            raise ForbiddenError(msg)

        if user.failed_login_attempts or user.locked_until:
            self.users.reset_failed_logins(user.id or 0)
            user.failed_login_attempts = 0
            user.locked_until = None
        log.info("login ok", extra={"user_id": user.id, "action": "LOGIN"})
        return user

    # ------------------------------------------------------------ helpers
    def _record_failure(self, user: Person, now: datetime) -> None:
        """Add one failed attempt, reading the current count under a row lock.

        The `user` object was loaded before the slow bcrypt check, so a parallel
        guess may have changed the row since. The lock makes attempts queue up.
        """
        with self.db.transaction():
            state = self.users.lock_login_state(user.id or 0)
            previous, current_lock = state or (user.failed_login_attempts, user.locked_until)
            if current_lock is not None and current_lock > now:
                # Another request locked the account a moment ago: keep that lock.
                user.failed_login_attempts, user.locked_until = previous, current_lock
                return
            # A lockout that already expired starts a fresh count.
            attempts = (0 if current_lock is not None else previous) + 1
            locked_until = None
            if attempts >= MAX_FAILED_ATTEMPTS:
                locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                details = f"Locked for {LOCKOUT_MINUTES} minutes after {attempts} failed logins."
                self.audit.insert(
                    AuditLog(
                        user_id=user.id or 0,
                        action="ACCOUNT_LOCKED",
                        entity="user",
                        record_reference=user.id,
                        details=details,
                    )
                )
                log.warning(
                    "account locked", extra={"user_id": user.id, "action": "ACCOUNT_LOCKED"}
                )
            self.users.record_failed_login(user.id or 0, attempts, locked_until)
        user.failed_login_attempts = attempts
        user.locked_until = locked_until

    def _locked_error(self, user: Person, now: datetime) -> ForbiddenError:
        minutes_left = self._minutes_left(user, now)
        msg = f"Too many failed attempts. Try again in {minutes_left} minute(s)."
        return ForbiddenError(msg)

    @staticmethod
    def _minutes_left(user: Person, now: datetime) -> int:
        if user.locked_until is None:
            return 0
        seconds = (user.locked_until - now).total_seconds()
        return max(1, int(seconds // 60) + (1 if seconds % 60 else 0))
