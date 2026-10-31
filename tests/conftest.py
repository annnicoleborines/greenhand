"""Shared pytest fixtures.

Unit tests never touch a database (they use FakeDatabaseManager below).
Integration tests use the TEST_DB_NAME database. If MySQL is not reachable they
are skipped with a clear message, so `pytest` still passes on a machine without
XAMPP running. CI always runs them against a MySQL 8 service.

Each integration test ends with every table emptied, so tests never see each
other's data.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymysql
import pytest
from dotenv import load_dotenv
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.config import TestConfig
from app.database import DatabaseManager

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = ROOT / "database" / "schema.sql"
TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "greenhands_test")

ALL_TABLES = [
    "audit_logs",
    "notifications",
    "registrations",
    "activities",
    "locations",
    "volunteer_profiles",
    "users",
]


def _database_reachable() -> bool:
    try:
        conn = pymysql.connect(
            host=os.environ.get("DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ.get("DB_USER", "root"),
            password=os.environ.get("DB_PASSWORD", ""),
            connect_timeout=2,
        )
        conn.close()
        return True
    except pymysql.MySQLError:
        return False


DB_AVAILABLE = _database_reachable()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark tests under tests/integration and tests/e2e; skip both when MySQL is down."""
    skip = pytest.mark.skip(reason="MySQL not reachable (run ./scripts/mysql.ps1 to start it)")
    for item in items:
        path = str(item.path)
        if "integration" in path or "e2e" in path:
            item.add_marker(pytest.mark.integration if "integration" in path else pytest.mark.e2e)
            if not DB_AVAILABLE:
                item.add_marker(skip)


# --------------------------------------------------------------------------
# Fake database for unit tests (no MySQL needed)
# --------------------------------------------------------------------------
class FakeDatabaseManager:
    """Records every SQL call and returns canned rows.

    Lets DAO unit tests check that the right SQL and parameters are produced
    without a real database. It is duck-typed: DAOs only call these methods.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.rows: list[dict[str, Any]] = []
        self.next_id = 1
        self.fail_with: Exception | None = None

    def _record(self, sql: str, params: tuple[Any, ...]) -> None:
        assert "%s" in sql or not params, "values must be passed as %s parameters"
        self.calls.append((" ".join(sql.split()), params))
        if self.fail_with is not None:
            raise self.fail_with

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        self._record(sql, params)
        return self.rows[0] if self.rows else None

    def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        self._record(sql, params)
        return list(self.rows)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        self._record(sql, params)
        if sql.lstrip().upper().startswith("INSERT"):
            self.next_id += 1
            return self.next_id - 1
        return 1

    @property
    def last_sql(self) -> str:
        return self.calls[-1][0]

    @property
    def last_params(self) -> tuple[Any, ...]:
        return self.calls[-1][1]


@pytest.fixture
def fake_db() -> FakeDatabaseManager:
    return FakeDatabaseManager()


# --------------------------------------------------------------------------
# Real database for integration tests
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def db() -> Iterator[DatabaseManager]:
    """Point the singleton at the test database and rebuild it from schema.sql."""
    if not DB_AVAILABLE:
        pytest.skip("MySQL not reachable")
    sys.path.insert(0, str(ROOT / "scripts"))
    from init_db import import_schema  # the same code the README tells users to run

    raw = pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        charset="utf8mb4",
    )
    import_schema(raw, TEST_DB_NAME)
    raw.close()

    manager = DatabaseManager()
    manager.configure(database=TEST_DB_NAME)
    yield manager
    manager.close()
    manager.configure()  # back to .env settings


@pytest.fixture
def clean_db(db: DatabaseManager) -> Iterator[DatabaseManager]:
    """Empty every table after the test (roles are reference data and stay)."""
    yield db
    db.close()
    with db.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in ALL_TABLES:
            cur.execute("TRUNCATE TABLE " + table)  # table names are constants above
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")


@pytest.fixture
def app(clean_db: DatabaseManager) -> Iterator[Flask]:
    flask_app = create_app(TestConfig)
    with flask_app.app_context():
        yield flask_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()
