"""Unit tests for the DatabaseManager singleton and its error translation. No MySQL."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pymysql
import pytest

from app.database.db_manager import DatabaseManager, translate_error
from app.errors import ConflictError, DatabaseError, ValidationError


def test_singleton_returns_the_same_instance() -> None:
    assert DatabaseManager() is DatabaseManager()


def test_configure_overrides_only_what_is_passed() -> None:
    manager = DatabaseManager()
    original = manager.database_name
    manager.configure(database="other_db")
    assert manager.database_name == "other_db"
    manager.configure()
    assert manager.database_name == original


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (pymysql.err.IntegrityError(1062, "Duplicate entry"), ConflictError),
        (pymysql.err.IntegrityError(1452, "FK fails"), ConflictError),
        (pymysql.err.OperationalError(4025, "CONSTRAINT failed"), ValidationError),
        (pymysql.err.OperationalError(3819, "Check constraint violated"), ValidationError),
        (pymysql.err.OperationalError(2003, "Can't connect"), DatabaseError),
        (pymysql.err.OperationalError(2006, "MySQL server has gone away"), DatabaseError),
        (pymysql.err.ProgrammingError(1146, "Table doesn't exist"), DatabaseError),
    ],
)
def test_translate_error_maps_mysql_codes(exc: pymysql.MySQLError, expected: type) -> None:
    translated = translate_error(exc)
    assert isinstance(translated, expected)
    assert "Duplicate entry" not in translated.message  # raw SQL text never reaches users


def test_connection_failure_becomes_database_error() -> None:
    manager = DatabaseManager()
    manager.close()
    with (
        patch("app.database.db_manager.pymysql.connect") as connect,
        pytest.raises(DatabaseError) as exc,
    ):
        connect.side_effect = pymysql.err.OperationalError(2003, "Can't connect")
        manager.connection()
    assert "XAMPP" in exc.value.message


def _fake_connection() -> MagicMock:
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = {"ok": 1}
    cursor.lastrowid = 0
    cursor.rowcount = 1
    conn.cursor.return_value = cursor
    return conn


def test_transaction_commits_on_success_and_rolls_back_on_error() -> None:
    manager = DatabaseManager()
    manager.close()
    conn = _fake_connection()
    with patch("app.database.db_manager.pymysql.connect", return_value=conn):
        with manager.transaction() as cur:
            cur.execute("UPDATE x SET y = %s", (1,))
        conn.begin.assert_called_once()
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

        conn.reset_mock()
        with pytest.raises(ConflictError), manager.transaction():
            raise pymysql.err.IntegrityError(1062, "Duplicate")
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
    manager.close()


def test_statements_inside_transaction_share_the_cursor() -> None:
    manager = DatabaseManager()
    manager.close()
    conn = _fake_connection()
    with patch("app.database.db_manager.pymysql.connect", return_value=conn):
        with manager.transaction() as tx_cursor:
            manager.execute("UPDATE x SET y = %s", (1,))
            manager.fetch_one("SELECT 1")
        del tx_cursor
        calls: list[Any] = conn.cursor.return_value.execute.call_args_list
        assert len(calls) == 2  # both ran on the transaction's cursor
    manager.close()
