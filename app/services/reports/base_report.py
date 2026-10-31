"""BaseReport: Template Method pattern.

`generate()` is the template: it always runs the same three steps in the same
order. Subclasses never override `generate()`; they fill in the steps:

    fetch_data()  -> get raw rows through the DAOs
    summarize()   -> compute totals from those rows
    format()      -> build the ReportResult that the view/CSV/print page shows
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.dao.activity_dao import ActivityDAO
    from app.dao.registration_dao import RegistrationDAO
    from app.dao.user_dao import UserDAO


@dataclass
class ReportContext:
    """The DAOs a report may read from. Reports never run SQL themselves."""

    user_dao: UserDAO
    activity_dao: ActivityDAO
    registration_dao: RegistrationDAO


@dataclass
class ReportResult:
    """What every report produces: a title, table columns + rows, and summary totals."""

    title: str
    columns: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.rows


class BaseReport(ABC):
    """Abstract report. Subclasses implement the three steps."""

    title: str = "Report"

    def __init__(self, context: ReportContext) -> None:
        self.context = context

    def generate(self) -> ReportResult:
        """The template method: fixed order, steps supplied by subclasses."""
        rows = self.fetch_data()
        summary = self.summarize(rows)
        return self.format(rows, summary)

    @abstractmethod
    def fetch_data(self) -> list[dict[str, Any]]:
        """Step 1: read raw rows from the DAOs."""

    @abstractmethod
    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Step 2: compute totals from the rows."""

    @abstractmethod
    def format(self, rows: list[dict[str, Any]], summary: dict[str, Any]) -> ReportResult:
        """Step 3: shape the final result for display or export."""
