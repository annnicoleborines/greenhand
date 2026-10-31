"""Browser test for My Registrations and Notifications (FR-3) with Playwright + Chromium.

Through a real server with CSRF enabled: a volunteer opens My Registrations from
the sidebar, cancels an approved registration (confirm() is accepted), sees the
Cancelled tab update, then opens the bell, reads one notification and marks it read.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from app.dao import NotificationDAO, RegistrationDAO, UserDAO
from app.database import DatabaseManager
from app.models import Notification, Registration, RegistrationStatus
from tests.e2e.conftest import E2E_PASSWORD, E2E_USERNAME
from tests.e2e.test_browse import seed_activities

pytestmark = pytest.mark.e2e


@pytest.fixture
def approved_and_notified(clean_db: DatabaseManager, live_server: str) -> None:
    """e2e_vol is APPROVED for the Riverbank drive and has one unread notification."""
    seed_activities(clean_db)
    user = UserDAO(clean_db).find_by_username(E2E_USERNAME)
    assert user is not None
    from app.dao import ActivityDAO

    riverbank = ActivityDAO(clean_db).find_by_title("Riverbank Reforestation Drive")
    assert riverbank is not None
    RegistrationDAO(clean_db).insert(
        Registration(
            activity_id=riverbank.id or 0, user_id=user.id or 0, status=RegistrationStatus.APPROVED
        )
    )
    NotificationDAO(clean_db).insert(
        Notification(
            user_id=user.id or 0,
            type="REGISTRATION_APPROVED",
            message="Your registration for Riverbank Reforestation Drive was approved.",
        )
    )
    clean_db.close()  # the server threads open their own connections


def test_volunteer_cancels_a_registration_and_reads_a_notification(
    page: Page, live_server: str, approved_and_notified: None
) -> None:
    page.on("dialog", lambda dialog: dialog.accept())  # answers the cancel confirm() with OK

    page.goto(f"{live_server}/login")
    page.get_by_label("Username").fill(E2E_USERNAME)
    page.get_by_label("Password").fill(E2E_PASSWORD)
    page.get_by_role("button", name="Login").click()
    expect(page).to_have_url(f"{live_server}/volunteer/dashboard")

    # ---- My Registrations: cancel the approved row
    page.get_by_role("link", name="My Registrations", exact=True).click()
    expect(page).to_have_url(f"{live_server}/registrations")
    row = page.locator("li", has_text="Riverbank Reforestation Drive")
    expect(row.locator("span.badge-green", has_text="Approved")).to_be_visible()
    row.get_by_role("button", name=re.compile("^Cancel registration")).click()
    expect(
        page.get_by_text("Your registration for Riverbank Reforestation Drive has been cancelled.")
    ).to_be_visible()
    row = page.locator("li", has_text="Riverbank Reforestation Drive")
    expect(row.locator("span.badge-gray", has_text="Cancelled")).to_be_visible()
    expect(row.get_by_role("link", name="Register again")).to_be_visible()
    expect(
        page.get_by_role("link", name=re.compile("^Cancelled 1"))
    ).to_be_visible()  # the tab count

    # ---- My Schedule shows nothing upcoming any more
    page.get_by_role("link", name="My Schedule").click()
    expect(page).to_have_url(f"{live_server}/registrations/schedule")
    expect(page.get_by_text("Nothing scheduled yet.")).to_be_visible()

    # ---- Notifications: the bell shows 1 unread, mark it read
    page.get_by_role("link", name="Notifications", exact=True).first.click()
    expect(page).to_have_url(f"{live_server}/notifications")
    expect(page.get_by_role("heading", name="1 unread")).to_be_visible()
    # The message also sits in the button's sr-only label, so pick the paragraph.
    expect(page.locator("p", has_text="was approved.")).to_be_visible()
    page.get_by_role("button", name=re.compile("^Mark as read")).click()
    expect(page.get_by_role("heading", name="All caught up")).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("^Mark as read"))).to_have_count(0)
