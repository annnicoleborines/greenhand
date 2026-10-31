"""Browser test for reports and audit logs (FR-6, FR-7) with Playwright + Chromium.

Through a real server: an admin opens Reports from the sidebar, opens the Activity
Participation report, filters it by status, sees the CSV download start, and then
checks the Audit Logs page for their own login entry.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from app.dao import AuditLogDAO
from app.database import DatabaseManager
from app.models import ActivityStatus, AuditLog, RegistrationStatus
from tests.integration.test_auth_flow import ADMIN_PASSWORD, make_admin
from tests.integration.test_browse_flow import (
    make_activity,
    make_location,
    make_volunteer,
    register,
)

pytestmark = pytest.mark.e2e


@pytest.fixture
def seeded(clean_db: DatabaseManager) -> None:
    admin = make_admin(clean_db)
    park = make_location(clean_db)
    riverbank = make_activity(
        clean_db, admin, park, "Riverbank Drive", in_days=7, max_volunteers=10
    )
    make_activity(
        clean_db, admin, park, "Hillside Drive", in_days=-30, status=ActivityStatus.COMPLETED
    )
    register(clean_db, riverbank, make_volunteer(clean_db, "vicky"), RegistrationStatus.APPROVED)
    AuditLogDAO(clean_db).insert(
        AuditLog(
            user_id=admin.id or 0,
            action="ACTIVITY_CREATED",
            entity="activity",
            record_reference=riverbank.id,
            details="Created activity Riverbank Drive.",
        )
    )
    clean_db.close()  # the server threads open their own connections


def test_admin_filters_a_report_downloads_csv_and_reads_the_audit_log(
    page: Page, live_server: str, seeded: None
) -> None:
    page.goto(f"{live_server}/login")
    page.get_by_label("Username").fill("admin1")
    page.get_by_label("Password").fill(ADMIN_PASSWORD)
    page.get_by_role("button", name="Login").click()
    expect(page).to_have_url(f"{live_server}/admin/dashboard")

    # ---- Reports index -> Activity Participation
    page.get_by_role("link", name="Reports", exact=True).click()
    expect(page).to_have_url(f"{live_server}/admin/reports/")
    page.locator("article", has_text="Activity Participation").get_by_role(
        "link", name=re.compile("^Open report")
    ).click()
    expect(page.get_by_role("heading", name="Activity Participation")).to_be_visible()
    expect(page.get_by_role("cell", name="Riverbank Drive")).to_be_visible()
    expect(page.get_by_role("cell", name="Hillside Drive")).to_be_visible()

    # ---- filter by status
    page.get_by_label("Activity status").select_option("OPEN")
    page.get_by_role("button", name="Apply").click()
    expect(page).to_have_url(re.compile(r"status=OPEN"))
    expect(page.get_by_role("cell", name="Riverbank Drive")).to_be_visible()
    expect(page.get_by_role("cell", name="Hillside Drive")).to_have_count(0)

    # ---- the CSV download carries the filter
    with page.expect_download() as download_info:
        page.get_by_role("link", name="Download CSV").click()
    download = download_info.value
    assert download.suggested_filename.startswith("activities-")
    assert download.suggested_filename.endswith(".csv")

    # ---- Audit Logs shows the seeded entry, and the action filter narrows to it
    page.get_by_role("link", name="Audit Logs", exact=True).click()
    expect(page).to_have_url(f"{live_server}/admin/audit-logs/")
    expect(page.get_by_role("cell", name=re.compile("^admin1"))).to_be_visible()
    expect(page.locator("code", has_text="ACTIVITY_CREATED")).to_be_visible()
    expect(page.get_by_text("Created activity Riverbank Drive.")).to_be_visible()
    page.get_by_label("Action").select_option("ACTIVITY_CREATED")
    page.get_by_role("button", name="Apply").click()
    expect(page.get_by_role("heading", name="1 entry matching the filters")).to_be_visible()
