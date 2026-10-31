"""Browser checks for the responsive layout and keyboard access (Phase 9, NFR Usability).

Through a real server: on a phone-sized viewport the sidebar is behind a menu button
that announces its state and can be closed with Escape; on any viewport the first Tab
reaches a "Skip to main content" link that moves focus into the main landmark; and a
submitted form disables its button so it cannot be sent twice.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import E2E_PASSWORD, E2E_USERNAME

pytestmark = pytest.mark.e2e


def log_in(page: Page, live_server: str) -> None:
    page.goto(f"{live_server}/login")
    page.get_by_label("Username").fill(E2E_USERNAME)
    page.get_by_label("Password").fill(E2E_PASSWORD)
    page.get_by_role("button", name="Login").click()
    expect(page).to_have_url(f"{live_server}/volunteer/dashboard")


def test_phone_layout_hides_the_sidebar_behind_an_accessible_menu_button(
    page: Page, live_server: str
) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    log_in(page, live_server)

    toggle = page.get_by_role("button", name="Open menu")
    expect(toggle).to_be_visible()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    sidebar = page.locator("#sidebar")
    assert "-translate-x-full" in (sidebar.get_attribute("class") or "")  # off-screen

    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#sidebar-backdrop")).to_be_visible()
    expect(sidebar.get_by_role("link", name="My Registrations")).to_be_visible()

    page.keyboard.press("Escape")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#sidebar-backdrop")).to_be_hidden()

    # No horizontal scrolling on a phone.
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_skip_link_moves_focus_to_the_main_landmark(page: Page, live_server: str) -> None:
    log_in(page, live_server)
    page.keyboard.press("Tab")
    skip = page.get_by_role("link", name="Skip to main content")
    expect(skip).to_be_focused()
    expect(skip).to_be_visible()  # sr-only until focused
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement && document.activeElement.id") == "main"


def test_submit_button_shows_a_loading_state_once(page: Page, live_server: str) -> None:
    page.goto(f"{live_server}/login")
    page.get_by_label("Username").fill(E2E_USERNAME)
    page.get_by_label("Password").fill(E2E_PASSWORD)
    button = page.locator("form button[type=submit]")

    # Stop the navigation AFTER the app's document-level handler has run (window
    # listeners bubble last), so the loading state can be observed on the same page.
    page.evaluate("window.addEventListener('submit', function (e) { e.preventDefault(); })")
    button.click()
    expect(button).to_be_disabled()
    expect(button).to_have_attribute("aria-busy", "true")
    expect(button).to_have_text("Please wait…")
    expect(page).to_have_url(f"{live_server}/login")  # still here: navigation was stopped
