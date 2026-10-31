"""Add columns that newer code needs to an EXISTING database, without losing data.

`scripts/init_db.py` drops and recreates every table, which is fine for a fresh
install but wipes real data. After pulling new code, run this instead:

    python scripts/upgrade_db.py

It looks at information_schema for each (table, column) in UPGRADES and adds the
column only when it is missing, so running it twice is harmless (idempotent).
It upgrades both DB_NAME and TEST_DB_NAME from .env and prints what it did.
"""

from __future__ import annotations

import os
import sys

import pymysql
from dotenv import load_dotenv

load_dotenv()

# (table, column, DDL to add it). Keep this list in sync with database/schema.sql.
UPGRADES: list[tuple[str, str, str]] = [
    (
        "users",
        "photo_path",
        "ALTER TABLE `users` ADD COLUMN `photo_path` VARCHAR(255) NULL AFTER `phone`",
    ),
]


def column_exists(
    connection: pymysql.connections.Connection, database: str, table: str, column: str
) -> bool:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
            (database, table, column),
        )
        return cur.fetchone() is not None


def upgrade_database(connection: pymysql.connections.Connection, database: str) -> list[str]:
    """Apply every missing upgrade to one database; return the columns that were added."""
    added: list[str] = []
    with connection.cursor() as cur:
        # Identifiers cannot be bound as %s parameters; the name comes from .env, not a user.
        cur.execute(f"USE `{database}`")
        for table, column, ddl in UPGRADES:
            if column_exists(connection, database, table, column):
                continue
            cur.execute(ddl)
            added.append(f"{table}.{column}")
    connection.commit()
    return added


def main() -> int:
    names = [
        os.environ.get("DB_NAME", "greenhands"),
        os.environ.get("TEST_DB_NAME", "greenhands_test"),
    ]
    connection = pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        charset="utf8mb4",
    )
    try:
        for name in names:
            added = upgrade_database(connection, name)
            if added:
                print(f"{name}: added {', '.join(added)}")
            else:
                print(f"{name}: already up to date")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
