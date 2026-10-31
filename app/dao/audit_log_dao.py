from __future__ import annotations

from datetime import date
from typing import Any

from app.dao.base_dao import BaseDAO
from app.models import AuditLog


class AuditLogDAO(BaseDAO):
    """SQL for the audit_logs table (FR-6: every add/edit/delete is recorded)."""

    @staticmethod
    def to_model(row: dict[str, Any]) -> AuditLog:
        return AuditLog(
            id=row["id"],
            user_id=row["user_id"],
            action=row["action"],
            entity=row["entity"],
            record_reference=row["record_reference"],
            timestamp=row["timestamp"],
            details=row["details"],
            username=row.get("username"),
        )

    def insert(self, entry: AuditLog) -> int:
        new_id = self.db.execute(
            "INSERT INTO audit_logs (user_id, action, entity, record_reference, details) "
            "VALUES (%s, %s, %s, %s, %s)",
            (entry.user_id, entry.action, entry.entity, entry.record_reference, entry.details),
        )
        entry.id = new_id
        return new_id

    def search(
        self,
        *,
        user_id: int | None = None,
        action: str | None = None,
        username: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLog]:
        where, params = self._filters(
            user_id=user_id, action=action, username=username, date_from=date_from, date_to=date_to
        )
        sql = (
            "SELECT l.id, l.user_id, l.action, l.entity, l.record_reference, l.timestamp, "
            "l.details, u.username FROM audit_logs l JOIN users u ON u.id = l.user_id"
            + where
            + " ORDER BY l.timestamp DESC, l.id DESC LIMIT %s OFFSET %s"
        )
        return [self.to_model(r) for r in self.db.fetch_all(sql, (*params, limit, offset))]

    def count_search(
        self,
        *,
        user_id: int | None = None,
        action: str | None = None,
        username: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> int:
        """Total for the same filters as `search`, so the pagination maths is right."""
        where, params = self._filters(
            user_id=user_id, action=action, username=username, date_from=date_from, date_to=date_to
        )
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM audit_logs l JOIN users u ON u.id = l.user_id" + where,
            params,
        )
        return int(row["n"]) if row else 0

    @staticmethod
    def _filters(
        *,
        user_id: int | None,
        action: str | None,
        username: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> tuple[str, tuple[Any, ...]]:
        """The WHERE clause shared by `search` and `count_search` (only given filters)."""
        sql = " WHERE 1 = 1"
        params: list[Any] = []
        if user_id is not None:
            sql += " AND l.user_id = %s"
            params.append(user_id)
        if action:
            sql += " AND l.action = %s"
            params.append(action)
        if username:
            sql += " AND u.username LIKE %s"  # the wildcard stays in the value
            params.append(f"%{username}%")
        if date_from is not None:
            sql += " AND l.timestamp >= %s"
            params.append(date_from)
        if date_to is not None:
            sql += " AND l.timestamp < DATE_ADD(%s, INTERVAL 1 DAY)"
            params.append(date_to)
        return sql, tuple(params)

    def list_actions(self) -> list[str]:
        """Every distinct action code, alphabetically, for the viewer's filter."""
        rows = self.db.fetch_all("SELECT DISTINCT action FROM audit_logs ORDER BY action")
        return [str(r["action"]) for r in rows]

    def count_all(self) -> int:
        row = self.db.fetch_one("SELECT COUNT(*) AS n FROM audit_logs")
        return int(row["n"]) if row else 0
