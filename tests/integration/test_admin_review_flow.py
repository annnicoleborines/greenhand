"""Integration tests for the admin review of registrations (FR-2, FR-3, FR-4, FR-6).

They drive the real `admin_registrations` controller with Flask's test client
against the test database: role gate, pending list with filter and pagination,
approve (reviewed_by / reviewed_at, volunteer notification, audit), reject with
and without remarks, double review refused, and what the volunteer then sees on
the details page.
"""

from __future__ import annotations

import re
from datetime import datetime

from flask.testing import FlaskClient

from app.dao import RegistrationDAO
from app.database import DatabaseManager
from app.models import Activity, ActivityStatus, Person, Registration, RegistrationStatus
from tests.integration.test_admin_manage_flow import visible_text
from tests.integration.test_auth_flow import ADMIN_PASSWORD, VOL_PASSWORD, count, log_in, make_admin
from tests.integration.test_browse_flow import (
    make_activity,
    make_location,
    make_volunteer,
    page_text,
    register,
)

LIST_URL = "/admin/registrations/"


# ----------------------------------------------------------------- helpers
def logged_in_admin(client: FlaskClient, db: DatabaseManager) -> Person:
    admin = make_admin(db)
    log_in(client, "admin1", ADMIN_PASSWORD)
    return admin


def pending_registration(
    db: DatabaseManager, admin: Person, *, max_volunteers: int = 10, username: str = "vicky"
) -> tuple[Activity, Person, Registration]:
    location = make_location(db)
    activity = make_activity(
        db, admin, location, "Mangrove Planting", max_volunteers=max_volunteers
    )
    volunteer = make_volunteer(db, username)
    register(db, activity, volunteer, RegistrationStatus.PENDING)
    row = RegistrationDAO(db).find_by_activity_and_user(activity.id or 0, volunteer.id or 0)
    assert row is not None
    return activity, volunteer, row


def reload(db: DatabaseManager, row: Registration) -> Registration:
    fresh = RegistrationDAO(db).find_by_id(row.id or 0)
    assert fresh is not None
    return fresh


# ------------------------------------------------------------------- tests
def test_volunteer_gets_403_on_every_review_route(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = make_admin(clean_db)
    _, _, row = pending_registration(clean_db, admin, username="vol_one")
    log_in(client, "vol_one", VOL_PASSWORD)

    assert client.get(LIST_URL).status_code == 403
    assert client.post(f"{LIST_URL}{row.id}/approve").status_code == 403
    assert client.post(f"{LIST_URL}{row.id}/reject", data={"remarks": "nope"}).status_code == 403
    assert reload(clean_db, row).status == RegistrationStatus.PENDING


def test_pending_list_shows_the_request_with_actions(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    activity, volunteer, row = pending_registration(clean_db, admin)

    page = page_text(client, LIST_URL)
    assert "1 pending registration" in page
    assert volunteer.full_name in page and "Mangrove Planting" in page
    assert f'href="/activities/{activity.id}"' in page
    assert f"{LIST_URL}{row.id}/approve" in page and f"{LIST_URL}{row.id}/reject" in page
    assert 'name="remarks"' in page
    assert 'aria-current="page"' in page  # sidebar "Registrations" is highlighted


def test_approve_sets_review_fields_notifies_volunteer_and_audits(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    _, volunteer, row = pending_registration(clean_db, admin)
    before = datetime.now().replace(microsecond=0)

    response = client.post(f"{LIST_URL}{row.id}/approve?status=PENDING&page=1")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/registrations/?status=PENDING&page=1")

    fresh = reload(clean_db, row)
    assert fresh.status == RegistrationStatus.APPROVED
    assert fresh.reviewed_by == admin.id
    assert fresh.reviewed_at is not None and fresh.reviewed_at >= before
    assert fresh.remarks is None

    assert (
        count(
            clean_db,
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s "
            "AND type = 'REGISTRATION_APPROVED' AND message LIKE %s",
            (volunteer.id, "%Mangrove Planting%approved%"),
        )
        == 1
    )
    assert (
        count(
            clean_db,
            "SELECT COUNT(*) AS n FROM audit_logs WHERE action = 'REGISTRATION_APPROVED' "
            "AND entity = 'registration' AND record_reference = %s AND user_id = %s",
            (row.id, admin.id),
        )
        == 1
    )

    page = page_text(client, LIST_URL)
    assert f"Approved {volunteer.full_name} for Mangrove Planting." in page
    assert "No pending registrations." in page  # the default view is empty again
    approved_page = page_text(client, f"{LIST_URL}?status=APPROVED")
    assert volunteer.full_name in approved_page and "No actions" in approved_page


def test_reject_requires_remarks_then_stores_them(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    _, volunteer, row = pending_registration(clean_db, admin)

    # Without remarks: refused, nothing changes.
    assert client.post(f"{LIST_URL}{row.id}/reject", data={"remarks": "  "}).status_code == 302
    page = page_text(client, LIST_URL)
    assert "Remarks are required to reject" in page
    assert reload(clean_db, row).status == RegistrationStatus.PENDING
    assert count(clean_db, "SELECT COUNT(*) AS n FROM notifications") == 0

    # With remarks: rejected, volunteer told why, audited.
    assert (
        client.post(f"{LIST_URL}{row.id}/reject", data={"remarks": "Age limit is 18."}).status_code
        == 302
    )
    fresh = reload(clean_db, row)
    assert fresh.status == RegistrationStatus.REJECTED
    assert fresh.remarks == "Age limit is 18." and fresh.reviewed_by == admin.id
    assert (
        count(
            clean_db,
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s "
            "AND type = 'REGISTRATION_REJECTED' AND message LIKE %s",
            (volunteer.id, "%Age limit is 18.%"),
        )
        == 1
    )
    assert (
        count(
            clean_db, "SELECT COUNT(*) AS n FROM audit_logs WHERE action = 'REGISTRATION_REJECTED'"
        )
        == 1
    )
    rejected_page = page_text(client, f"{LIST_URL}?status=REJECTED")
    assert "Age limit is 18." in rejected_page


def test_reviewing_twice_is_refused(client: FlaskClient, clean_db: DatabaseManager) -> None:
    admin = logged_in_admin(client, clean_db)
    _, _, row = pending_registration(clean_db, admin)

    assert client.post(f"{LIST_URL}{row.id}/approve").status_code == 302
    assert (
        client.post(f"{LIST_URL}{row.id}/reject", data={"remarks": "Changed my mind"}).status_code
        == 302
    )
    page = page_text(client, LIST_URL)
    assert "already APPROVED" in page
    assert reload(clean_db, row).status == RegistrationStatus.APPROVED
    assert count(clean_db, "SELECT COUNT(*) AS n FROM notifications") == 1  # only the approval


def test_approve_is_refused_when_approved_slots_are_full(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    activity, _, row = pending_registration(clean_db, admin, max_volunteers=1)
    # Capacity 1 and someone else is already approved (data changed outside the normal flow).
    other = make_volunteer(clean_db, "other")
    register(clean_db, activity, other, RegistrationStatus.APPROVED)

    assert client.post(f"{LIST_URL}{row.id}/approve").status_code == 302
    assert "Every slot of this activity is already approved." in page_text(client, LIST_URL)
    assert reload(clean_db, row).status == RegistrationStatus.PENDING


def test_approve_is_refused_for_a_cancelled_activity(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    location = make_location(clean_db)
    activity = make_activity(
        clean_db, admin, location, "Cancelled Drive", status=ActivityStatus.CANCELLED
    )
    volunteer = make_volunteer(clean_db, "vicky")
    register(clean_db, activity, volunteer, RegistrationStatus.PENDING)
    row = RegistrationDAO(clean_db).find_by_activity_and_user(activity.id or 0, volunteer.id or 0)
    assert row is not None

    assert client.post(f"{LIST_URL}{row.id}/approve").status_code == 302
    assert "This activity is CANCELLED" in page_text(client, LIST_URL)
    # Rejecting is still allowed, so the admin can close the request with a reason.
    assert (
        client.post(
            f"{LIST_URL}{row.id}/reject", data={"remarks": "Activity cancelled."}
        ).status_code
        == 302
    )
    assert reload(clean_db, row).status == RegistrationStatus.REJECTED


def test_unknown_registration_shows_404_page(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_admin(client, clean_db)
    assert client.post(f"{LIST_URL}9999/approve").status_code == 404


def test_filter_and_pagination(client: FlaskClient, clean_db: DatabaseManager) -> None:
    admin = logged_in_admin(client, clean_db)
    location = make_location(clean_db)
    activity = make_activity(clean_db, admin, location, "Big Drive", max_volunteers=50)
    for i in range(22):
        register(
            clean_db, activity, make_volunteer(clean_db, f"vol{i:02d}"), RegistrationStatus.PENDING
        )
    register(clean_db, activity, make_volunteer(clean_db, "done"), RegistrationStatus.APPROVED)

    first = page_text(client, LIST_URL)
    assert "22 pending registrations" in first
    assert "Showing 1-20 of 22 registrations" in visible_text(first) and "Page 1 of 2" in first
    next_link = re.search(r'href="([^"]*)"[^>]*rel="next"', first)
    assert next_link is not None
    assert "page=2" in next_link.group(1) and "status=PENDING" in next_link.group(1)
    assert "Vol Vol00" in first and "Vol Vol21" not in first  # oldest first

    second = page_text(client, f"{LIST_URL}?status=PENDING&page=2")
    assert "Showing 21-22 of 22 registrations" in visible_text(second) and "Vol Vol21" in second

    everything = page_text(client, f"{LIST_URL}?status=all")
    assert "23 registrations" in everything

    assert "1 approved registration" in page_text(client, f"{LIST_URL}?status=APPROVED")
    assert "22 pending registrations" in page_text(client, f"{LIST_URL}?status=bogus")  # falls back


def test_dashboard_links_to_the_review_pages(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    _, _, row = pending_registration(clean_db, admin)

    page = page_text(client, "/admin/dashboard")
    assert 'href="/admin/registrations/?status=PENDING"' in page
    assert f'href="/admin/registrations/?status=PENDING#registration-{row.id}"' in page
    assert 'Review<span class="sr-only"> registration #' in page


def test_volunteer_sees_the_review_result_on_the_details_page(
    app: object, client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin = logged_in_admin(client, clean_db)
    activity, _, row = pending_registration(clean_db, admin, username="vol_one")
    assert (
        client.post(f"{LIST_URL}{row.id}/reject", data={"remarks": "Age limit is 18."}).status_code
        == 302
    )

    client.post("/logout")  # logout is POST-only
    log_in(client, "vol_one", VOL_PASSWORD)
    page = page_text(client, f"/activities/{activity.id}")
    assert "Your registration" in page and "Rejected" in page and "Age limit is 18." in page
    assert f'action="/activities/{activity.id}/register"' not in page
