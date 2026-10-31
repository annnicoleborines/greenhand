"""The Template Method: BaseReport.generate() always runs the three steps in order."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.reports.base_report import BaseReport, ReportContext, ReportResult


class SpyReport(BaseReport):
    title = "Spy"

    def __init__(self, context: ReportContext) -> None:
        super().__init__(context)
        self.steps: list[str] = []

    def fetch_data(self) -> list[dict[str, Any]]:
        self.steps.append("fetch")
        return [{"n": 1}, {"n": 2}]

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        self.steps.append("summarize")
        return {"total": sum(r["n"] for r in rows)}

    def format(self, rows: list[dict[str, Any]], summary: dict[str, Any]) -> ReportResult:
        self.steps.append("format")
        return ReportResult(title=self.title, columns=["n"], rows=rows, summary=summary)


def test_generate_runs_steps_in_fixed_order() -> None:
    report = SpyReport(ReportContext(None, None, None))  # type: ignore[arg-type]
    result = report.generate()
    assert report.steps == ["fetch", "summarize", "format"]
    assert result.summary == {"total": 3}
    assert not result.is_empty


def test_base_report_cannot_be_used_without_the_steps() -> None:
    with pytest.raises(TypeError):
        BaseReport(ReportContext(None, None, None))  # type: ignore[abstract, arg-type]


def test_empty_result_flag() -> None:
    assert ReportResult(title="t", columns=[]).is_empty
