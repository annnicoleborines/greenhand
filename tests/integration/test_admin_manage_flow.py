"""Integration tests for the Phase 3 admin pages (FR-2, FR-3, FR-4, FR-6).

They drive the real `admin_volunteers`, `admin_locations` and `admin_activities`
controllers with Flask's test client against the test database: role gates,
locations CRUD, activities CRUD with the delete-or-cancel rule, status changes,
and the volunteers list with deactivate / activate / reset password.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, time, timedelta
from typing import Any

from flask import Flask
from flask.testing import FlaskClient

from app.auth.passwords import hash_password
from app.dao import ActivityDAO, LocationDAO, RegistrationDAO, RoleDAO, UserDAO
from app.database import DatabaseManager
from app.models import (
    Activity,
    ActivityStatus,
    Admin,
    Location,
    Registration,
    RegistrationStatus,
    RoleName,
    UserStatus,
    Volunteer,
)
from tests.integration.test_auth_flow import (
    ADMIN_PASSWORD,
    VOL_PASSWORD,
    count,
    log_in,
    make_admin,
    sign_up,
)

LOCATIONS_URL = "/admin/locations/"
ACTIVITIES_URL = "/admin/activities/"
VOLUNTEERS_URL = "/admin/volunteers/"
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


# ------------------------------------------------------------------ helpers
def logged_in_admin(client: FlaskClient, db: DatabaseManager) -> Admin:
    admin = make_admin(db)
    log_in(client, "admin1", ADMIN_PASSWORD)
    return admin


def logged_in_volunteer(client: FlaskClient) -> None:
    sign_up(client)
    log_in(client, "vol_one", VOL_PASSWORD)


def in_fresh_browser[T](app: Flask, action: Callable[[FlaskClient], T]) -> T:
    """Run `action` with a new test client AND a new app context.

    The shared `app` fixture keeps one app context open for the whole test, and
    Flask-Login caches the current user on `g` inside it. A second client would
    therefore look logged in as whoever used the first one; a nested app context
    gives it a clean `g`, like a second browser.
    """
    with app.app_context():
        return action(app.test_client())


def register_volunteer(app: Flask) -> Volunteer:
    """Sign up vol_one (Vicky Vol) from a fresh browser; the admin's client stays logged in."""
    in_fresh_browser(app, sign_up)
    user = UserDAO(app.extensions["db_manager"]).find_by_username("vol_one")
    assert isinstance(user, Volunteer)
    return user


def login_attempt(app: Flask, username: str, password: str) -> int:
    """Status code of a login from a fresh browser: 302 = logged in, 200 = refused."""
    return in_fresh_browser(app, lambda browser: log_in(browser, username, password)).status_code


def add_location(db: DatabaseManager, name: str = "Riverside Park") -> Location:
    location = Location(location_name=name, address="1 River Road", details=None)
    LocationDAO(db).insert(location)
    return location


def add_activity(
    db: DatabaseManager, admin: Admin, location: Location, **overrides: Any
) -> Activity:
    fields: dict[str, Any] = {
        "created_by": admin.id,
        "location_id": location.id,
        "title": "Mangrove Planting",
        "activity_date": date.today() + timedelta(days=7),
        "start_time": time(8, 0),
        "end_time": time(11, 0),
        "max_volunteers": 20,
    }
    fields.update(overrides)
    activity = Activity(**fields)
    ActivityDAO(db).insert(activity)
    return activity


def add_volunteer(
    db: DatabaseManager,
    username: str,
    password_hash: str,
    *,
    first: str = "Vol",
    last: str = "Unteer",
) -> Volunteer:
    """Insert a volunteer straight through the DAO (no bcrypt per user: tests stay fast)."""
    role = RoleDAO(db).find_by_name(RoleName.VOLUNTEER)
    user = Volunteer(
        role_id=role.id or 0,
        role_name=RoleName.VOLUNTEER,
        username=username,
        email=f"{username}@example.com",
        password_hash=password_hash,
        first_name=first,
        last_name=last,
    )
    UserDAO(db).insert(user)
    return user


def add_registration(
    db: DatabaseManager, activity: Activity, user: Volunteer, status: RegistrationStatus
) -> Registration:
    registration = Registration(activity_id=activity.id or 0, user_id=user.id or 0, status=status)
    RegistrationDAO(db).insert(registration)
    return registration


def location_form(**overrides: str) -> dict[str, str]:
    form = {"location_name": "Riverside Park", "address": "1 River Road", "details": ""}
    form.update(overrides)
    return form


def activity_form(location: Location, **overrides: str) -> dict[str, str]:
    form = {
        "title": "Mangrove Planting",
        "description": "Plant 200 seedlings along the river.",
        "location_id": str(location.id),
        "activity_date": TOMORROW,
        "start_time": "08:00",
        "end_time": "11:00",
        "max_volunteers": "20",
        "requirements": "",
    }
    form.update(overrides)
    return form


def audit_details(db: DatabaseManager, action: str) -> list[str]:
    rows = db.fetch_all("SELECT details FROM audit_logs WHERE action = %s ORDER BY id", (action,))
    return [str(r["details"]) for r in rows]


def page_text(client: FlaskClient, url: str) -> str:
    return client.get(url).get_data(as_text=True)


def visible_text(html: str) -> str:
    """The page as a reader sees it: tags removed, whitespace collapsed to single spaces."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


# ------------------------------------------------------------- access (FR-2)
def test_admin_pages_require_login(client: FlaskClient) -> None:
    for path in (LOCATIONS_URL, ACTIVITIES_URL, VOLUNTEERS_URL):
        response = client.get(path)
        assert response.status_code == 302 and response.headers["Location"].startswith("/login")


def test_volunteer_gets_403_on_every_admin_page(client: FlaskClient) -> None:
    logged_in_volunteer(client)
    gets = [
        LOCATIONS_URL,
        "/admin/locations/new",
        "/admin/locations/1/edit",
        ACTIVITIES_URL,
        "/admin/activities/new",
        "/admin/activities/1/edit",
        VOLUNTEERS_URL,
    ]
    posts = [
        "/admin/locations/new",
        "/admin/locations/1/edit",
        "/admin/locations/1/delete",
        "/admin/activities/new",
        "/admin/activities/1/edit",
        "/admin/activities/1/delete",
        "/admin/activities/1/status",
        "/admin/volunteers/1/deactivate",
        "/admin/volunteers/1/activate",
        "/admin/volunteers/1/reset-password",
    ]
    for path in gets:
        assert client.get(path).status_code == 403, path
    for path in posts:
        assert client.post(path, data={}).status_code == 403, path


def test_sidebar_and_dashboard_link_to_the_admin_pages(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    dashboard = page_text(client, "/admin/dashboard")
    assert f'href="{ACTIVITIES_URL}"' in dashboard and f'href="{VOLUNTEERS_URL}"' in dashboard
    assert f'href="{LOCATIONS_URL}"' in dashboard  # sidebar
    assert 'aria-current="page"' in page_text(client, LOCATIONS_URL)


# ------------------------------------------------------------ locations (FR-3)
def test_create_location_shows_in_list_and_audits(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)

    response = client.post("/admin/locations/new", data=location_form(details="Bring gloves."))

    assert response.status_code == 302 and response.headers["Location"].endswith(LOCATIONS_URL)
    saved = LocationDAO(clean_db).find_by_name("Riverside Park")
    assert (
        saved is not None and saved.address == "1 River Road" and saved.details == "Bring gloves."
    )
    assert audit_details(clean_db, "LOCATION_CREATED") == ["Created location Riverside Park."]

    page = page_text(client, LOCATIONS_URL)
    assert "Location Riverside Park has been added." in page
    assert "Riverside Park" in page and "1 location" in page and "New Location" in page


def test_duplicate_location_name_shows_an_inline_error(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    add_location(clean_db)

    response = client.post("/admin/locations/new", data=location_form(address="Somewhere else"))

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "A location with that name already exists." in page
    assert 'id="location_name-error"' in page
    assert 'value="Somewhere else"' in page  # typed values are kept
    assert count(clean_db, "SELECT COUNT(*) AS n FROM locations") == 1


def test_invalid_location_shows_errors_and_saves_nothing(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)

    response = client.post(
        "/admin/locations/new", data=location_form(location_name="A", address="")
    )

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'id="location_name-error"' in page and 'id="address-error"' in page
    assert count(clean_db, "SELECT COUNT(*) AS n FROM locations") == 0
    assert audit_details(clean_db, "LOCATION_CREATED") == []


def test_edit_location_is_prefilled_then_updates_and_audits(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    location = add_location(clean_db)
    edit_url = f"/admin/locations/{location.id}/edit"

    page = page_text(client, edit_url)
    assert 'value="Riverside Park"' in page and "Edit Location" in page

    response = client.post(edit_url, data=location_form(address="2 River Road"))

    assert response.status_code == 302
    saved = LocationDAO(clean_db).find_by_id(location.id or 0)
    assert saved is not None and saved.address == "2 River Road"
    assert audit_details(clean_db, "LOCATION_UPDATED") == ["Changed: address."]


def test_edit_location_to_another_locations_name_is_refused(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    add_location(clean_db, "Hilltop Grove")
    location = add_location(clean_db)

    response = client.post(
        f"/admin/locations/{location.id}/edit", data=location_form(location_name="Hilltop Grove")
    )

    assert response.status_code == 200
    assert "A location with that name already exists." in response.get_data(as_text=True)
    saved = LocationDAO(clean_db).find_by_id(location.id or 0)
    assert saved is not None and saved.location_name == "Riverside Park"


def test_delete_location_without_activities_removes_the_row(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    location = add_location(clean_db)

    response = client.post(f"/admin/locations/{location.id}/delete")

    assert response.status_code == 302
    assert LocationDAO(clean_db).find_by_id(location.id or 0) is None
    assert audit_details(clean_db, "LOCATION_DELETED") == ["Deleted location Riverside Park."]
    assert "has been deleted." in page_text(client, LOCATIONS_URL)


def test_delete_location_with_activities_is_refused(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    location = add_location(clean_db)
    add_activity(clean_db, admin, location)

    response = client.post(f"/admin/locations/{location.id}/delete")

    assert response.status_code == 302
    assert LocationDAO(clean_db).find_by_id(location.id or 0) is not None
    page = page_text(client, LOCATIONS_URL)
    assert "cannot be deleted" in page and "1 activity uses this location" in page
    assert audit_details(clean_db, "LOCATION_DELETED") == []


def test_unknown_location_is_404(client: FlaskClient, clean_db: DatabaseManager) -> None:
    logged_in_admin(client, clean_db)
    assert client.get("/admin/locations/999/edit").status_code == 404
    assert client.post("/admin/locations/999/delete").status_code == 404


# ----------------------------------------------------------- activities (FR-3)
def test_create_activity_from_the_form(client: FlaskClient, clean_db: DatabaseManager) -> None:
    admin = logged_in_admin(client, clean_db)
    location = add_location(clean_db)

    response = client.post("/admin/activities/new", data=activity_form(location))

    assert response.status_code == 302 and response.headers["Location"].endswith(ACTIVITIES_URL)
    saved = ActivityDAO(clean_db).find_by_title("Mangrove Planting")
    assert saved is not None
    assert saved.status == ActivityStatus.OPEN and saved.created_by == admin.id
    assert saved.activity_date.isoformat() == TOMORROW
    assert saved.start_time == time(8, 0) and saved.end_time == time(11, 0)
    assert saved.max_volunteers == 20 and saved.requirements is None
    assert audit_details(clean_db, "ACTIVITY_CREATED") == ["Created activity Mangrove Planting."]

    page = page_text(client, ACTIVITIES_URL)
    assert "Activity Mangrove Planting has been created." in page
    assert "Riverside Park" in page and "08:00 - 11:00" in page and "/ 20" in page
    assert "20 left" in page and ">Open<" in page


def test_create_activity_with_bad_input_shows_errors_and_saves_nothing(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    location = add_location(clean_db)

    response = client.post(
        "/admin/activities/new",
        data=activity_form(
            location, activity_date=YESTERDAY, end_time="07:00", location_id="", title="Hi"
        ),
    )

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Activity date cannot be in the past." in page
    assert "End time must be after start time." in page and 'id="end_time-error"' in page
    assert "Choose a location." in page and 'id="location_id-error"' in page
    assert 'id="title-error"' in page
    assert "Plant 200 seedlings along the river." in page  # typed values are kept
    assert count(clean_db, "SELECT COUNT(*) AS n FROM activities") == 0


def test_create_activity_with_unknown_location_id_is_refused(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    location = add_location(clean_db)

    response = client.post("/admin/activities/new", data=activity_form(location, location_id="999"))

    assert response.status_code == 200
    assert "Choose a location." in response.get_data(as_text=True)
    assert count(clean_db, "SELECT COUNT(*) AS n FROM activities") == 0


def test_edit_activity_is_prefilled_allows_a_past_date_and_audits(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    location = add_location(clean_db)
    activity = add_activity(clean_db, admin, location)
    edit_url = f"/admin/activities/{activity.id}/edit"

    page = page_text(client, edit_url)
    assert (
        'value="Mangrove Planting"' in page and 'value="08:00"' in page and 'value="11:00"' in page
    )
    assert f'<option value="{location.id}" selected>' in page

    response = client.post(
        edit_url, data=activity_form(location, activity_date=YESTERDAY, title="Mangrove Day")
    )

    assert response.status_code == 302
    saved = ActivityDAO(clean_db).find_by_id(activity.id or 0)
    assert saved is not None and saved.title == "Mangrove Day"
    assert saved.activity_date.isoformat() == YESTERDAY
    details = audit_details(clean_db, "ACTIVITY_UPDATED")
    assert len(details) == 1 and "title" in details[0] and "activity_date" in details[0]


def test_edit_cannot_drop_capacity_below_slots_already_taken(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    location = add_location(clean_db)
    activity = add_activity(clean_db, admin, location)
    shared_hash = hash_password("Shared123")
    add_registration(
        clean_db, activity, add_volunteer(clean_db, "v1", shared_hash), RegistrationStatus.PENDING
    )
    add_registration(
        clean_db, activity, add_volunteer(clean_db, "v2", shared_hash), RegistrationStatus.APPROVED
    )

    response = client.post(
        f"/admin/activities/{activity.id}/edit", data=activity_form(location, max_volunteers="1")
    )

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "2 volunteers already hold slots." in page and 'id="max_volunteers-error"' in page
    saved = ActivityDAO(clean_db).find_by_id(activity.id or 0)
    assert saved is not None and saved.max_volunteers == 20


def test_list_paginates_ten_per_page_and_filters_by_status(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    location = add_location(clean_db)
    for i in range(11):
        add_activity(clean_db, admin, location, title=f"Open activity {i:02d}")
    closed = add_activity(clean_db, admin, location, title="Closed activity")
    ActivityDAO(clean_db).set_status(closed.id or 0, ActivityStatus.CLOSED)

    page_one = page_text(client, ACTIVITIES_URL)
    assert "12 activities" in page_one and "?page=2" in page_one
    assert "Showing 1-10 of 12 activities" in visible_text(page_one)
    assert "Page 1 of 2" in page_one

    page_two = visible_text(page_text(client, f"{ACTIVITIES_URL}?page=2"))
    assert "Showing 11-12 of 12 activities" in page_two

    only_closed = page_text(client, f"{ACTIVITIES_URL}?status=closed")
    assert "1 closed activity" in only_closed and "Closed activity" in only_closed
    assert "Open activity 00" not in only_closed
    assert 'value="CLOSED" selected' in only_closed  # the filter box keeps the choice

    assert "12 activities" in page_text(client, f"{ACTIVITIES_URL}?status=bogus")  # unknown = all


def test_change_status_audits_the_transition_and_rejects_bad_values(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    activity = add_activity(clean_db, admin, add_location(clean_db))
    status_url = f"/admin/activities/{activity.id}/status"

    response = client.post(f"{status_url}?status=OPEN&page=1", data={"status": "CLOSED"})

    assert response.status_code == 302
    location_header = response.headers["Location"]
    assert "status=OPEN" in location_header and "page=1" in location_header  # back to the same view
    saved = ActivityDAO(clean_db).find_by_id(activity.id or 0)
    assert saved is not None and saved.status == ActivityStatus.CLOSED
    assert audit_details(clean_db, "ACTIVITY_STATUS_CHANGED") == ["OPEN -> CLOSED"]
    assert "Activity Mangrove Planting is now CLOSED." in page_text(client, ACTIVITIES_URL)

    client.post(status_url, data={"status": "CLOSED"})  # same status again
    assert "already CLOSED" in page_text(client, ACTIVITIES_URL)

    client.post(status_url, data={"status": "BOGUS"})
    assert "Choose a valid status." in page_text(client, ACTIVITIES_URL)
    assert (
        count(clean_db, "SELECT COUNT(*) AS n FROM audit_logs WHERE entity = %s", ("activity",))
        == 1
    )


def test_delete_without_registrations_removes_the_row(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    activity = add_activity(clean_db, admin, add_location(clean_db))

    response = client.post(f"/admin/activities/{activity.id}/delete")

    assert response.status_code == 302 and response.headers["Location"].endswith(ACTIVITIES_URL)
    assert ActivityDAO(clean_db).find_by_id(activity.id or 0) is None
    assert audit_details(clean_db, "ACTIVITY_DELETED") == ["Deleted activity Mangrove Planting."]
    assert count(clean_db, "SELECT COUNT(*) AS n FROM notifications") == 0
    assert "Activity Mangrove Planting has been deleted." in page_text(client, ACTIVITIES_URL)


def test_delete_with_registrations_cancels_notifies_slot_holders_and_audits(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    activity = add_activity(clean_db, admin, add_location(clean_db))
    shared_hash = hash_password("Shared123")
    pending = add_volunteer(clean_db, "pending_vol", shared_hash)
    approved = add_volunteer(clean_db, "approved_vol", shared_hash)
    rejected = add_volunteer(clean_db, "rejected_vol", shared_hash)
    add_registration(clean_db, activity, pending, RegistrationStatus.PENDING)
    add_registration(clean_db, activity, approved, RegistrationStatus.APPROVED)
    add_registration(clean_db, activity, rejected, RegistrationStatus.REJECTED)

    response = client.post(f"/admin/activities/{activity.id}/delete")

    assert response.status_code == 302
    saved = ActivityDAO(clean_db).find_by_id(activity.id or 0)
    assert saved is not None and saved.status == ActivityStatus.CANCELLED  # not deleted
    assert count(clean_db, "SELECT COUNT(*) AS n FROM registrations") == 3  # untouched

    rows = clean_db.fetch_all(
        "SELECT user_id, type, message FROM notifications ORDER BY user_id", ()
    )
    assert [r["user_id"] for r in rows] == sorted(
        [pending.id or 0, approved.id or 0]
    )  # not the rejected one
    assert all(r["type"] == "ACTIVITY_CANCELLED" for r in rows)
    expected_date = activity.activity_date.isoformat()
    assert all(
        r["message"] == f"Activity Mangrove Planting on {expected_date} was cancelled."
        for r in rows
    )

    assert audit_details(clean_db, "ACTIVITY_CANCELLED") == [
        "OPEN -> CANCELLED; 2 volunteer(s) notified."
    ]
    assert audit_details(clean_db, "ACTIVITY_DELETED") == []
    page = page_text(client, ACTIVITIES_URL)
    assert "was cancelled instead of" in page and ">Cancelled<" in page

    # A second delete has nothing left to cancel.
    client.post(f"/admin/activities/{activity.id}/delete")
    assert "already CANCELLED" in page_text(client, ACTIVITIES_URL)


def test_status_cancelled_follows_the_cancel_path(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    activity = add_activity(clean_db, admin, add_location(clean_db))
    volunteer = add_volunteer(clean_db, "pending_vol", hash_password("Shared123"))
    add_registration(clean_db, activity, volunteer, RegistrationStatus.PENDING)

    client.post(f"/admin/activities/{activity.id}/status", data={"status": "cancelled"})

    saved = ActivityDAO(clean_db).find_by_id(activity.id or 0)
    assert saved is not None and saved.status == ActivityStatus.CANCELLED
    assert (
        count(
            clean_db, "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s", (volunteer.id,)
        )
        == 1
    )
    assert audit_details(clean_db, "ACTIVITY_CANCELLED") == [
        "OPEN -> CANCELLED; 1 volunteer(s) notified."
    ]
    assert audit_details(clean_db, "ACTIVITY_STATUS_CHANGED") == []
    assert "has been cancelled and registered volunteers notified." in page_text(
        client, ACTIVITIES_URL
    )


def test_unknown_activity_is_404(client: FlaskClient, clean_db: DatabaseManager) -> None:
    logged_in_admin(client, clean_db)
    assert client.get("/admin/activities/999/edit").status_code == 404
    assert client.post("/admin/activities/999/delete").status_code == 404
    assert client.post("/admin/activities/999/status", data={"status": "CLOSED"}).status_code == 404


# ----------------------------------------------------------- volunteers (FR-3)
def test_volunteers_list_searches_and_never_shows_admins(
    app: Flask, client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    register_volunteer(app)  # Vicky Vol, vol_one
    add_volunteer(clean_db, "zed", hash_password("Shared123"), first="Zed", last="Zero")

    page = page_text(client, VOLUNTEERS_URL)
    assert "2 volunteers" in page and "Vicky Vol" in page and "Zed Zero" in page
    assert "admin1" not in page and ">Active<" in page
    assert "Deactivate" in page and "Reset password" in page

    found = page_text(client, f"{VOLUNTEERS_URL}?q=vicky")
    assert '1 volunteer matching "vicky"' in found and "Vicky Vol" in found
    assert "Zed Zero" not in found and 'value="vicky"' in found  # search box keeps the text

    by_email = page_text(client, f"{VOLUNTEERS_URL}?q=zed@example")
    assert "Zed Zero" in by_email and "Vicky Vol" not in by_email

    none = page_text(client, f"{VOLUNTEERS_URL}?q=nobody")
    assert 'No volunteers match "nobody".' in none


def test_volunteers_list_paginates_twenty_per_page(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    shared_hash = hash_password("Shared123")
    for i in range(25):
        add_volunteer(clean_db, f"vol{i:02d}", shared_hash, last=f"Z{i:02d}")

    page_one = visible_text(page_text(client, VOLUNTEERS_URL))
    assert "Showing 1-20 of 25 volunteers" in page_one and "Page 1 of 2" in page_one
    assert "vol00" in page_one and "vol24" not in page_one

    page_two = visible_text(page_text(client, f"{VOLUNTEERS_URL}?page=2"))
    assert "Showing 21-25 of 25 volunteers" in page_two
    assert "vol24" in page_two and "vol00" not in page_two


def test_deactivate_blocks_login_and_activate_restores_it(
    app: Flask, client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    volunteer = register_volunteer(app)

    response = client.post(f"/admin/volunteers/{volunteer.id}/deactivate?q=vol&page=1")

    assert response.status_code == 302 and "q=vol" in response.headers["Location"]
    saved = UserDAO(clean_db).find_by_id(volunteer.id or 0)
    assert saved is not None and saved.status == UserStatus.INACTIVE
    assert audit_details(clean_db, "USER_DEACTIVATED") == [
        "Account vol_one deactivated by an administrator."
    ]
    page = page_text(client, VOLUNTEERS_URL)
    assert "Vicky Vol (vol_one) has been deactivated." in page and ">Inactive<" in page
    assert "Activate" in page

    refused = in_fresh_browser(app, lambda browser: log_in(browser, "vol_one", VOL_PASSWORD))
    assert (
        refused.status_code == 403
    )  # same answer as test_auth_flow::test_inactive_account_cannot_log_in
    assert "inactive" in refused.get_data(as_text=True).lower()

    client.post(f"/admin/volunteers/{volunteer.id}/activate")
    saved = UserDAO(clean_db).find_by_id(volunteer.id or 0)
    assert saved is not None and saved.status == UserStatus.ACTIVE
    assert audit_details(clean_db, "USER_ACTIVATED") == [
        "Account vol_one activated by an administrator."
    ]
    assert login_attempt(app, "vol_one", VOL_PASSWORD) == 302  # works again


def test_admin_cannot_deactivate_their_own_account(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)

    response = client.post(f"/admin/volunteers/{admin.id}/deactivate")

    assert response.status_code == 302
    assert "You cannot deactivate your own account." in page_text(client, VOLUNTEERS_URL)
    saved = UserDAO(clean_db).find_by_id(admin.id or 0)
    assert saved is not None and saved.status == UserStatus.ACTIVE
    assert audit_details(clean_db, "USER_DEACTIVATED") == []


def test_reset_password_shows_the_temporary_password_once_and_it_logs_in(
    app: Flask, client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    volunteer = register_volunteer(app)

    response = client.post(f"/admin/volunteers/{volunteer.id}/reset-password")

    assert response.status_code == 302
    page = page_text(client, VOLUNTEERS_URL)
    match = re.search(r"Temporary password for vol_one: ([A-Za-z0-9]{12})", page)
    assert match is not None
    temporary = match.group(1)
    assert any(c.isalpha() for c in temporary) and any(c.isdigit() for c in temporary)
    assert "Temporary password" not in page_text(client, VOLUNTEERS_URL)  # flashed only once

    details = audit_details(clean_db, "PASSWORD_RESET")
    assert details == ["Temporary password issued for vol_one."] and temporary not in details[0]
    note = clean_db.fetch_one(
        "SELECT type, message FROM notifications WHERE user_id = %s", (volunteer.id,)
    )
    assert note is not None and note["type"] == "PASSWORD_RESET"
    assert note["message"] == "Your password was reset by an administrator."
    assert temporary not in note["message"]

    assert login_attempt(app, "vol_one", VOL_PASSWORD) == 200  # old password: refused
    assert login_attempt(app, "vol_one", temporary) == 302  # temporary password: works


def test_volunteer_actions_on_unknown_or_admin_accounts(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    assert client.post("/admin/volunteers/999/deactivate").status_code == 404
    assert client.post("/admin/volunteers/999/reset-password").status_code == 404

    client.post(f"/admin/volunteers/{admin.id}/reset-password")
    assert "Administrator accounts cannot be managed" in page_text(client, VOLUNTEERS_URL)
    assert audit_details(clean_db, "PASSWORD_RESET") == []
