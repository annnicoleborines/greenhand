"""Unit tests for the Phase 8 reports: filter schemas, the two admin BaseReport
subclasses, ReportService (catalogue, polymorphic for_person, CSV) and AuditService.

No database: the DAOs are fakes returning canned raw rows, exactly what the
reports' fetch_data() step receives in production.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

import pytest

from app.errors import ForbiddenError, NotFoundError
from app.models import ActivityStatus, Admin, AuditLog, RoleName, Volunteer
from app.schemas.report import AuditFilterSchema, ReportFilterSchema
from app.services.audit_service import AuditService
from app.services.report_service import REPORTS, ReportService, cell_text, summary_label
from app.services.reports.admin_reports import ActivityParticipationReport, VolunteerHoursReport
from app.services.reports.base_report import ReportContext


# ----------------------------------------------------------------- fakes
class FakeActivityDAO:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def report_rows(self, **filters: Any) -> list[dict[str, Any]]:
        self.calls.append(filters)
        return self.rows

    def count_all(self) -> int:
        return 2


class FakeRegistrationDAO:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def report_rows(self, **filters: Any) -> list[dict[str, Any]]:
        self.calls.append(filters)
        return self.rows

    def report_rows_for_user(self, user_id: int) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["user_id"] == user_id]

    def count_by_status(self) -> dict[str, int]:
        return {"PENDING": 1, "APPROVED": 2}


class FakeUserDAO:
    def count_by_role(self, role: RoleName) -> int:
        return 5


class FakeAuditDAO:
    def __init__(self, total: int = 0) -> None:
        self.total = total
        self.search_calls: list[dict[str, Any]] = []

    def count_search(self, **filters: Any) -> int:
        return self.total

    def search(self, **filters: Any) -> list[AuditLog]:
        self.search_calls.append(filters)
        return []

    def list_actions(self) -> list[str]:
        return ["LOGIN", "SIGN_UP"]


def admin() -> Admin:
    return Admin(
        id=1,
        role_id=2,
        role_name=RoleName.ADMIN,
        username="ada",
        email="a@x",
        first_name="A",
        last_name="A",
    )


def volunteer() -> Volunteer:
    return Volunteer(
        id=7,
        role_id=1,
        role_name=RoleName.VOLUNTEER,
        username="vic",
        email="v@x",
        first_name="V",
        last_name="V",
    )


ACTIVITY_ROWS = [
    {
        "id": 1,
        "title": "Riverbank",
        "activity_date": date(2030, 6, 8),
        "start_time": time(8, 0),
        "end_time": time(11, 0),
        "status": "OPEN",
        "max_volunteers": 10,
        "location_name": "Park",
        "pending": 2,
        "approved": 3,
        "completed": 0,
    },
    {
        "id": 2,
        "title": "Hillside",
        "activity_date": date(2030, 6, 9),
        "start_time": time(7, 0),
        "end_time": time(12, 0),
        "status": "COMPLETED",
        "max_volunteers": 5,
        "location_name": "Hill",
        "pending": 0,
        "approved": 0,
        "completed": 5,
    },
]
REGISTRATION_ROWS = [
    {
        "user_id": 7,
        "username": "vic",
        "volunteer_name": "Vicky Vol",
        "status": "APPROVED",
        "activity_title": "Riverbank",
        "activity_date": date(2030, 6, 8),
        "start_time": timedelta(hours=8),
        "end_time": timedelta(hours=11),
    },  # PyMySQL TIME -> timedelta
    {
        "user_id": 7,
        "username": "vic",
        "volunteer_name": "Vicky Vol",
        "status": "REJECTED",
        "activity_title": "Hillside",
        "activity_date": date(2030, 6, 9),
        "start_time": time(7, 0),
        "end_time": time(12, 0),
    },
    {
        "user_id": 8,
        "username": "bob",
        "volunteer_name": "Bob Bee",
        "status": "COMPLETED",
        "activity_title": "Hillside",
        "activity_date": date(2030, 6, 9),
        "start_time": time(7, 0),
        "end_time": time(12, 0),
    },
]


def context(
    activities: list[dict[str, Any]] = ACTIVITY_ROWS,
    registrations: list[dict[str, Any]] = REGISTRATION_ROWS,
) -> ReportContext:
    return ReportContext(
        user_dao=FakeUserDAO(),  # type: ignore[arg-type]
        activity_dao=FakeActivityDAO(activities),  # type: ignore[arg-type]
        registration_dao=FakeRegistrationDAO(registrations),  # type: ignore[arg-type]
    )


# --------------------------------------------------------------- schemas
def test_report_filters_are_tolerant() -> None:
    f = ReportFilterSchema.from_query(
        {"date_from": "2030-06-01", "date_to": "garbage", "status": "open"}
    )
    assert f.date_from == date(2030, 6, 1) and f.date_to is None
    assert f.status == ActivityStatus.OPEN and f.is_filtered
    assert f.as_query_args() == {"date_from": "2030-06-01", "status": "OPEN"}

    backwards = ReportFilterSchema.from_query({"date_from": "2030-06-10", "date_to": "2030-06-01"})
    assert backwards.date_from == date(2030, 6, 10) and backwards.date_to is None

    empty = ReportFilterSchema.from_query({"status": "bogus", "date_from": ""})
    assert not empty.is_filtered and empty.as_query_args() == {}


def test_audit_filters_are_tolerant() -> None:
    f = AuditFilterSchema.from_query({"action": " login ", "username": "ad", "page": "3"})
    assert (f.action, f.username, f.page) == ("LOGIN", "ad", 3)
    assert f.as_query_args() == {"action": "LOGIN", "username": "ad"}  # page is not a filter
    assert AuditFilterSchema.from_query({"page": "abc", "username": "x" * 60}).page == 1
    assert (
        AuditFilterSchema.from_query({"username": "x" * 60}).username is None
    )  # too long: dropped


# --------------------------------------------------------------- reports
def test_activity_participation_report_runs_the_template_method() -> None:
    ctx = context()
    filters = ReportFilterSchema.from_query({"status": "OPEN", "date_from": "2030-06-01"})
    result = ActivityParticipationReport(ctx, filters).generate()

    dao: FakeActivityDAO = ctx.activity_dao  # type: ignore[assignment]
    assert dao.calls == [
        {"date_from": date(2030, 6, 1), "date_to": None, "status": ActivityStatus.OPEN}
    ]
    assert result.title == "Activity Participation"
    assert result.columns[0] == "Activity" and result.columns[-1] == "Fill rate"
    assert result.rows[0]["Activity"] == "Riverbank" and result.rows[0]["Fill rate"] == "50%"
    assert result.rows[1]["Completed"] == 5 and result.rows[1]["Fill rate"] == "0%"
    assert result.summary == {
        "Activities": 2,
        "Total slots": 15,
        "Pending": 2,
        "Approved": 3,
        "Completed": 5,
        "Fill rate": "33%",
    }


def test_activity_participation_report_handles_no_rows() -> None:
    result = ActivityParticipationReport(context(activities=[]), ReportFilterSchema()).generate()
    assert result.is_empty and result.summary["Fill rate"] == "0%"


def test_volunteer_hours_report_groups_by_volunteer_and_counts_hours() -> None:
    result = VolunteerHoursReport(context(), ReportFilterSchema()).generate()
    assert result.columns[:2] == ["Volunteer", "Username"] and result.columns[-1] == "Hours"
    assert [r["Volunteer"] for r in result.rows] == ["Bob Bee", "Vicky Vol"]  # most hours first
    bob, vicky = result.rows
    assert (bob["Registrations"], bob["Completed"], bob["Hours"]) == (1, 1, 5.0)
    assert (vicky["Registrations"], vicky["Approved"], vicky["Rejected"], vicky["Hours"]) == (
        2,
        1,
        1,
        3.0,
    )
    assert result.summary == {
        "Volunteers": 2,
        "Registrations": 3,
        "Approved": 1,
        "Completed": 1,
        "Hours": 8.0,
    }
    assert "_by_volunteer" not in result.summary


# ---------------------------------------------------------------- service
def test_catalogue_and_generate_are_admin_only_and_404_unknown_names() -> None:
    service = ReportService(context())
    assert [info.name for info in service.catalogue(admin())] == [
        "system",
        "activities",
        "volunteers",
    ]
    with pytest.raises(ForbiddenError):
        service.catalogue(volunteer())
    with pytest.raises(NotFoundError):
        service.generate(admin(), "nope", ReportFilterSchema())
    with pytest.raises(ForbiddenError):
        service.generate(volunteer(), "system", ReportFilterSchema())
    system = service.generate(admin(), "system", ReportFilterSchema())
    assert system.title == "System Totals" and system.summary["Total volunteers"] == 5
    assert set(REPORTS) == {"system", "activities", "volunteers"}


def test_for_person_is_polymorphic() -> None:
    service = ReportService(context())
    assert service.for_person(admin()).title == "System Totals"
    mine = service.for_person(volunteer())
    assert mine.title == "My Volunteer Activity"
    assert (
        len(mine.rows) == 2 and mine.summary["hours"] == 3.0
    )  # only Vicky's rows, only APPROVED hours


def test_summary_labels_read_as_words() -> None:
    assert summary_label("total_registrations") == "Total registrations"
    assert summary_label("APPROVED") == "Approved" and summary_label("hours") == "Hours"
    assert summary_label("Fill rate") == "Fill rate"  # already written for people
    mine = ReportService(context()).for_person(volunteer())
    labels = [label for label, _ in ReportService.summary_items(mine)]
    assert labels[:2] == ["Total registrations", "Hours"] and "Approved" in labels


def test_cell_text_formats_every_value_type_the_same_way() -> None:
    assert cell_text(None) == "" and cell_text(True) == "Yes"
    assert cell_text(date(2030, 6, 8)) == "2030-06-08"
    assert (
        cell_text(time(8, 5)) == "08:05" and cell_text(timedelta(hours=11, minutes=30)) == "11:30"
    )
    assert cell_text(3.0) == "3" and cell_text(2.5) == "2.5" and cell_text(7) == "7"


def test_to_csv_has_header_rows_blank_line_and_summary() -> None:
    result = ReportService(context()).generate(admin(), "activities", ReportFilterSchema())
    csv_text = ReportService.to_csv(result)
    lines = csv_text.split("\r\n")
    assert lines[0] == "Activity,Date,Location,Status,Slots,Pending,Approved,Completed,Fill rate"
    assert lines[1] == "Riverbank,2030-06-08,Park,OPEN,10,2,3,0,50%"
    assert lines[3] == "" and lines[4] == "Summary" and lines[5] == "Activities,2"
    assert ReportService.display_rows(result)[1][0] == "Hillside"


# ------------------------------------------------------------------ audit
def test_audit_service_pages_with_filters_and_clamps_to_the_last_page() -> None:
    dao = FakeAuditDAO(total=30)
    service = AuditService(audit=dao)  # type: ignore[arg-type]
    filters = AuditFilterSchema.from_query({"action": "login", "username": "ad", "page": "9"})
    page = service.list_page(admin(), filters)
    assert page.page == 2 and page.pages == 2 and page.total == 30  # ?page=9 -> last page
    assert dao.search_calls == [
        {
            "action": "LOGIN",
            "username": "ad",
            "date_from": None,
            "date_to": None,
            "limit": 25,
            "offset": 25,
        }
    ]
    assert service.actions(admin()) == ["LOGIN", "SIGN_UP"]
    with pytest.raises(ForbiddenError):
        service.list_page(volunteer(), filters)
