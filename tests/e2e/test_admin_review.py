"""Browser test for the admin review page (FR-3) with Playwright + Chromium.

Through a real server with CSRF enabled: an admin opens Registrations from the
sidebar, approves one pending request (confirm() is accepted), and rejects
another with remarks typed into the row form.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from app.dao import RegistrationDAO
from app.database import DatabaseManager
from app.models import ActivityStatus, RegistrationStatus
from tests.integration.test_auth_flow import ADMIN_PASSWORD, make_admin
from tests.integration.test_browse_flow import (
    make_activity,
    make_location,
    make_volunteer,
    register,
)

pytestmark = pytest.mark.e2e


@pytest.fixture
def two_pending(clean_db: DatabaseManager) -> None:
    """An admin, one activity and two pending volunteers (the live server seeds a third user)."""
    admin = make_admin(clean_db)
    activity = make_activity(
        clean_db, admin, make_location(clean_db), "Mangrove Planting", status=ActivityStatus.OPEN
    )
    for name in ("alice", "bob"):
        register(clean_db, activity, make_volunteer(clean_db, name), RegistrationStatus.PENDING)
    assert RegistrationDAO(clean_db).count_search(status=RegistrationStatus.PENDING) == 2
    clean_db.close()  # the server threads open their own connections


def test_admin_approves_one_request_and_rejects_another(
    page: Page, live_server: str, two_pending: None
) -> None:
    page.on("dialog", lambda dialog: dialog.accept())  # answers the Approve confirm() with OK

    page.goto(f"{live_server}/login")
    page.get_by_label("Username").fill("admin1")
    page.get_by_label("Password").fill(ADMIN_PASSWORD)
    page.get_by_role("button", name="Login").click()
    expect(page).to_have_url(f"{live_server}/admin/dashboard")
    expect(page.get_by_text("Pending Registrations")).to_be_visible()

    page.get_by_role("link", name="Registrations", exact=True).click()
    expect(page).to_have_url(re.compile(r"/admin/registrations/"))
    expect(page.get_by_role("heading", name="2 pending registrations")).to_be_visible()

    # ---- approve Alice
    alice = page.get_by_role("row", name=re.compile("Vol Alice"))
    alice.get_by_role("button", name=re.compile("^Approve")).click()
    expect(page.get_by_text("Approved Vol Alice for Mangrove Planting.")).to_be_visible()
    expect(page.get_by_role("heading", name="1 pending registration")).to_be_visible()

    # ---- reject Bob with remarks
    bob = page.get_by_role("row", name=re.compile("Vol Bob"))
    bob.get_by_label(re.compile("Remarks for rejecting")).fill("Age limit is 18.")
    bob.get_by_role("button", name=re.compile("^Reject")).click()
    expect(page.get_by_text("Rejected Vol Bob for Mangrove Planting.")).to_be_visible()
    expect(page.get_by_text("No pending registrations.")).to_be_visible()

    # ---- the rejected row keeps the remarks under its badge
    page.get_by_label("Filter by status").select_option("REJECTED")
    page.get_by_role("button", name="Filter").click()
    bob = page.get_by_role("row", name=re.compile("Vol Bob"))
    expect(bob.locator("span.badge-red", has_text="Rejected")).to_be_visible()
    expect(bob.get_by_text("Age limit is 18.")).to_be_visible()
