"""Browser test for registering for an activity (FR-3) with Playwright + Chromium.

Through a real server with CSRF enabled: a volunteer logs in, opens an activity
from the dashboard, clicks Register, and sees the "You are registered" state with
one slot fewer.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from app.database import DatabaseManager
from tests.e2e.conftest import E2E_PASSWORD, E2E_USERNAME
from tests.e2e.test_browse import seed_activities

pytestmark = pytest.mark.e2e


def test_volunteer_registers_from_the_details_page(
    page: Page, live_server: str, clean_db: DatabaseManager
) -> None:
    seed_activities(clean_db)  # Riverbank Reforestation Drive: 25 slots

    page.goto(f"{live_server}/login")
    page.get_by_label("Username").fill(E2E_USERNAME)
    page.get_by_label("Password").fill(E2E_PASSWORD)
    page.get_by_role("button", name="Login").click()
    expect(page).to_have_url(f"{live_server}/volunteer/dashboard")

    page.get_by_role("link", name="Riverbank Reforestation Drive").click()
    expect(page.get_by_role("heading", name="Riverbank Reforestation Drive")).to_be_visible()
    expect(page.get_by_text("25 of 25 slots left")).to_be_visible()

    page.get_by_role("button", name="Register", exact=True).click()

    expect(page.get_by_text("You are registered for Riverbank Reforestation Drive")).to_be_visible()
    expect(page.get_by_text("24 of 25 slots left")).to_be_visible()
    # The slot card (in the <aside>) now shows the registration state instead of the button.
    card_state = page.locator("aside [role='status']")
    expect(card_state).to_contain_text("You are registered")
    expect(card_state).to_contain_text("Pending")
    expect(page.get_by_role("button", name="Register", exact=True)).to_have_count(0)
