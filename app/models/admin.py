from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models.person import Person

if TYPE_CHECKING:
    from app.services.reports.base_report import ReportContext, ReportResult


@dataclass(kw_only=True)
class Admin(Person):
    """A Person with the ADMIN role. Admins have no volunteer profile."""

    def generate_report(self, context: ReportContext) -> ReportResult:
        """Report on system-wide totals."""
        from app.services.reports.person_reports import SystemTotalsReport

        return SystemTotalsReport(context).generate()
