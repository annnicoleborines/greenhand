"""Admin reports controller: on-screen reports, CSV export and a printable view (FR-7).

Thin by design (Controller in MVC): read the filters from the URL, ask ReportService
for the ReportResult, hand it to a template or stream it as CSV. Every route is
ADMIN-only (`role_required`), and the service checks the role again (FR-2).
"""

from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, Response, render_template, request
from flask.typing import ResponseReturnValue
from flask_login import current_user

from app.auth.roles import role_required
from app.models import ActivityStatus, RoleName
from app.schemas.report import ReportFilterSchema
from app.services.report_service import ReportService

admin_reports_bp = Blueprint("admin_reports", __name__, url_prefix="/admin/reports")

STATUS_CHOICES = [(status.value, status.value.capitalize()) for status in ActivityStatus]


def csv_response(text: str, filename: str) -> Response:
    """Offer `text` as a CSV download; the BOM lets Excel open UTF-8 correctly."""
    return Response(
        "﻿" + text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin_reports_bp.get("/")
@role_required(RoleName.ADMIN)
def index() -> ResponseReturnValue:
    return render_template(
        "admin/reports/index.html", reports=ReportService.build().catalogue(current_user)
    )


@admin_reports_bp.get("/<name>")
@role_required(RoleName.ADMIN)
def show(name: str) -> ResponseReturnValue:
    service = ReportService.build()
    info = service.info(current_user, name)  # 404 page for an unknown report
    filters = ReportFilterSchema.from_query(request.args)
    result = service.generate(current_user, name, filters)
    return render_template(
        "reports/show.html",
        info=info,
        result=result,
        rows=ReportService.display_rows(result),
        summary=ReportService.summary_items(result),
        filters=filters,
        status_choices=STATUS_CHOICES,
        csv_url_endpoint="admin_reports.download",
        print_url_endpoint="admin_reports.printable",
        url_args={"name": name, **filters.as_query_args()},
        back_url_endpoint="admin_reports.index",
    )


@admin_reports_bp.get("/<name>.csv")
@role_required(RoleName.ADMIN)
def download(name: str) -> ResponseReturnValue:
    service = ReportService.build()
    filters = ReportFilterSchema.from_query(request.args)
    result = service.generate(current_user, name, filters)
    return csv_response(ReportService.to_csv(result), f"{name}-{date.today().isoformat()}.csv")


@admin_reports_bp.get("/<name>/print")
@role_required(RoleName.ADMIN)
def printable(name: str) -> ResponseReturnValue:
    service = ReportService.build()
    filters = ReportFilterSchema.from_query(request.args)
    result = service.generate(current_user, name, filters)
    return render_template(
        "reports/print.html",
        result=result,
        rows=ReportService.display_rows(result),
        summary=ReportService.summary_items(result),
        filters=filters,
        generated_at=datetime.now(),
    )
