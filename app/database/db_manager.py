"""DatabaseManager: the one object that talks to MySQL (Singleton pattern).

Why a Singleton?
    The whole app shares a single set of connection settings and a single place
    that knows how to connect, reconnect and run transactions. `DatabaseManager()`
    always returns the same instance, so every DAO uses the same configuration.

Thread note:
    Flask's dev server handles requests in threads, and a PyMySQL connection must
    not be shared between threads. So the single manager keeps ONE connection PER
    THREAD (threading.local). There is still only one manager object.

Transactions:
    with DatabaseManager().transaction() as cursor:
        cursor.execute("...", params)      # everything here commits together
    Inside the block every DAO call on this thread joins the same transaction.
    Outside a block each statement auto-commits on its own.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, ClassVar

import pymysql
import pymysql.cursors
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from app.errors import AppError, ConflictError, DatabaseError, ValidationError

log = logging.getLogger(__name__)

# MySQL / MariaDB error numbers we translate into typed application errors.
DUPLICATE_KEY = 1062
FOREIGN_KEY_FAILS = {1451, 1452}
CHECK_VIOLATION = {3819, 4025}  # 3819 = MySQL 8, 4025 = MariaDB
CONNECTION_LOST = {2002, 2003, 2006, 2013}


def translate_error(exc: pymysql.MySQLError) -> AppError:
    """Map a raw PyMySQL error to one of our typed errors (never leaks SQL to users)."""
    code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
    if code == DUPLICATE_KEY:
        return ConflictError("That record already exists (duplicate entry).")
    if code in FOREIGN_KEY_FAILS:
        return ConflictError("This record is linked to other records and cannot be changed.")
    if code in CHECK_VIOLATION:
        return ValidationError("A database rule was violated (check the time range and capacity).")
    if code in CONNECTION_LOST or isinstance(exc, pymysql.err.OperationalError):
        return DatabaseError()
    return DatabaseError("The database returned an unexpected error.")


class DatabaseManager:
    """Singleton wrapper around PyMySQL."""

    _instance: ClassVar[DatabaseManager | None] = None
    _initialised: bool
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __new__(cls) -> DatabaseManager:
        # Double-checked locking: create the instance only once, even with threads.
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialised = False
                    cls._instance = instance
        return cls._instance

    def __init__(self) -> None:
        if self._initialised:
            return
        self._initialised = True
        self._local = threading.local()
        self.configure()

    # ------------------------------------------------------------------ setup
    def configure(self, **overrides: Any) -> None:
        """Read connection settings from .env (tests override `database`)."""
        self._settings: dict[str, Any] = {
            "host": os.environ.get("DB_HOST", "127.0.0.1"),
            "port": int(os.environ.get("DB_PORT", "3306")),
            "user": os.environ.get("DB_USER", "root"),
            "password": os.environ.get("DB_PASSWORD", ""),
            "database": os.environ.get("DB_NAME", "greenhands"),
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
            "autocommit": True,
            "connect_timeout": 5,
        }
        self._settings.update(overrides)
        self.close()

    @property
    def database_name(self) -> str:
        return str(self._settings["database"])

    # ------------------------------------------------------------- connection
    def connection(self) -> Connection[DictCursor]:
        """Return this thread's connection, opening or re-opening it when needed."""
        conn: Connection[DictCursor] | None = getattr(self._local, "conn", None)
        try:
            if conn is None:
                conn = pymysql.connect(**self._settings)
                self._local.conn = conn
            else:
                try:
                    conn.ping(reconnect=False)
                except pymysql.MySQLError:
                    # MySQL dropped the connection (restart, timeout): open a fresh one.
                    log.warning("database connection lost, reconnecting", extra={"action": "db_reconnect"})
                    conn = pymysql.connect(**self._settings)
                    self._local.conn = conn
        except pymysql.MySQLError as exc:
            log.error("database connection failed", extra={"action": "db_connect"})
            self._local.conn = None
            raise translate_error(exc) from exc
        return conn

    def close(self) -> None:
        """Close this thread's connection (called at app teardown and in tests)."""
        local = getattr(self, "_local", None)
        conn = getattr(local, "conn", None) if local else None
        if conn is not None:
            try:
                conn.close()
            except pymysql.MySQLError:
                pass
            self._local.conn = None

    # ----------------------------------------------------------- transactions
    @property
    def _active_cursor(self) -> DictCursor | None:
        return getattr(self._local, "tx_cursor", None)

    @contextmanager
    def transaction(self) -> Iterator[DictCursor]:
        """Run several statements as one unit: commit at the end, roll back on error."""
        if self._active_cursor is not None:  # nested call joins the outer transaction
            yield self._active_cursor
            return
        conn = self.connection()
        cursor = conn.cursor()
        self._local.tx_cursor = cursor
        try:
            conn.begin()
            yield cursor
            conn.commit()
        except pymysql.MySQLError as exc:
            conn.rollback()
            raise translate_error(exc) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            self._local.tx_cursor = None
            cursor.close()

    # -------------------------------------------------------------- execution
    @contextmanager
    def cursor(self) -> Iterator[DictCursor]:
        """A cursor that joins the open transaction, or auto-commits on its own."""
        active = self._active_cursor
        if active is not None:
            yield active
            return
        cur = self.connection().cursor()
        try:
            yield cur
        except pymysql.MySQLError as exc:
            raise translate_error(exc) from exc
        finally:
            cur.close()

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Run INSERT/UPDATE/DELETE. Returns lastrowid for INSERT, else affected rows."""
        with self.cursor() as cur:
            cur.execute(sql, params)
            return int(cur.lastrowid) if cur.lastrowid else int(cur.rowcount)

    def ping(self) -> bool:
        """Health check: True when SELECT 1 works."""
        return self.fetch_one("SELECT 1 AS ok") is not None
