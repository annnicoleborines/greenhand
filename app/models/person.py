"""Person: abstract base for every login account (Inheritance + Template Method).

Volunteer and Admin both ARE a Person: they share the users-table fields, the
name helpers and the Flask-Login hooks. What differs is `generate_report()`,
which each subclass must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.models.base_entity import BaseEntity
from app.models.enums import RoleName, UserStatus

if TYPE_CHECKING:
    from app.services.reports.base_report import ReportContext, ReportResult


@dataclass(kw_only=True)
class Person(BaseEntity, ABC):
    role_id: int
    role_name: RoleName
    username: str
    email: str
    password_hash: str = ""
    first_name: str
    last_name: str
    phone: str | None = None
    photo_path: str | None = None  # relative to UPLOAD_FOLDER, e.g. "avatars/user_5.png"
    status: UserStatus = UserStatus.ACTIVE
    failed_login_attempts: int = 0
    locked_until: datetime | None = None

    # ---- name helpers used by the header avatar ----
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def initials(self) -> str:
        return f"{self.first_name[:1]}{self.last_name[:1]}".upper()

    # ---- account state ----
    @property
    def is_admin(self) -> bool:
        return self.role_name == RoleName.ADMIN

    def is_locked(self, now: datetime | None = None) -> bool:
        """True while a login lockout is in force."""
        if self.locked_until is None:
            return False
        return self.locked_until > (now or datetime.now())

    # ---- Flask-Login protocol (implemented by hand so mypy keeps the class typed) ----
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)

    # ---- polymorphic behaviour ----
    @abstractmethod
    def generate_report(self, context: ReportContext) -> ReportResult:
        """Each kind of person reports on different things (see Volunteer / Admin)."""

    def to_dict(self) -> dict[str, object]:
        data = super().to_dict()
        data.pop("password_hash", None)  # never expose the hash
        return data
