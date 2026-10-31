"""RegistrationDAO: SQL for the registrations table."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from app.dao.base_dao import BaseDAO
from app.models import ActivityStatus, Registration, RegistrationStatus

_SELECT = """
SELECT g.id, g.activity_id, g.user_id, g.status, g.registration_date, g.reviewed_at,
       g.reviewed_by, g.remarks,
       a.title AS activity_title, a.activity_date,
       a.start_time AS activity_start_time, a.end_time AS activity_end_time,
       a.status AS activity_status, l.location_name,
       CONCAT(u.first_name, ' ', u.last_name) AS volunteer_name
FROM registrations g
JOIN activities a ON a.id = g.activity_id
JOIN locations l ON l.id = a.location_id
JOIN users u ON u.id = g.user_id
"""


class RegistrationDAO(BaseDAO):
    @staticmethod
    def to_model(row: dict[str, Any]) -> Registration:
        return Registration(
            id=row["id"],
            activity_id=row["activity_id"],
            user_id=row["user_id"],
            status=RegistrationStatus(row["status"]),
            registration_date=row["registration_date"],
            reviewed_at=row["reviewed_at"],
            reviewed_by=row["reviewed_by"],
            remarks=row["remarks"],
            activity_title=row.get("activity_title"),
            activity_date=BaseDAO.to_date(row["activity_date"])
            if row.get("activity_date")
            else None,
            activity_start_time=(
                BaseDAO.to_time(row["activity_start_time"])
                if row.get("activity_start_time")
                else None
            ),
            activity_end_time=(
                BaseDAO.to_time(row["activity_end_time"]) if row.get("activity_end_time") else None
            ),
            activity_status=(
                ActivityStatus(row["activity_status"]) if row.get("activity_status") else None
            ),
            location_name=row.get("location_name"),
            volunteer_name=row.get("volunteer_name"),
        )

    # ---- reads ----
    def find_by_id(self, registration_id: int) -> Registration | None:
        row = self.db.fetch_one(_SELECT + "WHERE g.id = %s", (registration_id,))
        return self.to_model(row) if row else None

    def find_by_activity_and_user(self, activity_id: int, user_id: int) -> Registration | None:
        row = self.db.fetch_one(
            _SELECT + "WHERE g.activity_id = %s AND g.user_id = %s", (activity_id, user_id)
        )
        return self.to_model(row) if row else None

    def list_by_user(
        self, user_id: int, status: RegistrationStatus | None = None
    ) -> list[Registration]:
        sql = _SELECT + "WHERE g.user_id = %s"
        params: list[Any] = [user_id]
        if status is not None:
            sql += " AND g.status = %s"
            params.append(status.value)
        sql += " ORDER BY g.registration_date DESC"
        return [self.to_model(r) for r in self.db.fetch_all(sql, tuple(params))]

    def list_by_status(
        self, status: RegistrationStatus, *, limit: int = 50, offset: int = 0
    ) -> list[Registration]:
        rows = self.db.fetch_all(
            _SELECT + "WHERE g.status = %s ORDER BY g.registration_date LIMIT %s OFFSET %s",
            (status.value, limit, offset),
        )
        return [self.to_model(r) for r in rows]

    def search(
        self, *, status: RegistrationStatus | None = None, limit: int = 20, offset: int = 0
    ) -> list[Registration]:
        """One page for the admin review list: oldest request first so nobody waits longest.

        `status=None` means every status. `search` and `count_search` share
        `_status_filter` so the page and its total can never disagree.
        """
        where, params = self._status_filter(status)
        rows = self.db.fetch_all(
            _SELECT + where + " ORDER BY g.registration_date, g.id LIMIT %s OFFSET %s",
            (*params, limit, offset),
        )
        return [self.to_model(r) for r in rows]

    def count_search(self, *, status: RegistrationStatus | None = None) -> int:
        where, params = self._status_filter(status)
        row = self.db.fetch_one("SELECT COUNT(*) AS n FROM registrations g" + where, params)
        return int(row["n"]) if row else 0

    @staticmethod
    def _status_filter(status: RegistrationStatus | None) -> tuple[str, tuple[Any, ...]]:
        if status is None:
            return "", ()
        return " WHERE g.status = %s", (status.value,)

    def list_recent(self, limit: int = 10) -> list[Registration]:
        rows = self.db.fetch_all(
            _SELECT + "ORDER BY g.registration_date DESC, g.id DESC LIMIT %s", (limit,)
        )
        return [self.to_model(r) for r in rows]

    def count_slot_taking(self, activity_id: int, *, for_update: bool = False) -> int:
        """How many slots are used: PENDING + APPROVED (never stored on the activity).

        `for_update=True` makes it a locking read (LOCK IN SHARE MODE) for use inside a
        transaction that already holds the activity row lock: InnoDB then returns the
        latest committed count instead of the transaction's snapshot.
        """
        sql = (
            "SELECT COUNT(*) AS n FROM registrations "
            "WHERE activity_id = %s AND status IN ('PENDING', 'APPROVED')"
        )
        if for_update:
            sql += " LOCK IN SHARE MODE"
        row = self.db.fetch_one(sql, (activity_id,))
        return int(row["n"]) if row else 0

    def count_for_activity(
        self,
        activity_id: int,
        statuses: Iterable[RegistrationStatus],
        *,
        for_update: bool = False,
    ) -> int:
        """Rows of one activity in the given statuses (e.g. APPROVED only, for approval).

        Like `count_slot_taking`, `for_update=True` adds LOCK IN SHARE MODE so a caller
        holding the activity row lock reads the latest committed count.
        """
        values = [status.value for status in statuses]
        if not values:
            return 0
        placeholders = ", ".join(["%s"] * len(values))
        sql = (
            "SELECT COUNT(*) AS n FROM registrations WHERE activity_id = %s "
            "AND status IN (" + placeholders + ")"
        )
        if for_update:
            sql += " LOCK IN SHARE MODE"
        row = self.db.fetch_one(sql, (activity_id, *values))
        return int(row["n"]) if row else 0

    def count_by_status(self) -> dict[str, int]:
        rows = self.db.fetch_all("SELECT status, COUNT(*) AS n FROM registrations GROUP BY status")
        counts = {status.value: 0 for status in RegistrationStatus}
        for r in rows:
            counts[r["status"]] = int(r["n"])
        return counts

    def report_rows_for_user(self, user_id: int) -> list[dict[str, Any]]:
        """Raw rows for VolunteerActivityReport (title, date, times, status)."""
        return self.db.fetch_all(
            "SELECT a.title AS activity_title, a.activity_date, a.start_time, a.end_time, "
            "g.status FROM registrations g JOIN activities a ON a.id = g.activity_id "
            "WHERE g.user_id = %s ORDER BY a.activity_date DESC",
            (user_id,),
        )

    def report_rows(
        self, *, date_from: date | None = None, date_to: date | None = None
    ) -> list[dict[str, Any]]:
        """Raw rows for VolunteerHoursReport: one per registration with volunteer + activity."""
        sql = (
            "SELECT u.id AS user_id, u.username, "
            "CONCAT(u.first_name, ' ', u.last_name) AS volunteer_name, g.status, "
            "a.title AS activity_title, a.activity_date, a.start_time, a.end_time "
            "FROM registrations g JOIN users u ON u.id = g.user_id "
            "JOIN activities a ON a.id = g.activity_id WHERE 1 = 1"
        )
        params: list[Any] = []
        if date_from is not None:
            sql += " AND a.activity_date >= %s"
            params.append(date_from)
        if date_to is not None:
            sql += " AND a.activity_date <= %s"
            params.append(date_to)
        sql += " ORDER BY u.last_name, u.first_name, a.activity_date, g.id"
        return self.db.fetch_all(sql, tuple(params))

    # ---- writes ----
    def insert(self, registration: Registration) -> int:
        new_id = self.db.execute(
            "INSERT INTO registrations (activity_id, user_id, status) VALUES (%s, %s, %s)",
            (registration.activity_id, registration.user_id, registration.status.value),
        )
        registration.id = new_id
        return new_id

    def reopen(self, registration_id: int) -> bool:
        """Cancelled -> PENDING again, re-using the same row (brief, Section 3)."""
        affected = self.db.execute(
            "UPDATE registrations SET status = 'PENDING', registration_date = NOW(), "
            "reviewed_at = NULL, reviewed_by = NULL, remarks = NULL WHERE id = %s",
            (registration_id,),
        )
        return affected > 0

    def set_status(self, registration_id: int, status: RegistrationStatus) -> bool:
        affected = self.db.execute(
            "UPDATE registrations SET status = %s WHERE id = %s",
            (status.value, registration_id),
        )
        return affected > 0

    def review(
        self,
        registration_id: int,
        *,
        status: RegistrationStatus,
        reviewed_by: int,
        reviewed_at: datetime,
        remarks: str | None,
    ) -> bool:
        affected = self.db.execute(
            "UPDATE registrations SET status = %s, reviewed_by = %s, reviewed_at = %s, "
            "remarks = %s WHERE id = %s",
            (status.value, reviewed_by, reviewed_at, remarks, registration_id),
        )
        return affected > 0

    def list_user_ids_by_activity(
        self, activity_id: int, statuses: Iterable[RegistrationStatus]
    ) -> list[int]:
        """Ids of the volunteers registered for an activity in any of the given statuses.

        Used to notify everyone who still holds a slot when an activity is cancelled.
        The IN (...) list is built from one %s per status, so values stay parameters.
        """
        values = [status.value for status in statuses]
        if not values:
            return []
        placeholders = ", ".join(["%s"] * len(values))
        rows = self.db.fetch_all(
            "SELECT user_id FROM registrations WHERE activity_id = %s "
            "AND status IN (" + placeholders + ") ORDER BY user_id",
            (activity_id, *values),
        )
        return [int(r["user_id"]) for r in rows]
