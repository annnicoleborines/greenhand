"""Reports returned by Person.generate_report() (polymorphism in action).

Volunteer.generate_report() -> VolunteerActivityReport (own registrations + hours)
Admin.generate_report()     -> SystemTotalsReport     (system-wide totals)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.models.enums import RegistrationStatus, RoleName
from app.services.reports.base_report import BaseReport, ReportContext, ReportResult

if TYPE_CHECKING:
    from app.models.volunteer import Volunteer

HOURS_COUNTING_STATUSES = {RegistrationStatus.APPROVED, RegistrationStatus.COMPLETED}


def _hours(start: Any, end: Any) -> float:
    """Length of an activity in hours. PyMySQL gives TIME columns as timedelta."""
    if isinstance(start, timedelta) and isinstance(end, timedelta):
        return round((end - start).total_seconds() / 3600, 2)
    return round(
        (datetime.combine(date.min, end) - datetime.combine(date.min, start)).total_seconds()
        / 3600,
        2,
    )


class VolunteerActivityReport(BaseReport):
    title = "My Volunteer Activity"

    def __init__(self, context: ReportContext, *, volunteer: Volunteer) -> None:
        super().__init__(context)
        self.volunteer = volunteer

    def fetch_data(self) -> list[dict[str, Any]]:
        if self.volunteer.id is None:
            return []
        return self.context.registration_dao.report_rows_for_user(self.volunteer.id)

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        by_status = {status.value: 0 for status in RegistrationStatus}
        hours = 0.0
        for row in rows:
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1
            if row["status"] in HOURS_COUNTING_STATUSES:
                hours += _hours(row["start_time"], row["end_time"])
        return {"total_registrations": len(rows), "hours": round(hours, 2), **by_status}

    def format(self, rows: list[dict[str, Any]], summary: dict[str, Any]) -> ReportResult:
        return ReportResult(
            title=self.title,
            columns=["Activity", "Date", "Start", "End", "Status"],
            rows=[
                {
                    "Activity": r["activity_title"],
                    "Date": r["activity_date"],
                    "Start": r["start_time"],
                    "End": r["end_time"],
                    "Status": r["status"],
                }
                for r in rows
            ],
            summary=summary,
        )


class SystemTotalsReport(BaseReport):
    title = "System Totals"

    def fetch_data(self) -> list[dict[str, Any]]:
        ctx = self.context
        return [
            {"metric": "Total activities", "value": ctx.activity_dao.count_all()},
            {"metric": "Total volunteers", "value": ctx.user_dao.count_by_role(RoleName.VOLUNTEER)},
            *[
                {"metric": f"Registrations {status}", "value": count}
                for status, count in ctx.registration_dao.count_by_status().items()
            ],
        ]

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {row["metric"]: row["value"] for row in rows}

    def format(self, rows: list[dict[str, Any]], summary: dict[str, Any]) -> ReportResult:
        return ReportResult(
            title=self.title,
            columns=["Metric", "Value"],
            rows=[{"Metric": r["metric"], "Value": r["value"]} for r in rows],
            summary=summary,
        )
