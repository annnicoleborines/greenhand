"""Browser test for browsing activities (FR-3) with Playwright + Chromium.

Through a real server: a volunteer logs in, sees the upcoming activity on the
dashboard, opens Activities from the sidebar, filters by keyword, opens the
details page and reads the computed slots text.
"""

from __future__ import annotations

import re
from datetime import date, time, timedelta

import pytest
from playwright.sync_api import Page, expect

from app.dao import ActivityDAO, LocationDAO
from app.database import DatabaseManager
from app.models import Activity, Location
from tests.e2e.conftest import E2E_PASSWORD, E2E_USERNAME
from tests.integration.test_auth_flow import make_admin

pytestmark = pytest.mark.e2e


def seed_activities(db: DatabaseManager) -> None:
    admin = make_admin(db)
    park = Location(location_name="Riverside Park", address="Riverside Drive, Green City")
    LocationDAO(db).insert(park)
    for title, in_days, max_volunteers in (
        ("Riverbank Reforestation Drive", 7, 25),
        ("Hillside Native Tree Planting", 14, 15),
    ):
        ActivityDAO(db).insert(
            Activity(
                created_by=admin.id or 0,
                location_id=park.id or 0,
                title=title,
                description="Plant native seedlings with us.",
                activity_date=date.today() + timedelta(days=in_days),
                start_time=time(7, 0),
                end_time=time(11, 0),
                max_volunteers=max_volunteers,
            )
        )
    db.close()  # the server threads use their own connections


def test_volunteer_filters_activities_and_opens_details(
    page: Page, live_server: str, clean_db: DatabaseManager
) -> None:
    seed_activities(clean_db)

    page.goto(f"{live_server}/login")
    page.get_by_label("Username").fill(E2E_USERNAME)
    page.get_by_label("Password").fill(E2E_PASSWORD)
    page.get_by_role("button", name="Login").click()
    expect(page).to_have_url(f"{live_server}/volunteer/dashboard")
    expect(page.get_by_role("heading", name="Upcoming activities")).to_be_visible()
    expect(page.get_by_role("link", name="Riverbank Reforestation Drive")).to_be_visible()

    page.get_by_role("link", name="Activities", exact=True).click()
    expect(page).to_have_url(f"{live_server}/activities")
    expect(page.get_by_role("link", name="View details")).to_have_count(2)

    page.get_by_label("Keyword").fill("Riverbank")
    page.get_by_role("button", name="Apply filters").click()
    expect(page).to_have_url(re.compile(r"/activities\?.*keyword=Riverbank"))
    expect(page.get_by_role("link", name="View details")).to_have_count(1)
    expect(page.get_by_text("Hillside Native Tree Planting")).to_have_count(0)
    expect(page.get_by_text("25 of 25 slots left")).to_be_visible()

    page.get_by_role("link", name="View details").click()
    expect(page).to_have_url(re.compile(r"/activities/\d+$"))
    expect(page.get_by_role("heading", name="Riverbank Reforestation Drive")).to_be_visible()
    expect(page.get_by_text("25 of 25 slots left")).to_be_visible()
    expect(page.get_by_text("Riverside Drive, Green City")).to_be_visible()
    expect(page.get_by_role("button", name="Register", exact=True)).to_be_enabled()
    expect(page.get_by_text("Your request will be reviewed by an administrator.")).to_be_visible()

    page.get_by_role("link", name="Back to activities").first.click()
    expect(page).to_have_url(f"{live_server}/activities")
