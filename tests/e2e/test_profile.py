"""Browser test for the volunteer profile pages (FR-3) with Playwright + Chromium.

Goes through a real server with CSRF enabled: log in, open My Profile from the
sidebar, edit the phone number and see the new value on the profile page.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import E2E_PASSWORD, E2E_USERNAME

pytestmark = pytest.mark.e2e


def test_volunteer_edits_phone_number_from_my_profile(page: Page, live_server: str) -> None:
    page.goto(f"{live_server}/login")
    page.get_by_label("Username").fill(E2E_USERNAME)
    page.get_by_label("Password").fill(E2E_PASSWORD)
    page.get_by_role("button", name="Login").click()
    expect(page).to_have_url(f"{live_server}/volunteer/dashboard")

    page.get_by_role("link", name="My Profile").click()
    expect(page).to_have_url(f"{live_server}/profile/")
    expect(page.get_by_role("heading", name="My Profile")).to_be_visible()
    expect(page.get_by_role("heading", name="Eve Browser")).to_be_visible()

    page.get_by_role("link", name="Edit Profile").click()
    expect(page).to_have_url(f"{live_server}/profile/edit")
    page.get_by_label("Phone number").fill("0917 555 1234")
    page.get_by_role("button", name="Save changes").click()

    expect(page).to_have_url(f"{live_server}/profile/")
    expect(page.get_by_text("Your profile has been updated.")).to_be_visible()
    expect(page.get_by_text("0917 555 1234")).to_be_visible()
