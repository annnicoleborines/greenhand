"""Browser test for the admin management pages (FR-3) with Playwright + Chromium.

Goes through a real server with CSRF enabled: an admin logs in, adds a location
and an activity through the forms, sees the activity in the list and changes
its status through the row form (which asks for confirmation with confirm()).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from playwright.sync_api import Page, expect

from app.database import DatabaseManager
from tests.integration.test_auth_flow import ADMIN_PASSWORD, make_admin

pytestmark = pytest.mark.e2e

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture
def admin_account(clean_db: DatabaseManager) -> None:
    """The shared live_server seeds a volunteer; this test also needs an admin."""
    make_admin(clean_db)
    clean_db.close()  # the server threads open their own connections


def test_admin_creates_a_location_and_an_activity(
    page: Page, live_server: str, admin_account: None
) -> None:
    page.on("dialog", lambda dialog: dialog.accept())  # answers every confirm() with OK

    page.goto(f"{live_server}/login")
    page.get_by_label("Username").fill("admin1")
    page.get_by_label("Password").fill(ADMIN_PASSWORD)
    page.get_by_role("button", name="Login").click()
    expect(page).to_have_url(f"{live_server}/admin/dashboard")

    # ---- location
    page.get_by_role("link", name="Manage Locations").click()
    expect(page).to_have_url(f"{live_server}/admin/locations/")
    page.get_by_role("link", name="New Location").first.click()
    expect(page.get_by_role("heading", name="New Location")).to_be_visible()
    page.get_by_label("Location name").fill("Riverside Park")
    page.get_by_label("Address").fill("1 River Road")
    page.get_by_role("button", name="Add location").click()
    expect(page).to_have_url(f"{live_server}/admin/locations/")
    expect(page.get_by_text("Location Riverside Park has been added.")).to_be_visible()
    expect(page.get_by_role("cell", name="Riverside Park")).to_be_visible()

    # ---- activity
    page.get_by_role("link", name="Manage Activities").click()
    expect(page).to_have_url(f"{live_server}/admin/activities/")
    page.get_by_role("link", name="New Activity").first.click()
    expect(page.get_by_role("heading", name="New Activity")).to_be_visible()
    page.get_by_label("Title").fill("Mangrove Planting")
    page.get_by_label("Location").select_option(label="Riverside Park")
    page.get_by_label("Date").fill(TOMORROW)
    page.get_by_label("Start time").fill("08:00")
    page.get_by_label("End time").fill("11:00")
    page.get_by_label("Maximum volunteers").fill("20")
    page.get_by_role("button", name="Create activity").click()

    expect(page).to_have_url(f"{live_server}/admin/activities/")
    expect(page.get_by_text("Activity Mangrove Planting has been created.")).to_be_visible()
    row = page.get_by_role("row", name=re.compile("Mangrove Planting"))
    expect(row.get_by_role("cell", name="Riverside Park")).to_be_visible()
    expect(row.locator("span.badge-green", has_text="Open")).to_be_visible()  # not the <option>

    # ---- status change through the row form (confirm() is accepted by the handler above)
    row.get_by_label("New status for Mangrove Planting").select_option("CLOSED")
    row.get_by_role("button", name="Set").click()
    expect(page.get_by_text("Activity Mangrove Planting is now CLOSED.")).to_be_visible()
    row = page.get_by_role("row", name=re.compile("Mangrove Planting"))
    expect(row.locator("span.badge-gray", has_text="Closed")).to_be_visible()
