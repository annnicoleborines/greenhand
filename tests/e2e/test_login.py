"""Browser test for the login page (FR-1) with Playwright + Chromium.

Unlike the test-client tests, this goes through a real HTTP server with CSRF
enabled, so it also proves the hidden csrf_token field in the template works.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import E2E_PASSWORD, E2E_USERNAME

pytestmark = pytest.mark.e2e


def test_volunteer_can_log_in_and_out_in_the_browser(page: Page, live_server: str) -> None:
    page.goto(f"{live_server}/login")
    expect(page.get_by_role("heading", name="Welcome Back!")).to_be_visible()

    page.get_by_label("Username").fill(E2E_USERNAME)
    page.get_by_label("Password").fill(E2E_PASSWORD)
    page.get_by_role("button", name="Login").click()

    expect(page).to_have_url(f"{live_server}/volunteer/dashboard")
    expect(page.get_by_text("Welcome back, Eve!")).to_be_visible()

    page.get_by_role("button", name="Logout").click()
    expect(page).to_have_url(f"{live_server}/login")
    expect(page.get_by_text("You have been logged out.")).to_be_visible()


def test_wrong_password_keeps_user_on_login_with_generic_message(
    page: Page, live_server: str
) -> None:
    page.goto(f"{live_server}/login")
    page.get_by_label("Username").fill(E2E_USERNAME)
    page.get_by_label("Password").fill("not-the-password")
    page.get_by_role("button", name="Login").click()

    expect(page).to_have_url(f"{live_server}/login")
    expect(page.get_by_text("Invalid username or password.")).to_be_visible()
    expect(page.get_by_label("Username")).to_have_value(E2E_USERNAME)  # typed username kept
