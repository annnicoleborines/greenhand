"""ReportService: builds reports (FR-7) for the screen, the CSV download and the print view.

- Admin reports are picked by name from REPORTS, each a BaseReport subclass (Template
  Method); every admin method is ADMIN-only (`require_role`).
- `for_person()` is the polymorphic one: it calls `actor.generate_report()`, so a
  Volunteer gets their own activity report and an Admin the system totals, without
  this service knowing which subclass it is talking to.
- The same `display_rows()` text is used by the HTML table, the CSV and the print
  page, so the three views can never disagree. CSV is produced with the standard
  `csv` module (quoting handled for us) and offered as a download by the controller.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from app.auth.roles import require_role
from app.dao import ActivityDAO, RegistrationDAO, UserDAO
from app.database import DatabaseManager
from app.errors import NotFoundError
from app.models import Person, RoleName
from app.schemas.report import ReportFilterSchema
from app.services.reports.admin_reports import ActivityParticipationReport, VolunteerHoursReport
from app.services.reports.base_report import BaseReport, ReportContext, ReportResult
from app.services.reports.person_reports import SystemTotalsReport

ReportFactory = Callable[[ReportContext, ReportFilterSchema], BaseReport]


@dataclass(frozen=True)
class ReportInfo:
    """Catalogue entry shown on the Reports index page."""

    name: str
    title: str
    description: str
    uses_filters: bool
    factory: ReportFactory


REPORTS: dict[str, ReportInfo] = {
    "system": ReportInfo(
        "system",
        "System Totals",
        "How many activities, volunteers and registrations the system holds, by status.",
        False,
        lambda ctx, _filters: SystemTotalsReport(ctx),
    ),
    "activities": ReportInfo(
        "activities",
        "Activity Participation",
        "Every activity with its pending, approved and completed slots and how full it is.",
        True,
        ActivityParticipationReport,
    ),
    "volunteers": ReportInfo(
        "volunteers",
        "Volunteer Hours",
        "Every volunteer with their registrations by status and the hours they served.",
        True,
        VolunteerHoursReport,
    ),
}
MSG_NOT_FOUND = "Report not found."


def cell_text(value: Any) -> str:
    """One table cell as text, the same for HTML, CSV and print."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, timedelta):  # PyMySQL gives TIME columns as timedelta
        minutes = int(value.total_seconds() // 60)
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def summary_label(label: str) -> str:
    """'total_registrations' -> 'Total registrations', 'APPROVED' -> 'Approved'.

    Labels that already contain a space (the admin reports write them for people)
    are left exactly as they are.
    """
    if " " in label:
        return label
    return label.replace("_", " ").capitalize()


@dataclass
class ReportService:
    context: ReportContext

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> ReportService:
        manager = db or DatabaseManager()
        return cls(
            context=ReportContext(
                user_dao=UserDAO(manager),
                activity_dao=ActivityDAO(manager),
                registration_dao=RegistrationDAO(manager),
            )
        )

    # ------------------------------------------------------------- catalogue
    def catalogue(self, actor: Person) -> list[ReportInfo]:
        require_role(actor, RoleName.ADMIN)
        return list(REPORTS.values())

    def info(self, actor: Person, name: str) -> ReportInfo:
        require_role(actor, RoleName.ADMIN)
        info = REPORTS.get(name)
        if info is None:
            raise NotFoundError(MSG_NOT_FOUND)
        return info

    # --------------------------------------------------------------- generate
    def generate(self, actor: Person, name: str, filters: ReportFilterSchema) -> ReportResult:
        """Run one admin report through the template method."""
        info = self.info(actor, name)
        return info.factory(self.context, filters).generate()

    def for_person(self, actor: Person) -> ReportResult:
        """The actor's own report: Volunteer -> their activity, Admin -> system totals."""
        return actor.generate_report(self.context)

    # ------------------------------------------------------------------ views
    @staticmethod
    def display_rows(result: ReportResult) -> list[list[str]]:
        return [[cell_text(row.get(column)) for column in result.columns] for row in result.rows]

    @staticmethod
    def summary_items(result: ReportResult) -> list[tuple[str, str]]:
        return [(summary_label(label), cell_text(value)) for label, value in result.summary.items()]

    @classmethod
    def to_csv(cls, result: ReportResult) -> str:
        """Header row, data rows, a blank line, then the summary as label,value pairs."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(result.columns)
        writer.writerows(cls.display_rows(result))
        if result.summary:
            writer.writerow([])
            writer.writerow(["Summary"])
            for label, value in cls.summary_items(result):
                writer.writerow([label, value])
        return buffer.getvalue()
