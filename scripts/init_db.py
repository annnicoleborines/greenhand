"""Create the databases and import database/schema.sql (Python alternative to phpMyAdmin).

Usage:
    python scripts/init_db.py             # create DB_NAME + TEST_DB_NAME, import schema in both
    python scripts/init_db.py --only-test

WARNING: schema.sql drops and recreates every table, so existing data is lost.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

load_dotenv()

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "database" / "schema.sql"


def split_statements(sql_text: str) -> list[str]:
    """Split a .sql file into statements. Comment lines are dropped first."""
    lines = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    statements = [s.strip() for s in "\n".join(lines).split(";")]
    return [s for s in statements if s]


def import_schema(connection: pymysql.connections.Connection, database: str) -> None:
    with connection.cursor() as cur:
        # Identifiers cannot be bound as %s parameters; the name comes from .env, not a user.
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        cur.execute(f"USE `{database}`")
        for statement in split_statements(SCHEMA_FILE.read_text(encoding="utf-8")):
            cur.execute(statement)
    connection.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only-test", action="store_true", help="only (re)create the test DB")
    args = parser.parse_args()

    names = [os.environ.get("TEST_DB_NAME", "greenhands_test")]
    if not args.only_test:
        names.insert(0, os.environ.get("DB_NAME", "greenhands"))

    connection = pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        charset="utf8mb4",
    )
    try:
        for name in names:
            import_schema(connection, name)
            print(f"schema imported into: {name}")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
