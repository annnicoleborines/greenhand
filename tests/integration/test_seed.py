"""The demo seed must give every screen something to show, and running it twice must
not duplicate anything (the defense machine will run it more than once)."""

from __future__ import annotations

import os

import pytest
from flask.testing import FlaskClient

import seed
from app.database import DatabaseManager
from tests.integration.test_auth_flow import count, log_in


@pytest.fixture
def demo_passwords(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SEED_ADMIN_PASSWORD", "Admin2026!")
    monkeypatch.setitem(os.environ, "SEED_VOLUNTEER_PASSWORD", "Plant2026!")


def totals(db: DatabaseManager) -> dict[str, int]:
    return {
        table: count(db, f"SELECT COUNT(*) AS n FROM {table}")  # noqa: S608  (constant names)
        for table in (
            "users",
            "locations",
            "activities",
            "registrations",
            "notifications",
            "audit_logs",
        )
    }


def test_seed_fills_every_table_and_is_idempotent(
    client: FlaskClient, clean_db: DatabaseManager, demo_passwords: None
) -> None:
    seed.run(big=False)
    first = totals(clean_db)
    assert first["users"] == 5 and first["locations"] == 3 and first["activities"] == 6
    assert first["registrations"] == 10
    by_status = {
        row["status"]: int(row["n"])
        for row in clean_db.fetch_all(
            "SELECT status, COUNT(*) AS n FROM registrations GROUP BY status"
        )
    }
    assert by_status == {"APPROVED": 3, "PENDING": 3, "COMPLETED": 2, "REJECTED": 1, "CANCELLED": 1}
    # Admin was told about every sign-up and the cancellation; reviewed volunteers were told too.
    # 10 submitted + 1 cancelled to the admin; 6 review results to volunteers
    # (3 approved, 2 completed which were approved first, 1 rejected).
    assert first["notifications"] == 10 + 1 + 6
    # Every activity creation, every registration, every review and the cancellation are audited.
    assert first["audit_logs"] == 6 + 10 + 6 + 1  # created, registered, reviewed, cancelled
    assert (
        count(clean_db, "SELECT COUNT(*) AS n FROM registrations WHERE reviewed_by IS NOT NULL")
        == 6
    )
    assert (
        count(
            clean_db,
            "SELECT COUNT(*) AS n FROM registrations WHERE remarks = %s",
            ("Age requirement not met.",),
        )
        == 1
    )

    seed.run(big=False)
    assert totals(clean_db) == first  # nothing duplicated

    # The demo accounts can log in with the seeded passwords.
    assert log_in(client, "admin", "Admin2026!").status_code == 302
    client.post("/logout")
    assert log_in(client, "maria", "Plant2026!").status_code == 302
    page = client.get("/registrations").get_data(as_text=True)
    assert "Riverbank Reforestation Drive" in page and "Trail Restoration Weekend" in page
