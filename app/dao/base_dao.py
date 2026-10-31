"""BaseDAO: shared plumbing for every Data Access Object (DAO pattern).

Rules (checked at code review):
- ALL SQL lives in app/dao/. Controllers, services and templates never run SQL.
- Every statement uses %s placeholders; values are passed as a tuple.
  No f-strings, +, % or .format() with values. Ever.
- DAOs return model objects (app/models), not raw rows.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from app.database.db_manager import DatabaseManager


class BaseDAO:
    def __init__(self, db: DatabaseManager | None = None) -> None:
        self.db = db or DatabaseManager()

    # ---- value converters for PyMySQL quirks ----
    @staticmethod
    def to_time(value: Any) -> time:
        """PyMySQL returns TIME columns as timedelta; models want datetime.time."""
        if isinstance(value, time):
            return value
        if isinstance(value, timedelta):
            total = int(value.total_seconds())
            return time(total // 3600, (total % 3600) // 60, total % 60)
        if isinstance(value, str):
            return time.fromisoformat(value)
        msg = f"Cannot convert {value!r} to time"
        raise TypeError(msg)

    @staticmethod
    def to_bool(value: Any) -> bool:
        return bool(value)

    @staticmethod
    def to_date(value: Any) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))
