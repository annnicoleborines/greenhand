"""Volunteer controller: pages only volunteers see."""

from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import current_user

from app.auth.roles import role_required
from app.models import RoleName
from app.services.browse_service import BrowseService

volunteer_bp = Blueprint("volunteer", __name__, url_prefix="/volunteer")


@volunteer_bp.get("/dashboard")
@role_required(RoleName.VOLUNTEER)
def dashboard() -> str:
    # The "Upcoming activities" box: the three soonest OPEN activities (Phase 4).
    upcoming = BrowseService.build().upcoming(current_user)
    return render_template("volunteer/dashboard.html", user=current_user, upcoming=upcoming)
