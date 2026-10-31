"""Admin controller: pages only admins see."""

from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import current_user

from app.auth.roles import role_required
from app.models import RoleName
from app.services.dashboard_service import DashboardService

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.get("/dashboard")
@role_required(RoleName.ADMIN)
def dashboard() -> str:
    overview = DashboardService.build().admin_overview(current_user)
    return render_template("admin/dashboard.html", overview=overview)
