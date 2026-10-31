"""UserDAO: SQL for the users table (joined with roles and volunteer_profiles).

Returns Volunteer or Admin objects depending on the role (polymorphism):
the rest of the app never has to look at role_id to know what kind of Person it has.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.dao.base_dao import BaseDAO
from app.models import Admin, Person, RoleName, UserStatus, Volunteer, VolunteerProfile

# One SELECT used by every "find" so the mapping is always the same.
_SELECT = """
SELECT u.id, u.role_id, u.username, u.email, u.password_hash, u.first_name, u.last_name,
       u.phone, u.photo_path, u.status, u.failed_login_attempts, u.locked_until,
       u.created_at, u.updated_at,
       r.name AS role_name,
       p.id AS profile_id, p.address, p.birth_date, p.emergency_contact_name,
       p.emergency_contact_phone, p.created_at AS profile_created_at,
       p.updated_at AS profile_updated_at
FROM users u
JOIN roles r ON r.id = u.role_id
LEFT JOIN volunteer_profiles p ON p.user_id = u.id
"""


class UserDAO(BaseDAO):
    @staticmethod
    def to_model(row: dict[str, Any]) -> Person:
        """Build an Admin or a Volunteer (with profile, when one exists) from a joined row."""
        common: dict[str, Any] = {
            "id": row["id"],
            "role_id": row["role_id"],
            "role_name": RoleName(row["role_name"]),
            "username": row["username"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "phone": row["phone"],
            "photo_path": row.get("photo_path"),
            "status": UserStatus(row["status"]),
            "failed_login_attempts": row["failed_login_attempts"],
            "locked_until": row["locked_until"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if common["role_name"] == RoleName.ADMIN:
            return Admin(**common)
        profile = None
        if row.get("profile_id") is not None:
            profile = VolunteerProfile(
                id=row["profile_id"],
                user_id=row["id"],
                address=row["address"],
                birth_date=row["birth_date"],
                emergency_contact_name=row["emergency_contact_name"],
                emergency_contact_phone=row["emergency_contact_phone"],
                created_at=row["profile_created_at"],
                updated_at=row["profile_updated_at"],
            )
        return Volunteer(**common, profile=profile)

    # ---- reads ----
    def find_by_id(self, user_id: int) -> Person | None:
        row = self.db.fetch_one(_SELECT + "WHERE u.id = %s", (user_id,))
        return self.to_model(row) if row else None

    def find_by_username(self, username: str) -> Person | None:
        row = self.db.fetch_one(_SELECT + "WHERE u.username = %s", (username,))
        return self.to_model(row) if row else None

    def find_by_email(self, email: str) -> Person | None:
        row = self.db.fetch_one(_SELECT + "WHERE u.email = %s", (email,))
        return self.to_model(row) if row else None

    def username_exists(self, username: str) -> bool:
        row = self.db.fetch_one("SELECT 1 AS found FROM users WHERE username = %s", (username,))
        return row is not None

    def email_exists(self, email: str) -> bool:
        row = self.db.fetch_one("SELECT 1 AS found FROM users WHERE email = %s", (email,))
        return row is not None

    def lock_login_state(self, user_id: int) -> tuple[int, datetime | None] | None:
        """Read the failed-login counter under a row lock (call inside a transaction).

        Parallel wrong guesses then wait for each other instead of all reading the
        same old count, so the 5-attempt limit cannot be skipped by racing.
        """
        row = self.db.fetch_one(
            "SELECT failed_login_attempts, locked_until FROM users WHERE id = %s FOR UPDATE",
            (user_id,),
        )
        if row is None:
            return None
        return int(row["failed_login_attempts"]), row["locked_until"]

    def count_by_role(self, role: RoleName) -> int:
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM users u JOIN roles r ON r.id = u.role_id WHERE r.name = %s",
            (role.value,),
        )
        return int(row["n"]) if row else 0

    def list_by_role(self, role: RoleName, *, limit: int = 50, offset: int = 0) -> list[Person]:
        rows = self.db.fetch_all(
            _SELECT + "WHERE r.name = %s ORDER BY u.last_name, u.first_name LIMIT %s OFFSET %s",
            (role.value, limit, offset),
        )
        return [self.to_model(r) for r in rows]

    def list_admin_ids(self) -> list[int]:
        rows = self.db.fetch_all(
            "SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id WHERE r.name = %s",
            (RoleName.ADMIN.value,),
        )
        return [int(r["id"]) for r in rows]

    def search_volunteers(
        self, search: str | None = None, *, limit: int = 20, offset: int = 0
    ) -> list[Person]:
        """Volunteers (never admins) for the admin list, filtered by a search box.

        The search matches first name, last name, username or email. The LIKE
        wildcards are part of the VALUE ("%ana%"), never pasted into the SQL text.
        """
        sql = _SELECT + "WHERE r.name = %s"
        params: list[Any] = [RoleName.VOLUNTEER.value]
        sql, params = self._add_volunteer_search(sql, params, search)
        sql += " ORDER BY u.last_name, u.first_name, u.id LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        return [self.to_model(r) for r in self.db.fetch_all(sql, tuple(params))]

    def count_volunteers(self, search: str | None = None) -> int:
        """How many volunteers match the same search (for the page count)."""
        sql = "SELECT COUNT(*) AS n FROM users u JOIN roles r ON r.id = u.role_id WHERE r.name = %s"
        params: list[Any] = [RoleName.VOLUNTEER.value]
        sql, params = self._add_volunteer_search(sql, params, search)
        row = self.db.fetch_one(sql, tuple(params))
        return int(row["n"]) if row else 0

    @staticmethod
    def _add_volunteer_search(
        sql: str, params: list[Any], search: str | None
    ) -> tuple[str, list[Any]]:
        """Append the shared LIKE filter so the list and its count always agree."""
        text = (search or "").strip()
        if text:
            sql += (
                " AND (u.first_name LIKE %s OR u.last_name LIKE %s "
                "OR u.username LIKE %s OR u.email LIKE %s)"
            )
            like = "%" + text + "%"
            params.extend([like, like, like, like])
        return sql, params

    # ---- writes ----
    def insert(self, person: Person) -> int:
        """Insert the users row and return the new id (profiles: VolunteerProfileDAO)."""
        new_id = self.db.execute(
            "INSERT INTO users (role_id, username, email, password_hash, first_name, last_name, "
            "phone, photo_path, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                person.role_id,
                person.username,
                person.email,
                person.password_hash,
                person.first_name,
                person.last_name,
                person.phone,
                person.photo_path,
                person.status.value,
            ),
        )
        person.id = new_id
        return new_id

    def update_contact(
        self, user_id: int, *, first_name: str, last_name: str, phone: str | None
    ) -> bool:
        affected = self.db.execute(
            "UPDATE users SET first_name = %s, last_name = %s, phone = %s WHERE id = %s",
            (first_name, last_name, phone, user_id),
        )
        return affected > 0

    def update_photo(self, user_id: int, photo_path: str | None) -> bool:
        """Store the avatar's path relative to app/static (None clears it)."""
        affected = self.db.execute(
            "UPDATE users SET photo_path = %s WHERE id = %s", (photo_path, user_id)
        )
        return affected > 0

    def update_password(self, user_id: int, password_hash: str) -> bool:
        """Replace the bcrypt hash. The service hashes; the DAO only stores."""
        affected = self.db.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id)
        )
        return affected > 0

    def record_failed_login(
        self, user_id: int, attempts: int, locked_until: datetime | None
    ) -> None:
        self.db.execute(
            "UPDATE users SET failed_login_attempts = %s, locked_until = %s WHERE id = %s",
            (attempts, locked_until, user_id),
        )

    def reset_failed_logins(self, user_id: int) -> None:
        self.db.execute(
            "UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE id = %s",
            (user_id,),
        )

    def set_status(self, user_id: int, status: UserStatus) -> bool:
        affected = self.db.execute(
            "UPDATE users SET status = %s WHERE id = %s", (status.value, user_id)
        )
        return affected > 0
