"""AdminUserService: admins manage volunteer accounts (list, (de)activate, reset password).

Rules from the brief:
- Every method is ADMIN-only (`require_role`, checked here as well as on the route).
- Only volunteers are listed or changed here; an admin account is never touched,
  and an admin can never deactivate themself.
- "Reset password" has no email service, so the server makes a temporary password,
  stores only its bcrypt hash and hands the plain text back ONCE to the admin who
  pressed the button. The volunteer gets an in-app notification. The audit entry
  never contains the password.
- Every status change and reset writes an audit_logs entry in the same transaction
  (FR-6).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from app.auth.passwords import hash_password
from app.auth.roles import require_role
from app.dao import AuditLogDAO, NotificationDAO, UserDAO
from app.database import DatabaseManager
from app.errors import ConflictError, NotFoundError
from app.models import AuditLog, Notification, Person, RoleName, UserStatus
from app.services.pagination import Page, clamp_page, offset_for

log = logging.getLogger(__name__)

DEFAULT_PER_PAGE = 20
TEMP_PASSWORD_LENGTH = 12
# No 0/O or 1/l/I: the admin reads the password out to the volunteer, so every
# character must be unambiguous when written down.
_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"
_DIGITS = "23456789"
NOTIFICATION_TYPE_RESET = "PASSWORD_RESET"
RESET_MESSAGE = "Your password was reset by an administrator."


def generate_temporary_password(length: int = TEMP_PASSWORD_LENGTH) -> str:
    """Random letters and digits from `secrets`, with at least one of each.

    One letter and one digit are placed first, the rest is random, and then the
    whole thing is shuffled (also with `secrets`) so the guaranteed characters do
    not always sit at the start.
    """
    if length < 2:
        msg = "A temporary password needs at least two characters."
        raise ValueError(msg)
    chars = [secrets.choice(_LETTERS), secrets.choice(_DIGITS)]
    chars += [secrets.choice(_LETTERS + _DIGITS) for _ in range(length - 2)]
    for i in range(len(chars) - 1, 0, -1):  # Fisher-Yates shuffle with secrets.randbelow
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


@dataclass
class AdminUserService:
    db: DatabaseManager
    users: UserDAO
    notifications: NotificationDAO
    audit: AuditLogDAO

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> AdminUserService:
        """Convenience constructor used by controllers."""
        manager = db or DatabaseManager()
        return cls(
            db=manager,
            users=UserDAO(manager),
            notifications=NotificationDAO(manager),
            audit=AuditLogDAO(manager),
        )

    # --------------------------------------------------------------- read
    def list_volunteers_page(
        self,
        actor: Person,
        search: str | None = None,
        page: int = 1,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> Page[Person]:
        """One page of volunteers matching the search box (name, username or email)."""
        require_role(actor, RoleName.ADMIN)
        page = clamp_page(page)
        text = (search or "").strip() or None
        items = self.users.search_volunteers(
            text, limit=per_page, offset=offset_for(page, per_page)
        )
        total = self.users.count_volunteers(text)
        return Page(items=items, page=page, per_page=per_page, total=total)

    def get(self, actor: Person, user_id: int) -> Person:
        """One volunteer account (the controller needs the username for its messages)."""
        require_role(actor, RoleName.ADMIN)
        return self._get_volunteer(user_id)

    # ------------------------------------------------- activate / deactivate
    def set_active(self, actor: Person, user_id: int, active: bool) -> Person:
        """Flip users.status between ACTIVE and INACTIVE, with the self-lockout guard."""
        require_role(actor, RoleName.ADMIN)
        if not active and user_id == actor.id:
            msg = "You cannot deactivate your own account."
            raise ConflictError(msg)
        user = self._get_volunteer(user_id)

        wanted = UserStatus.ACTIVE if active else UserStatus.INACTIVE
        if user.status == wanted:
            return user  # already in that state: nothing to save, nothing to audit

        action = "USER_ACTIVATED" if active else "USER_DEACTIVATED"
        verb = "activated" if active else "deactivated"
        with self.db.transaction():
            self.users.set_status(user_id, wanted)
            user.status = wanted
            self._audit(actor, action, user, f"Account {user.username} {verb} by an administrator.")
        log.info("user status changed", extra={"user_id": actor.id, "action": action})
        return user

    # ----------------------------------------------------- reset password
    def reset_password(self, actor: Person, user_id: int) -> str:
        """Store a new temporary password's hash and return the plain text once.

        The caller (the controller) flashes it to the admin and forgets it. The
        lockout counter is cleared too, since a locked-out volunteer is the usual
        reason an admin is asked to reset a password.
        """
        require_role(actor, RoleName.ADMIN)
        user = self._get_volunteer(user_id)

        temporary = generate_temporary_password()
        new_hash = hash_password(temporary)
        with self.db.transaction():
            self.users.update_password(user_id, new_hash)
            self.users.reset_failed_logins(user_id)
            self.notifications.insert(
                Notification(user_id=user_id, type=NOTIFICATION_TYPE_RESET, message=RESET_MESSAGE)
            )
            self._audit(
                actor,
                "PASSWORD_RESET",
                user,
                f"Temporary password issued for {user.username}.",  # never the password itself
            )
        user.password_hash = new_hash
        log.info("password reset", extra={"user_id": actor.id, "action": "PASSWORD_RESET"})
        return temporary

    # ------------------------------------------------------------ helpers
    def _get_volunteer(self, user_id: int) -> Person:
        """Load the target account; admins are refused so this page only manages volunteers."""
        user = self.users.find_by_id(user_id)
        if user is None:
            msg = "Volunteer not found."
            raise NotFoundError(msg)
        if user.is_admin:
            msg = "Administrator accounts cannot be managed from this page."
            raise ConflictError(msg)
        return user

    def _audit(self, actor: Person, action: str, user: Person, details: str) -> None:
        self.audit.insert(
            AuditLog(
                user_id=actor.id or 0,
                action=action,
                entity="user",
                record_reference=user.id,
                details=details,
            )
        )
