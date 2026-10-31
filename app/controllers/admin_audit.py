"""Admin audit-log controller: the FR-6 trail, with filters and pagination.

Thin by design (Controller in MVC): turn the query string into AuditFilterSchema,
ask AuditService for one page, render. ADMIN-only on the route and in the service.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request
from flask.typing import ResponseReturnValue
from flask_login import current_user

from app.auth.roles import role_required
from app.models import RoleName
from app.schemas.report import AuditFilterSchema
from app.services.audit_service import AuditService

admin_audit_bp = Blueprint("admin_audit", __name__, url_prefix="/admin/audit-logs")


@admin_audit_bp.get("/")
@role_required(RoleName.ADMIN)
def list_logs() -> ResponseReturnValue:
    service = AuditService.build()
    filters = AuditFilterSchema.from_query(request.args)
    page = service.list_page(current_user, filters)
    return render_template(
        "admin/audit_logs.html",
        page=page,
        filters=filters,
        action_choices=[
            (code, code.replace("_", " ").capitalize()) for code in service.actions(current_user)
        ],
    )
