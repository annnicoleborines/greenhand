"""Integration tests for reports and the audit-log viewer (FR-6, FR-7).

They drive the real `admin_reports`, `admin_audit` and `registrations` (own report)
controllers with Flask's test client against the test database: role gates, the
three admin reports with filters, CSV download headers and content, the printable
view, the volunteer's own report (polymorphic generate_report), and the audit-log
list with filters and pagination.
"""

from __future__ import annotations

from datetime import date, timedelta

from flask.testing import FlaskClient

from app.dao import AuditLogDAO
from app.database import DatabaseManager
from app.models import ActivityStatus, AuditLog, RegistrationStatus
from tests.integration.test_admin_manage_flow import visible_text
from tests.integration.test_auth_flow import ADMIN_PASSWORD, VOL_PASSWORD, log_in, make_admin
from tests.integration.test_browse_flow import (
    logged_in_volunteer,
    make_activity,
    make_location,
    make_volunteer,
    page_text,
    register,
)

REPORTS_URL = "/admin/reports/"
AUDIT_URL = "/admin/audit-logs/"


def seed(db: DatabaseManager) -> None:
    """Two activities (one open next week, one completed last month) and three registrations."""
    admin = make_admin(db)
    park = make_location(db)
    riverbank = make_activity(db, admin, park, "Riverbank Drive", in_days=7, max_volunteers=10)
    hillside = make_activity(
        db,
        admin,
        park,
        "Hillside Drive",
        in_days=-30,
        max_volunteers=5,
        status=ActivityStatus.COMPLETED,
    )
    vicky = make_volunteer(db, "vicky")
    bob = make_volunteer(db, "bob")
    register(db, riverbank, vicky, RegistrationStatus.APPROVED)
    register(db, riverbank, bob, RegistrationStatus.PENDING)
    register(db, hillside, bob, RegistrationStatus.COMPLETED)


def logged_in_admin(client: FlaskClient) -> None:
    log_in(client, "admin1", ADMIN_PASSWORD)


# ------------------------------------------------------------------- gates
def test_volunteer_gets_403_on_admin_reports_and_audit_logs(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    logged_in_volunteer(client)
    for url in (
        REPORTS_URL,
        f"{REPORTS_URL}system",
        f"{REPORTS_URL}system.csv",
        f"{REPORTS_URL}system/print",
        AUDIT_URL,
    ):
        assert client.get(url).status_code == 403, url


# ----------------------------------------------------------------- reports
def test_reports_index_lists_the_three_reports(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    make_admin(clean_db)
    logged_in_admin(client)
    page = page_text(client, REPORTS_URL)
    for name, title in (
        ("system", "System Totals"),
        ("activities", "Activity Participation"),
        ("volunteers", "Volunteer Hours"),
    ):
        assert title in page and f'href="{REPORTS_URL}{name}"' in page
    assert 'aria-current="page"' in page  # sidebar "Reports" highlighted
    assert client.get(f"{REPORTS_URL}nope").status_code == 404


def test_system_totals_report_on_screen(client: FlaskClient, clean_db: DatabaseManager) -> None:
    seed(clean_db)
    logged_in_admin(client)
    text = visible_text(page_text(client, f"{REPORTS_URL}system"))
    assert "System Totals" in text
    assert "Total activities 2" in text and "Total volunteers 2" in text
    assert "Registrations APPROVED 1" in text and "Registrations PENDING 1" in text
    assert "Download CSV" in text and "Printable view" in text


def test_activity_participation_report_with_filters(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    seed(clean_db)
    logged_in_admin(client)

    everything = visible_text(page_text(client, f"{REPORTS_URL}activities"))
    assert "Riverbank Drive" in everything and "Hillside Drive" in everything
    assert "Activities 2" in everything and "Total slots 15" in everything
    assert "Approved 1" in everything and "Pending 1" in everything and "Completed 1" in everything

    only_open = visible_text(page_text(client, f"{REPORTS_URL}activities?status=OPEN"))
    assert "Riverbank Drive" in only_open and "Hillside Drive" not in only_open
    assert "20%" in only_open  # 2 of 10 slots taken

    since_today = page_text(
        client, f"{REPORTS_URL}activities?date_from={date.today().isoformat()}&status=bogus"
    )
    assert "Riverbank Drive" in since_today and "Hillside Drive" not in since_today
    assert (
        'href="/admin/reports/activities.csv?date_from=' in since_today
    )  # the CSV link keeps the filters

    none = page_text(client, f"{REPORTS_URL}activities?date_from=2099-01-01")
    assert "No data for this report with these filters." in none


def test_volunteer_hours_report(client: FlaskClient, clean_db: DatabaseManager) -> None:
    seed(clean_db)
    logged_in_admin(client)
    text = visible_text(page_text(client, f"{REPORTS_URL}volunteers"))
    assert "Volunteer Hours" in text
    assert "Volunteers 2" in text and "Registrations 3" in text and "Hours 8" in text  # 4h + 4h
    assert (
        "Vol Bob bob 2 1 0 1 0 0 4" in text
    )  # name, username, total, pending, approved, completed, rejected, cancelled, hours
    assert "Vol Vicky vicky 1 0 1 0 0 0 4" in text


def test_csv_download_has_headers_rows_and_summary(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    seed(clean_db)
    logged_in_admin(client)
    response = client.get(f"{REPORTS_URL}activities.csv?status=OPEN")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert (
        response.headers["Content-Disposition"]
        == f'attachment; filename="activities-{date.today().isoformat()}.csv"'
    )
    body = response.get_data(as_text=True).lstrip("﻿")
    lines = body.split("\r\n")
    assert lines[0] == "Activity,Date,Location,Status,Slots,Pending,Approved,Completed,Fill rate"
    next_week = (date.today() + timedelta(days=7)).isoformat()
    assert lines[1] == f"Riverbank Drive,{next_week},Riverside Park,OPEN,10,1,1,0,20%"
    assert "Summary" in lines and "Activities,1" in lines


def test_printable_view_has_no_navigation(client: FlaskClient, clean_db: DatabaseManager) -> None:
    seed(clean_db)
    logged_in_admin(client)
    page = page_text(client, f"{REPORTS_URL}volunteers/print?date_from=2000-01-01")
    text = visible_text(page)
    assert "Volunteer Hours" in text and "Generated" in text and "Filters: from 2000-01-01" in text
    assert "Vol Bob" in page and 'onclick="window.print()"' in page
    assert 'id="sidebar"' not in page and "Logout" not in page  # plain page for the printer
    assert "print:hidden" in page


def test_volunteer_sees_their_own_report_through_generate_report(
    client: FlaskClient, clean_db: DatabaseManager
) -> None:
    seed(clean_db)
    log_in(client, "bob", VOL_PASSWORD)
    text = visible_text(page_text(client, "/registrations/report"))
    assert "My Volunteer Activity" in text
    assert "Riverbank Drive" in text and "Hillside Drive" in text
    assert (
        "Total registrations 2" in text and "Hours 4" in text
    )  # only the COMPLETED one counts hours
    assert "Vol Vicky" not in text  # nobody else's data

    csv_body = client.get("/registrations/report.csv").get_data(as_text=True).lstrip("﻿")
    assert csv_body.startswith("Activity,Date,Start,End,Status\r\n")
    assert "Hillside Drive" in csv_body and "COMPLETED" in csv_body
    printed = page_text(client, "/registrations/report/print")
    assert "My Volunteer Activity" in printed and 'id="sidebar"' not in printed

    # Admins have their own polymorphic report but not this volunteer route.
    client.post("/logout")
    logged_in_admin(client)
    assert client.get("/registrations/report").status_code == 403


# -------------------------------------------------------------- audit logs
def test_audit_log_viewer_filters_and_pages(client: FlaskClient, clean_db: DatabaseManager) -> None:
    admin = make_admin(clean_db)
    vicky = make_volunteer(clean_db, "vicky")
    dao = AuditLogDAO(clean_db)
    for i in range(27):
        dao.insert(
            AuditLog(
                user_id=admin.id or 0,
                action="ACTIVITY_CREATED",
                entity="activity",
                record_reference=i + 1,
                details=f"Created activity {i + 1}.",
            )
        )
    dao.insert(
        AuditLog(
            user_id=vicky.id or 0,
            action="SIGN_UP",
            entity="user",
            record_reference=vicky.id,
            details="Vicky signed up.",
        )
    )
    logged_in_admin(client)

    first = page_text(client, AUDIT_URL)
    text = visible_text(first)
    assert "28 entries" in text  # 27 created + 1 sign-up (logins are logged, not audited)
    assert "Showing 1-25 of 28 entries" in text and "Page 1 of 2" in text
    assert "Vicky signed up." in first  # newest first
    assert 'aria-current="page"' in first  # sidebar "Audit Logs" highlighted
    assert '<option value="ACTIVITY_CREATED"' in first and '<option value="SIGN_UP"' in first

    second = visible_text(page_text(client, f"{AUDIT_URL}?page=2"))
    assert "Showing 26-28 of 28 entries" in second

    by_action = visible_text(page_text(client, f"{AUDIT_URL}?action=sign_up"))
    assert (
        "1 entry" in by_action
        and "Vicky signed up." in by_action
        and "Created activity" not in by_action
    )

    by_user = visible_text(page_text(client, f"{AUDIT_URL}?username=vic"))
    assert "1 entry" in by_user and "vicky" in by_user

    by_date = visible_text(
        page_text(
            client,
            f"{AUDIT_URL}?date_from={date.today().isoformat()}&date_to={date.today().isoformat()}",
        )
    )
    assert "28 entries" in by_date
    nothing = page_text(client, f"{AUDIT_URL}?date_to=2000-01-01")
    assert "No entries match these filters." in nothing

    clamped = visible_text(page_text(client, f"{AUDIT_URL}?page=99"))
    assert "Showing 26-28 of 28 entries" in clamped  # out of range -> last page
