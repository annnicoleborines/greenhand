from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models.person import Person
from app.models.volunteer_profile import VolunteerProfile

if TYPE_CHECKING:
    from app.services.reports.base_report import ReportContext, ReportResult


@dataclass(kw_only=True)
class Volunteer(Person):
    """A Person with the VOLUNTEER role. Has zero or one VolunteerProfile."""

    profile: VolunteerProfile | None = None

    def generate_report(self, context: ReportContext) -> ReportResult:
        """Report on this volunteer's own registrations and hours."""
        from app.services.reports.person_reports import VolunteerActivityReport

        return VolunteerActivityReport(context, volunteer=self).generate()
