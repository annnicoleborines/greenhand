"""Admin reports built on the Template Method (BaseReport.generate(): fetch -> summarize -> format).

ActivityParticipationReport: one row per activity in the date range / status, with how
many slots are pending, approved and completed and how full the activity is.
VolunteerHoursReport: one row per volunteer with their registrations by status and the
hours of the activities they were approved for or completed.

The reports read through the DAOs only (ReportContext); the SQL lives in the DAOs.
"""

from __future__ import annotations

from typing import Any

from app.models.enums import RegistrationStatus
from app.schemas.report import ReportFilterSchema
from app.services.reports.base_report import BaseReport, ReportContext, ReportResult
from app.services.reports.person_reports import HOURS_COUNTING_STATUSES, _hours


class ActivityParticipationReport(BaseReport):
    title = "Activity Participation"

    def __init__(self, context: ReportContext, filters: ReportFilterSchema) -> None:
        super().__init__(context)
        self.filters = filters

    def fetch_data(self) -> list[dict[str, Any]]:
        return self.context.activity_dao.report_rows(
            date_from=self.filters.date_from,
            date_to=self.filters.date_to,
            status=self.filters.status,
        )

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        capacity = sum(int(r["max_volunteers"]) for r in rows)
        approved = sum(int(r["approved"]) for r in rows)
        pending = sum(int(r["pending"]) for r in rows)
        completed = sum(int(r["completed"]) for r in rows)
        taken = approved + pending
        return {
            "Activities": len(rows),
            "Total slots": capacity,
            "Pending": pending,
            "Approved": approved,
            "Completed": completed,
            "Fill rate": f"{round(100 * taken / capacity) if capacity else 0}%",
        }

    def format(self, rows: list[dict[str, Any]], summary: dict[str, Any]) -> ReportResult:
        table = []
        for r in rows:
            taken = int(r["pending"]) + int(r["approved"])
            capacity = int(r["max_volunteers"])
            table.append(
                {
                    "Activity": r["title"],
                    "Date": r["activity_date"],
                    "Location": r["location_name"],
                    "Status": r["status"],
                    "Slots": capacity,
                    "Pending": int(r["pending"]),
                    "Approved": int(r["approved"]),
                    "Completed": int(r["completed"]),
                    "Fill rate": f"{round(100 * taken / capacity) if capacity else 0}%",
                }
            )
        return ReportResult(
            title=self.title,
            columns=[
                "Activity",
                "Date",
                "Location",
                "Status",
                "Slots",
                "Pending",
                "Approved",
                "Completed",
                "Fill rate",
            ],
            rows=table,
            summary=summary,
        )


class VolunteerHoursReport(BaseReport):
    title = "Volunteer Hours"

    def __init__(self, context: ReportContext, filters: ReportFilterSchema) -> None:
        super().__init__(context)
        self.filters = filters

    def fetch_data(self) -> list[dict[str, Any]]:
        # One flat row per registration (volunteer + activity + status); grouping happens here,
        # in Python, so the summary and the table are computed from the same rows.
        return self.context.registration_dao.report_rows(
            date_from=self.filters.date_from, date_to=self.filters.date_to
        )

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        per_volunteer: dict[int, dict[str, Any]] = {}
        for r in rows:
            entry = per_volunteer.setdefault(
                int(r["user_id"]),
                {
                    "Volunteer": r["volunteer_name"],
                    "Username": r["username"],
                    "Registrations": 0,
                    **{status.value.capitalize(): 0 for status in RegistrationStatus},
                    "Hours": 0.0,
                },
            )
            entry["Registrations"] += 1
            entry[str(r["status"]).capitalize()] += 1
            if r["status"] in HOURS_COUNTING_STATUSES:
                entry["Hours"] = round(entry["Hours"] + _hours(r["start_time"], r["end_time"]), 2)
        volunteers = sorted(per_volunteer.values(), key=lambda e: (-e["Hours"], e["Volunteer"]))
        return {
            "Volunteers": len(volunteers),
            "Registrations": len(rows),
            "Approved": sum(v["Approved"] for v in volunteers),
            "Completed": sum(v["Completed"] for v in volunteers),
            "Hours": round(sum(v["Hours"] for v in volunteers), 2),
            "_by_volunteer": volunteers,  # consumed by format(), not shown as a total
        }

    def format(self, rows: list[dict[str, Any]], summary: dict[str, Any]) -> ReportResult:
        volunteers = summary.pop("_by_volunteer")
        return ReportResult(
            title=self.title,
            columns=[
                "Volunteer",
                "Username",
                "Registrations",
                "Pending",
                "Approved",
                "Completed",
                "Rejected",
                "Cancelled",
                "Hours",
            ],
            rows=volunteers,
            summary=summary,
        )
