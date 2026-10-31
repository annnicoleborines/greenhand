"""Integration tests for My Registrations, My Schedule and Notifications (FR-2, FR-3, FR-6).

They drive the real `registrations` and `notifications` controllers with Flask's
test client against the test database: tabs, cancel (row, admin notifications,
audit, slot freed, register again re-uses the row), the cancel refusals, the
schedule split, the notifications inbox with mark-as-read and the unread badge.
"""

from __future__ import annotations

import re

from flask.testing import FlaskClient

from app.dao import ActivityDAO, NotificationDAO, RegistrationDAO, UserDAO
from app.database import DatabaseManager
from app.models import Activity, Notification, Person, Registration, RegistrationStatus, Volunteer
from tests.integration.test_admin_manage_flow import visible_text
from tests.integration.test_auth_flow import ADMIN_PASSWORD, count, log_in, make_admin
from tests.integration.test_browse_flow import (
    logged_in_volunteer,
    make_activity,
    make_location,
    make_volunteer,
    page_text,
    register,
)

LIST_URL = "/registrations"
SCHEDULE_URL = "/registrations/schedule"
INBOX_URL = "/notifications"


# ----------------------------------------------------------------- helpers
def current_volunteer(db: DatabaseManager) -> Volunteer:
    user = UserDAO(db).find_by_username("vol_one")
    assert isinstance(user, Volunteer)
    return user


def row_for(db: DatabaseManager, activity: Activity, user: Person) -> Registration:
    row = RegistrationDAO(db).find_by_activity_and_user(activity.id or 0, user.id or 0)
    assert row is not None
    return row


def setup(
    client: FlaskClient, db: DatabaseManager
) -> tuple[Person, Volunteer, Activity, Activity, Activity]:
    """An admin, the logged-in volunteer vol_one and three activities (future, past, other)."""
    admin = make_admin(db)
    location = make_location(db)
    future = make_activity(db, admin, location, "Future Drive", in_days=7, max_volunteers=3)
    past = make_activity(db, admin, location, "Past Drive", in_days=-7)
    other = make_activity(db, admin, location, "Other Drive", in_days=14)
    logged_in_volunteer(client)
    return admin, current_volunteer(db), future, past, other


# ------------------------------------------------------------------- tabs
def test_admin_gets_403_on_volunteer_pages(client: FlaskClient, clean_db: DatabaseManager) -> None:
    make_admin(clean_db)
    log_in(client, "admin1", ADMIN_PASSWORD)
    assert client.get(LIST_URL).status_code == 403
    assert client.get(SCHEDULE_URL).status_code == 403
    assert client.post(f"{LIST_URL}/1/cancel").status_code == 403
    assert client.get(INBOX_URL).status_code == 200  # admins do have an inbox


def test_list_shows_own_rows_with_tabs_and_counts(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    _, me, future, past, other = setup(client, clean_db)
    register(clean_db, future, me, RegistrationStatus.PENDING)
    register(clean_db, past, me, RegistrationStatus.APPROVED)
    register(clean_db, other, make_volunteer(clean_db, "someone"), RegistrationStatus.PENDING)

    page = page_text(client, LIST_URL)
    text = visible_text(page)
    assert "Future Drive" in page and "Past Drive" in page and "Other Drive" not in page
    assert "All 2" in text and "Pending 1" in text and "Approved 1" in text and "Rejected 0" in text
    assert (
        f'action="{LIST_URL}/{row_for(clean_db, future, me).id}/cancel' in page
    )  # future: can cancel
    assert f'action="{LIST_URL}/{row_for(clean_db, past, me).id}/cancel' not in page  # past: cannot
    assert 'aria-current="page"' in page  # sidebar "My Registrations" highlighted

    pending_only = page_text(client, f"{LIST_URL}?status=PENDING")
    assert "Future Drive" in pending_only and "Past Drive" not in pending_only
    assert "No rejected registrations." in page_text(client, f"{LIST_URL}?status=REJECTED")


def test_empty_list_points_to_browse(client: FlaskClient, clean_db: DatabaseManager) -> None:
    setup(client, clean_db)
    page = page_text(client, LIST_URL)
    assert "You have not registered for any activity yet." in page
    assert 'href="/activities"' in page


# ----------------------------------------------------------------- cancel
def test_cancel_frees_the_slot_notifies_admins_audits_and_allows_register_again(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin, me, future, _, _ = setup(client, clean_db)
    second_admin = make_admin_two(clean_db)
    bystander = make_volunteer(clean_db, "bystander")
    register(clean_db, future, me, RegistrationStatus.APPROVED)
    row = row_for(clean_db, future, me)
    assert ActivityDAO(clean_db).find_by_id(future.id or 0).taken_slots == 1  # type: ignore[union-attr]

    response = client.post(f"{LIST_URL}/{row.id}/cancel?status=APPROVED")
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"{LIST_URL}?status=APPROVED")

    fresh = RegistrationDAO(clean_db).find_by_id(row.id or 0)
    assert fresh is not None and fresh.status == RegistrationStatus.CANCELLED
    assert ActivityDAO(clean_db).find_by_id(future.id or 0).taken_slots == 0  # type: ignore[union-attr]
    for admin_id in (admin.id, second_admin.id):
        assert (
            count(
                clean_db,
                "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s "
                "AND type = 'REGISTRATION_CANCELLED' AND message LIKE %s",
                (admin_id, "%approved registration for Future Drive%"),
            )
            == 1
        )
    assert (
        count(
            clean_db, "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s", (bystander.id,)
        )
        == 0
    )
    assert (
        count(
            clean_db,
            "SELECT COUNT(*) AS n FROM audit_logs WHERE action = 'REGISTRATION_CANCELLED' "
            "AND entity = 'registration' AND record_reference = %s AND user_id = %s",
            (row.id, me.id),
        )
        == 1
    )

    page = page_text(client, LIST_URL)
    assert "Your registration for Future Drive has been cancelled." in page
    assert "Register again" in page and f'href="/activities/{future.id}"' in page

    # Registering again re-uses the same row (Phase 5 rule).
    assert client.post(f"/activities/{future.id}/register").status_code == 302
    again = row_for(clean_db, future, me)
    assert again.id == row.id and again.status == RegistrationStatus.PENDING


def test_cancel_refusals(client: FlaskClient, clean_db: DatabaseManager) -> None:
    _, me, future, past, other = setup(client, clean_db)
    register(clean_db, future, me, RegistrationStatus.REJECTED)
    register(clean_db, past, me, RegistrationStatus.APPROVED)
    stranger = make_volunteer(clean_db, "stranger")
    register(clean_db, other, stranger, RegistrationStatus.PENDING)

    rejected = row_for(clean_db, future, me)
    assert client.post(f"{LIST_URL}/{rejected.id}/cancel").status_code == 302
    assert "can no longer be cancelled; it is REJECTED" in page_text(client, LIST_URL)

    started = row_for(clean_db, past, me)
    assert client.post(f"{LIST_URL}/{started.id}/cancel").status_code == 302
    assert "already started" in page_text(client, LIST_URL)
    assert row_for(clean_db, past, me).status == RegistrationStatus.APPROVED  # unchanged

    theirs = row_for(clean_db, other, stranger)
    assert client.post(f"{LIST_URL}/{theirs.id}/cancel").status_code == 404  # not mine: not found
    assert row_for(clean_db, other, stranger).status == RegistrationStatus.PENDING  # unchanged
    assert count(clean_db, "SELECT COUNT(*) AS n FROM notifications") == 0


# --------------------------------------------------------------- schedule
def test_schedule_splits_upcoming_and_history(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    _, me, future, past, other = setup(client, clean_db)
    register(clean_db, future, me, RegistrationStatus.APPROVED)  # 4 hours, upcoming
    register(clean_db, past, me, RegistrationStatus.APPROVED)  # 4 hours, history
    register(clean_db, other, me, RegistrationStatus.REJECTED)  # never shown

    page = page_text(client, SCHEDULE_URL)
    text = visible_text(page)
    assert "Upcoming 1" in text and "Completed 1" in text and "Hours volunteered 4.0" in text
    upcoming_section = page[page.index("Upcoming</h2>") : page.index("History</h2>")]
    history_section = page[page.index("History</h2>") :]
    assert "Future Drive" in upcoming_section and "Past Drive" not in upcoming_section
    assert "Past Drive" in history_section and "Future Drive" not in history_section
    assert "Other Drive" not in page
    assert 'href="/registrations"' in page  # "Manage registrations"


# ---------------------------------------------------------- notifications
def test_inbox_lists_own_messages_and_marks_them_read(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin, me, *_ = setup(client, clean_db)
    dao = NotificationDAO(clean_db)
    mine_1 = Notification(
        user_id=me.id or 0, type="REGISTRATION_APPROVED", message="Approved for Future Drive"
    )
    mine_2 = Notification(
        user_id=me.id or 0, type="ACTIVITY_CANCELLED", message="Other Drive was cancelled"
    )
    theirs = Notification(
        user_id=admin.id or 0, type="REGISTRATION_SUBMITTED", message="Admin only message"
    )
    for note in (mine_1, mine_2, theirs):
        dao.insert(note)

    dashboard = page_text(client, "/volunteer/dashboard")
    assert f'href="{INBOX_URL}"' in dashboard  # the header bell
    assert re.search(r">\s*2\s*<", dashboard)  # the unread badge

    page = page_text(client, INBOX_URL)
    assert "2 unread" in page and "Mark all as read" in page
    assert "Approved for Future Drive" in page and "Other Drive was cancelled" in page
    assert "Admin only message" not in page
    assert "Activity cancelled" in page  # the type label
    assert page.count('name="csrf_token"') >= 3  # two row forms + mark-all

    # One message
    assert client.post(f"{INBOX_URL}/{mine_1.id}/read").status_code == 302
    assert dao.unread_count(me.id or 0) == 1
    page = page_text(client, INBOX_URL)
    assert "1 unread" in page
    # Someone else's message: 404, still unread
    assert client.post(f"{INBOX_URL}/{theirs.id}/read").status_code == 404
    assert dao.unread_count(admin.id or 0) == 1
    # Everything
    assert client.post(f"{INBOX_URL}/read-all").status_code == 302
    assert dao.unread_count(me.id or 0) == 0
    page = page_text(client, INBOX_URL)
    assert "All caught up" in page and "1 notification marked as read." in page
    assert "Mark all as read" not in page


def test_admin_inbox_receives_registration_events(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    admin, me, future, *_ = setup(client, clean_db)
    assert (
        client.post(f"/activities/{future.id}/register").status_code == 302
    )  # Phase 5 notifies admins

    client.post("/logout")
    log_in(client, "admin1", ADMIN_PASSWORD)
    page = page_text(client, INBOX_URL)
    assert "New registration" in page and "registered for Future Drive" in page
    assert "1 unread" in page


def make_admin_two(db: DatabaseManager) -> Person:
    """A second administrator, to prove every admin is notified."""
    from app.auth.passwords import hash_password
    from app.dao import RoleDAO
    from app.models import Admin, RoleName

    role = RoleDAO(db).find_by_name(RoleName.ADMIN)
    second = Admin(
        role_id=role.id or 0,
        role_name=RoleName.ADMIN,
        username="admin2",
        email="admin2@example.com",
        password_hash=hash_password(ADMIN_PASSWORD),
        first_name="Bea",
        last_name="Admin",
    )
    UserDAO(db).insert(second)
    return second
