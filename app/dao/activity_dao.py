"""ActivityDAO: SQL for the activities table.

Available slots are never stored. Every SELECT here computes `taken_slots`
with a correlated COUNT of PENDING + APPROVED registrations.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.dao.base_dao import BaseDAO
from app.models import Activity, ActivityStatus

# Shared SELECT so every method maps rows the same way.
_SELECT = """
SELECT a.id, a.created_by, a.location_id, a.title, a.description, a.activity_date,
       a.start_time, a.end_time, a.max_volunteers, a.requirements, a.status,
       a.created_at, a.updated_at,
       l.location_name,
       (SELECT COUNT(*) FROM registrations r
         WHERE r.activity_id = a.id AND r.status IN ('PENDING', 'APPROVED')) AS taken_slots
FROM activities a
JOIN locations l ON l.id = a.location_id
"""


class ActivityDAO(BaseDAO):
    def to_model(self, row: dict[str, Any]) -> Activity:
        return Activity(
            id=row["id"],
            created_by=row["created_by"],
            location_id=row["location_id"],
            title=row["title"],
            description=row["description"],
            activity_date=self.to_date(row["activity_date"]),
            start_time=self.to_time(row["start_time"]),
            end_time=self.to_time(row["end_time"]),
            max_volunteers=row["max_volunteers"],
            requirements=row["requirements"],
            status=ActivityStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            taken_slots=int(row.get("taken_slots") or 0),
            location_name=row.get("location_name"),
        )

    # ---- reads ----
    def find_by_id(self, activity_id: int) -> Activity | None:
        row = self.db.fetch_one(_SELECT + "WHERE a.id = %s", (activity_id,))
        return self.to_model(row) if row else None

    def find_by_title(self, title: str) -> Activity | None:
        row = self.db.fetch_one(_SELECT + "WHERE a.title = %s", (title,))
        return self.to_model(row) if row else None

    def lock_for_update(self, activity_id: int) -> Activity | None:
        """Row-lock the activity inside the caller's transaction (SELECT ... FOR UPDATE).

        Must be called inside `DatabaseManager().transaction()`; the lock is released
        when that transaction commits or rolls back.
        """
        row = self.db.fetch_one(_SELECT + "WHERE a.id = %s FOR UPDATE", (activity_id,))
        return self.to_model(row) if row else None

    def search(
        self,
        *,
        keyword: str | None = None,
        location_id: int | None = None,
        activity_date: date | None = None,
        date_from: date | None = None,
        status: ActivityStatus | None = ActivityStatus.OPEN,
        limit: int = 12,
        offset: int = 0,
    ) -> list[Activity]:
        """Filtered list for the browse page. Filters are optional; only set ones apply.

        `date_from` hides activities before that day (the browse page passes today,
        so past activities never show even when they are still OPEN). Rows are
        ordered soonest first; `a.id` is a tie-break so pagination is stable.
        """
        params: list[Any] = []
        sql = (
            _SELECT
            + "WHERE 1 = 1"
            + self._search_filters(params, keyword, location_id, activity_date, date_from, status)
        )
        sql += " ORDER BY a.activity_date, a.start_time, a.id LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        return [self.to_model(r) for r in self.db.fetch_all(sql, tuple(params))]

    def count_search(
        self,
        *,
        keyword: str | None = None,
        location_id: int | None = None,
        activity_date: date | None = None,
        date_from: date | None = None,
        status: ActivityStatus | None = ActivityStatus.OPEN,
    ) -> int:
        """How many rows `search` would return with the same filters (for page counts)."""
        params: list[Any] = []
        sql = "SELECT COUNT(*) AS n FROM activities a WHERE 1 = 1" + self._search_filters(
            params, keyword, location_id, activity_date, date_from, status
        )
        row = self.db.fetch_one(sql, tuple(params))
        return int(row["n"]) if row else 0

    @staticmethod
    def _search_filters(
        params: list[Any],
        keyword: str | None,
        location_id: int | None,
        activity_date: date | None,
        date_from: date | None,
        status: ActivityStatus | None,
    ) -> str:
        """Build the shared WHERE clauses for search/count_search.

        Returns the SQL text to append and fills `params` in the same order, so
        the two queries can never drift apart. Every value stays a %s parameter;
        the LIKE wildcard is part of the VALUE, not the SQL text.
        """
        sql = ""
        if status is not None:
            sql += " AND a.status = %s"
            params.append(status.value)
        if location_id is not None:
            sql += " AND a.location_id = %s"
            params.append(location_id)
        if activity_date is not None:
            sql += " AND a.activity_date = %s"
            params.append(activity_date)
        if date_from is not None:
            sql += " AND a.activity_date >= %s"
            params.append(date_from)
        if keyword:
            sql += " AND (a.title LIKE %s OR a.description LIKE %s)"
            like = "%" + keyword + "%"
            params.extend([like, like])
        return sql

    def list_upcoming_open(self, limit: int = 3, today: date | None = None) -> list[Activity]:
        """The next few OPEN activities on or after `today`, soonest first (dashboard widget)."""
        rows = self.db.fetch_all(
            _SELECT + "WHERE a.status = %s AND a.activity_date >= %s "
            "ORDER BY a.activity_date, a.start_time, a.id LIMIT %s",
            (ActivityStatus.OPEN.value, today or date.today(), limit),
        )
        return [self.to_model(r) for r in rows]

    def list_all(self, *, limit: int = 50, offset: int = 0) -> list[Activity]:
        rows = self.db.fetch_all(
            _SELECT + "ORDER BY a.activity_date DESC, a.id DESC LIMIT %s OFFSET %s",
            (limit, offset),
        )
        return [self.to_model(r) for r in rows]

    def count_all(self) -> int:
        row = self.db.fetch_one("SELECT COUNT(*) AS n FROM activities")
        return int(row["n"]) if row else 0

    def count_by_status(self) -> dict[str, int]:
        rows = self.db.fetch_all("SELECT status, COUNT(*) AS n FROM activities GROUP BY status")
        counts = {status.value: 0 for status in ActivityStatus}
        for r in rows:
            counts[r["status"]] = int(r["n"])
        return counts

    def registration_count(self, activity_id: int) -> int:
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM registrations WHERE activity_id = %s", (activity_id,)
        )
        return int(row["n"]) if row else 0

    def report_rows(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        status: ActivityStatus | None = None,
    ) -> list[dict[str, Any]]:
        """Raw rows for ActivityParticipationReport: one per activity with slot counts.

        The counts come from one LEFT JOIN + conditional SUM, so an activity nobody
        registered for still appears with zeros. Filters are optional and only added
        when given (values stay %s parameters).
        """
        sql = (
            "SELECT a.id, a.title, a.activity_date, a.start_time, a.end_time, a.status, "
            "a.max_volunteers, l.location_name, "
            "COALESCE(SUM(r.status = 'PENDING'), 0) AS pending, "
            "COALESCE(SUM(r.status = 'APPROVED'), 0) AS approved, "
            "COALESCE(SUM(r.status = 'COMPLETED'), 0) AS completed "
            "FROM activities a JOIN locations l ON l.id = a.location_id "
            "LEFT JOIN registrations r ON r.activity_id = a.id WHERE 1 = 1"
        )
        params: list[Any] = []
        if date_from is not None:
            sql += " AND a.activity_date >= %s"
            params.append(date_from)
        if date_to is not None:
            sql += " AND a.activity_date <= %s"
            params.append(date_to)
        if status is not None:
            sql += " AND a.status = %s"
            params.append(status.value)
        sql += (
            " GROUP BY a.id, a.title, a.activity_date, a.start_time, a.end_time, a.status, "
            "a.max_volunteers, l.location_name ORDER BY a.activity_date, a.start_time, a.id"
        )
        return self.db.fetch_all(sql, tuple(params))

    # ---- writes ----
    def insert(self, activity: Activity) -> int:
        new_id = self.db.execute(
            "INSERT INTO activities (created_by, location_id, title, description, "
            "activity_date, start_time, end_time, max_volunteers, requirements, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                activity.created_by,
                activity.location_id,
                activity.title,
                activity.description,
                activity.activity_date,
                activity.start_time,
                activity.end_time,
                activity.max_volunteers,
                activity.requirements,
                activity.status.value,
            ),
        )
        activity.id = new_id
        return new_id

    def update(self, activity: Activity) -> bool:
        affected = self.db.execute(
            "UPDATE activities SET location_id = %s, title = %s, description = %s, "
            "activity_date = %s, start_time = %s, end_time = %s, max_volunteers = %s, "
            "requirements = %s, status = %s WHERE id = %s",
            (
                activity.location_id,
                activity.title,
                activity.description,
                activity.activity_date,
                activity.start_time,
                activity.end_time,
                activity.max_volunteers,
                activity.requirements,
                activity.status.value,
                activity.id,
            ),
        )
        return affected > 0

    def set_status(self, activity_id: int, status: ActivityStatus) -> bool:
        affected = self.db.execute(
            "UPDATE activities SET status = %s WHERE id = %s", (status.value, activity_id)
        )
        return affected > 0

    def delete(self, activity_id: int) -> bool:
        affected = self.db.execute("DELETE FROM activities WHERE id = %s", (activity_id,))
        return affected > 0
