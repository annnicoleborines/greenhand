"""Integration tests for registering for an activity (FR-2, FR-3, FR-6).

They drive the real `activities` controller with Flask's test client against the
test database: a volunteer registers (row, audit entry, one notification per
admin), the details page changes state, duplicates / full / closed activities are
refused with a message and no new row, admins get 403, and a cancelled
registration is re-used instead of inserting a second row.
"""

from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from app.dao import RegistrationDAO, UserDAO
from app.database import DatabaseManager
from app.models import (
    Activity,
    ActivityStatus,
    Person,
    Registration,
    RegistrationStatus,
    Volunteer,
)
from tests.integration.test_admin_manage_flow import in_fresh_browser
from tests.integration.test_auth_flow import ADMIN_PASSWORD, count, log_in, make_admin
from tests.integration.test_browse_flow import (
    logged_in_volunteer,
    make_activity,
    make_location,
    make_volunteer,
    page_text,
    register,
)


# ----------------------------------------------------------------- helpers
def setup_activity(db: DatabaseManager, **overrides: object) -> tuple[Person, Activity]:
    admin = make_admin(db)
    location = make_location(db)
    activity = make_activity(db, admin, location, "Mangrove Planting", **overrides)  # type: ignore[arg-type]
    return admin, activity


def current_volunteer(db: DatabaseManager) -> Volunteer:
    user = UserDAO(db).find_by_username("vol_one")
    assert isinstance(user, Volunteer)
    return user


def post_register(client: FlaskClient, activity: Activity) -> TestResponse:
    return client.post(f"/activities/{activity.id}/register")


def no_register_form(page: str, activity: Activity) -> bool:
    """True when the page has no Register form (the sidebar's logout button is also a submit)."""
    return f'action="/activities/{activity.id}/register"' not in page


def registrations_for(db: DatabaseManager, activity: Activity) -> int:
    return count(
        db, "SELECT COUNT(*) AS n FROM registrations WHERE activity_id = %s", (activity.id,)
    )


# ------------------------------------------------------------------- tests
def test_volunteer_registers_creates_row_audit_and_admin_notifications(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin, activity = setup_activity(clean_db, max_volunteers=5)
    second_admin = make_volunteer(clean_db, "admin_two")  # a second user to prove targeting
    logged_in_volunteer(client)
    volunteer = current_volunteer(clean_db)

    before = page_text(client, f"/activities/{activity.id}")
    assert "5 of 5 slots left" in before
    assert 'name="csrf_token"' in before and ">Register</button>" in before

    response = post_register(client, activity)
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/activities/{activity.id}")

    row = RegistrationDAO(clean_db).find_by_activity_and_user(activity.id or 0, volunteer.id or 0)
    assert row is not None and row.status == RegistrationStatus.PENDING

    assert (
        count(
            clean_db,
            "SELECT COUNT(*) AS n FROM audit_logs WHERE action = 'REGISTRATION_CREATED' "
            "AND entity = 'registration' AND record_reference = %s AND user_id = %s",
            (row.id, volunteer.id),
        )
        == 1
    )
    # Exactly one notification, to the admin; the other volunteer gets nothing.
    assert (
        count(clean_db, "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s", (admin.id,))
        == 1
    )
    assert (
        count(
            clean_db,
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s",
            (second_admin.id,),
        )
        == 0
    )

    after = page_text(client, f"/activities/{activity.id}")
    assert "You are registered for Mangrove Planting" in after  # flash
    assert "4 of 5 slots left" in after  # one slot taken by the PENDING row
    assert "You are registered" in after and "Pending" in after
    assert ">Register</button>" not in after


def test_registering_twice_is_refused_and_keeps_one_row(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    _, activity = setup_activity(clean_db)
    logged_in_volunteer(client)

    assert post_register(client, activity).status_code == 302
    response = post_register(
        client,
        activity,
    )
    assert response.status_code == 302
    assert registrations_for(clean_db, activity) == 1
    page = page_text(client, f"/activities/{activity.id}")
    assert "You are already registered for this activity." in page
    assert (
        count(
            clean_db, "SELECT COUNT(*) AS n FROM audit_logs WHERE action = 'REGISTRATION_CREATED'"
        )
        == 1
    )


def test_full_activity_is_refused(client: FlaskClient, clean_db: DatabaseManager) -> None:
    admin, activity = setup_activity(clean_db, max_volunteers=1)
    other = make_volunteer(clean_db, "other")
    register(clean_db, activity, other, RegistrationStatus.APPROVED)
    logged_in_volunteer(client)

    page = page_text(client, f"/activities/{activity.id}")
    assert "Full" in page and "This activity is full." in page and no_register_form(page, activity)

    assert post_register(client, activity).status_code == 302
    assert registrations_for(clean_db, activity) == 1
    assert "This activity is full." in page_text(client, f"/activities/{activity.id}")
    assert count(clean_db, "SELECT COUNT(*) AS n FROM notifications") == 0


def test_closed_activity_is_refused(client: FlaskClient, clean_db: DatabaseManager) -> None:
    _, activity = setup_activity(clean_db, status=ActivityStatus.CLOSED)
    logged_in_volunteer(client)

    page = page_text(client, f"/activities/{activity.id}")
    assert "Registration is closed." in page and no_register_form(page, activity)

    assert post_register(client, activity).status_code == 302
    assert registrations_for(clean_db, activity) == 0
    assert "This activity is not open for registration." in page_text(
        client, f"/activities/{activity.id}"
    )


def test_admin_gets_403_and_no_register_button(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    _, activity = setup_activity(clean_db)
    log_in(client, "admin1", ADMIN_PASSWORD)

    page = page_text(client, f"/activities/{activity.id}")
    assert "Administrators cannot register for activities." in page
    assert no_register_form(page, activity)

    assert post_register(client, activity).status_code == 403
    assert registrations_for(clean_db, activity) == 0


def test_unknown_activity_shows_404_page(client: FlaskClient, clean_db: DatabaseManager) -> None:
    logged_in_volunteer(client)
    response = client.post("/activities/9999/register")
    assert response.status_code == 404


def test_cancelled_registration_is_reused_not_duplicated(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    _, activity = setup_activity(clean_db)
    logged_in_volunteer(client)
    volunteer = current_volunteer(clean_db)
    dao = RegistrationDAO(clean_db)

    assert post_register(client, activity).status_code == 302
    first = dao.find_by_activity_and_user(activity.id or 0, volunteer.id or 0)
    assert first is not None
    dao.set_status(first.id or 0, RegistrationStatus.CANCELLED)  # Phase 7 does this via the UI

    page = page_text(client, f"/activities/{activity.id}")
    assert "Register again" in page

    assert post_register(client, activity).status_code == 302
    second = dao.find_by_activity_and_user(activity.id or 0, volunteer.id or 0)
    assert second is not None
    assert second.id == first.id  # same row re-used
    assert second.status == RegistrationStatus.PENDING
    assert registrations_for(clean_db, activity) == 1
    assert (
        count(
            clean_db, "SELECT COUNT(*) AS n FROM audit_logs WHERE action = 'REGISTRATION_CREATED'"
        )
        == 2
    )


def test_rejected_registration_cannot_register_again(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    _, activity = setup_activity(clean_db)
    logged_in_volunteer(client)
    volunteer = current_volunteer(clean_db)
    RegistrationDAO(clean_db).insert(
        Registration(
            activity_id=activity.id or 0,
            user_id=volunteer.id or 0,
            status=RegistrationStatus.REJECTED,
        )
    )

    page = page_text(client, f"/activities/{activity.id}")
    assert "Your registration" in page and "Rejected" in page and no_register_form(page, activity)

    assert post_register(client, activity).status_code == 302
    assert "You cannot register for this activity again." in page_text(
        client, f"/activities/{activity.id}"
    )
    assert registrations_for(clean_db, activity) == 1


def test_two_volunteers_and_the_last_slot(
    app: Flask, client: FlaskClient, clean_db: DatabaseManager
) -> None:
    """Sequential version of the race: the second volunteer sees the slot gone."""
    _, activity = setup_activity(clean_db, max_volunteers=1)
    logged_in_volunteer(client)  # vol_one
    make_volunteer(clean_db, "vol_two")

    assert post_register(client, activity).status_code == 302

    def second_browser(browser: FlaskClient) -> TestResponse:
        from tests.integration.test_auth_flow import VOL_PASSWORD

        log_in(browser, "vol_two", VOL_PASSWORD)
        response = browser.post(f"/activities/{activity.id}/register", follow_redirects=True)
        return response

    response = in_fresh_browser(app, second_browser)
    assert response.status_code == 200
    assert "This activity is full." in response.get_data(as_text=True)
    assert registrations_for(clean_db, activity) == 1
