"""Integration tests for browsing activities (FR-2, FR-3, FR-4, NFR Performance).

They drive the real `activities` controller and the volunteer dashboard with
Flask's test client against the test database. Activities are inserted through
the DAOs with dates relative to today, so the tests keep working on any day.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from flask.testing import FlaskClient

from app.auth.passwords import hash_password
from app.dao import ActivityDAO, LocationDAO, RegistrationDAO, RoleDAO, UserDAO
from app.database import DatabaseManager
from app.models import (
    Activity,
    ActivityStatus,
    Location,
    Person,
    Registration,
    RegistrationStatus,
    RoleName,
    Volunteer,
)
from tests.integration.test_auth_flow import (
    ADMIN_PASSWORD,
    VOL_PASSWORD,
    log_in,
    make_admin,
    sign_up,
)


# ----------------------------------------------------------------- helpers
def days(n: int) -> date:
    return date.today() + timedelta(days=n)


def make_location(db: DatabaseManager, name: str = "Riverside Park") -> Location:
    location = Location(
        location_name=name, address=f"{name} Drive, Green City", details="Meet at the main gate."
    )
    LocationDAO(db).insert(location)
    return location


def make_activity(
    db: DatabaseManager,
    admin: Person,
    location: Location,
    title: str,
    *,
    in_days: int = 7,
    status: ActivityStatus = ActivityStatus.OPEN,
    max_volunteers: int = 10,
    description: str | None = "Plant native seedlings along the riverbank.",
) -> Activity:
    activity = Activity(
        created_by=admin.id or 0,
        location_id=location.id or 0,
        title=title,
        description=description,
        activity_date=days(in_days),
        start_time=time(7, 0),
        end_time=time(11, 0),
        max_volunteers=max_volunteers,
        requirements="Bring water and wear closed shoes.",
        status=status,
    )
    ActivityDAO(db).insert(activity)
    return activity


def make_volunteer(db: DatabaseManager, username: str) -> Volunteer:
    role = RoleDAO(db).find_by_name(RoleName.VOLUNTEER)
    volunteer = Volunteer(
        role_id=role.id or 0,
        role_name=RoleName.VOLUNTEER,
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password(VOL_PASSWORD),
        first_name="Vol",
        last_name=username.capitalize(),
    )
    UserDAO(db).insert(volunteer)
    return volunteer


def register(
    db: DatabaseManager, activity: Activity, user: Person, status: RegistrationStatus
) -> None:
    RegistrationDAO(db).insert(
        Registration(activity_id=activity.id or 0, user_id=user.id or 0, status=status)
    )


def logged_in_volunteer(client: FlaskClient) -> None:
    sign_up(client)
    log_in(client, "vol_one", VOL_PASSWORD)


def page_text(client: FlaskClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, response.status_code
    return response.get_data(as_text=True)


def card_count(page: str) -> int:
    return page.count("View details")


# ------------------------------------------------------------- access (FR-2)
def test_browse_pages_require_login(client: FlaskClient) -> None:
    for path in ("/activities", "/activities/1"):
        response = client.get(path)
        assert response.status_code == 302 and response.headers["Location"].startswith("/login")


def test_admin_can_browse_too(client: FlaskClient, clean_db: DatabaseManager) -> None:
    admin = make_admin(clean_db)
    activity = make_activity(clean_db, admin, make_location(clean_db), "Riverbank Drive")
    log_in(client, "admin1", ADMIN_PASSWORD)

    assert "Riverbank Drive" in page_text(client, "/activities")
    assert "Riverbank Drive" in page_text(client, f"/activities/{activity.id}")


# ----------------------------------------------------------------- the list
def test_only_open_future_activities_are_listed(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = make_admin(clean_db)
    park = make_location(clean_db)
    make_activity(clean_db, admin, park, "Open next week", in_days=7)
    make_activity(clean_db, admin, park, "Open today", in_days=0)
    make_activity(clean_db, admin, park, "Open yesterday", in_days=-1)  # past: hidden
    make_activity(clean_db, admin, park, "Closed soon", in_days=5, status=ActivityStatus.CLOSED)
    make_activity(clean_db, admin, park, "Cancelled soon", status=ActivityStatus.CANCELLED)
    make_activity(clean_db, admin, park, "Completed soon", status=ActivityStatus.COMPLETED)
    logged_in_volunteer(client)

    page = page_text(client, "/activities")

    assert card_count(page) == 2
    assert "Open next week" in page and "Open today" in page
    for hidden in ("Open yesterday", "Closed soon", "Cancelled soon", "Completed soon"):
        assert hidden not in page
    assert page.index("Open today") < page.index("Open next week")  # soonest first
    assert 'aria-current="page"' in page  # "Activities" is highlighted in the sidebar


def test_card_shows_date_time_location_slots_and_badge(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = make_admin(clean_db)
    park = make_location(clean_db, "Hillside Reserve")
    activity = make_activity(clean_db, admin, park, "Hillside Planting", in_days=3)
    register(clean_db, activity, make_volunteer(clean_db, "pending"), RegistrationStatus.PENDING)
    register(clean_db, activity, make_volunteer(clean_db, "approved"), RegistrationStatus.APPROVED)
    logged_in_volunteer(client)

    page = page_text(client, "/activities")

    assert days(3).strftime("%a, %b %d, %Y") in page
    assert "7:00 AM - 11:00 AM" in page
    assert "Hillside Reserve" in page
    assert "8 of 10 slots left" in page
    assert 'class="badge-green">Open</span>' in page
    assert f'href="/activities/{activity.id}"' in page


def test_full_activity_shows_full(client: FlaskClient, clean_db: DatabaseManager) -> None:
    admin = make_admin(clean_db)
    activity = make_activity(clean_db, admin, make_location(clean_db), "Tiny", max_volunteers=1)
    register(clean_db, activity, make_volunteer(clean_db, "lucky"), RegistrationStatus.APPROVED)
    logged_in_volunteer(client)

    assert "Full" in page_text(client, "/activities")
    detail = page_text(client, f"/activities/{activity.id}")
    assert "Full" in detail and "All 1 slots are taken." in detail


# ------------------------------------------------------------------ filters
def test_keyword_filter_matches_title_or_description(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = make_admin(clean_db)
    park = make_location(clean_db)
    make_activity(clean_db, admin, park, "Mangrove Seedling Day", description="By the river.")
    make_activity(clean_db, admin, park, "Campus Corridor", description="Near the mangrove area.")
    make_activity(clean_db, admin, park, "Hillside Planting", description="Bring gloves.")
    logged_in_volunteer(client)

    page = page_text(client, "/activities?keyword=mangrove")

    assert card_count(page) == 2
    assert "Mangrove Seedling Day" in page and "Campus Corridor" in page
    assert "Hillside Planting" not in page
    assert 'value="mangrove"' in page  # the typed keyword stays in the box
    assert ">Clear</a>" in page


def test_location_filter(client: FlaskClient, clean_db: DatabaseManager) -> None:
    admin = make_admin(clean_db)
    park = make_location(clean_db, "Riverside Park")
    hill = make_location(clean_db, "Hillside Reserve")
    make_activity(clean_db, admin, park, "River planting")
    make_activity(clean_db, admin, hill, "Hill planting")
    logged_in_volunteer(client)

    page = page_text(client, f"/activities?location_id={hill.id}")

    assert card_count(page) == 1 and "Hill planting" in page and "River planting" not in page
    assert f'<option value="{hill.id}" selected>Hillside Reserve</option>' in page
    assert f'<option value="{park.id}" >Riverside Park</option>' in page  # all locations listed


def test_date_filter(client: FlaskClient, clean_db: DatabaseManager) -> None:
    admin = make_admin(clean_db)
    park = make_location(clean_db)
    make_activity(clean_db, admin, park, "In five days", in_days=5)
    make_activity(clean_db, admin, park, "In six days", in_days=6)
    logged_in_volunteer(client)

    page = page_text(client, f"/activities?activity_date={days(5).isoformat()}")

    assert card_count(page) == 1 and "In five days" in page and "In six days" not in page
    assert f'value="{days(5).isoformat()}"' in page


def test_invalid_filter_values_are_ignored(client: FlaskClient, clean_db: DatabaseManager) -> None:
    """FR-4 for a GET form: a hand-edited URL shows the unfiltered list, never an error."""
    admin = make_admin(clean_db)
    make_activity(clean_db, admin, make_location(clean_db), "Still listed")
    logged_in_volunteer(client)

    page = page_text(client, "/activities?location_id=abc&activity_date=not-a-date&page=zero")

    assert card_count(page) == 1 and "Still listed" in page


def test_empty_state_has_a_clear_filters_link(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = make_admin(clean_db)
    make_activity(clean_db, admin, make_location(clean_db), "Something else")
    logged_in_volunteer(client)

    page = page_text(client, "/activities?keyword=zzz-no-match")

    assert card_count(page) == 0
    assert "No activities match your filters." in page
    assert 'href="/activities"' in page and "Clear filters" in page
    assert "Showing" not in page  # no pagination bar for an empty list


# --------------------------------------------------------------- pagination
def test_pagination_splits_13_activities_and_links_keep_filters(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = make_admin(clean_db)
    park = make_location(clean_db, "Riverside Park")
    other = make_location(clean_db, "Elsewhere")
    for n in range(1, 14):  # 13 matching activities, one per day so the order is fixed
        make_activity(clean_db, admin, park, f"Session {n:02d}", in_days=n)
    make_activity(clean_db, admin, other, "Session 99 elsewhere", in_days=1)  # filtered out
    logged_in_volunteer(client)

    first = page_text(client, f"/activities?keyword=Session&location_id={park.id}")
    assert card_count(first) == 12
    assert "Session 01" in first and "Session 12" in first and "Session 13" not in first
    assert "Session 99 elsewhere" not in first
    assert "Showing <span" in first and "1-12</span> of 13" in first
    assert 'rel="next"' in first and 'rel="prev"' not in first
    next_link = first[first.index('<a href="', first.index("Page 1 of 2")) :]
    next_link = next_link[: next_link.index('"', 9)]
    assert "page=2" in next_link and "keyword=Session" in next_link
    assert f"location_id={park.id}" in next_link  # filters survive the page change

    second = page_text(client, f"/activities?keyword=Session&location_id={park.id}&page=2")
    assert card_count(second) == 1 and "Session 13" in second and "Session 12" not in second
    assert "13-13</span> of 13" in second
    assert 'rel="prev"' in second and 'rel="next"' not in second

    beyond = page_text(client, f"/activities?keyword=Session&location_id={park.id}&page=99")
    assert "Session 13" in beyond and "13-13</span> of 13" in beyond  # clamped to the last page


# ---------------------------------------------------------------- details
def test_details_page_counts_only_pending_and_approved_registrations(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = make_admin(clean_db)
    park = make_location(clean_db, "Riverside Park")
    activity = make_activity(clean_db, admin, park, "Riverbank Reforestation Drive", in_days=4)
    for name, status in (
        ("pending", RegistrationStatus.PENDING),
        ("approved", RegistrationStatus.APPROVED),
        ("rejected", RegistrationStatus.REJECTED),
        ("cancelled", RegistrationStatus.CANCELLED),
    ):
        register(clean_db, activity, make_volunteer(clean_db, name), status)
    logged_in_volunteer(client)

    page = page_text(client, f"/activities/{activity.id}")

    assert "Riverbank Reforestation Drive" in page
    assert "8 of 10 slots left" in page  # REJECTED and CANCELLED do not take a slot
    assert "Plant native seedlings along the riverbank." in page
    assert "Bring water and wear closed shoes." in page
    assert "Riverside Park Drive, Green City" in page and "Meet at the main gate." in page
    assert days(4).strftime("%A, %B %d, %Y") in page and "7:00 AM - 11:00 AM" in page
    assert "4.0 hours" in page
    assert ">Register</button>" in page and 'name="csrf_token"' in page  # Phase 5 form
    assert "Your request will be reviewed by an administrator." in page
    assert "Back to activities" in page and 'href="/activities"' in page
    assert 'aria-current="page"' in page  # the sidebar keeps "Activities" highlighted


def test_missing_activity_shows_the_404_page(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_volunteer(client)

    response = client.get("/activities/999")

    assert response.status_code == 404
    page = response.get_data(as_text=True)
    assert "Activity not found." in page and "Back to home" in page


# -------------------------------------------------------------- dashboard
def test_dashboard_shows_the_three_soonest_upcoming_activities(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = make_admin(clean_db)
    park = make_location(clean_db)
    third = make_activity(clean_db, admin, park, "Third soonest", in_days=10)
    first = make_activity(clean_db, admin, park, "First soonest", in_days=3)
    second = make_activity(clean_db, admin, park, "Second soonest", in_days=7)
    make_activity(clean_db, admin, park, "Fourth soonest", in_days=20)
    make_activity(clean_db, admin, park, "Already happened", in_days=-2)
    make_activity(clean_db, admin, park, "Closed tomorrow", in_days=1, status=ActivityStatus.CLOSED)
    logged_in_volunteer(client)

    page = page_text(client, "/volunteer/dashboard")

    assert "Upcoming activities" in page
    assert page.index("First soonest") < page.index("Second soonest") < page.index("Third soonest")
    for hidden in ("Fourth soonest", "Already happened", "Closed tomorrow"):
        assert hidden not in page
    for activity in (first, second, third):
        assert f'href="/activities/{activity.id}"' in page
    assert 'href="/activities"' in page  # "Browse Activities" card and "See all"


def test_dashboard_upcoming_empty_state(client: FlaskClient, clean_db: DatabaseManager) -> None:
    logged_in_volunteer(client)

    page = page_text(client, "/volunteer/dashboard")

    assert "No upcoming activities yet." in page
