"""Public pages that do not belong to a role: home and health check (Controller)."""

from __future__ import annotations

from flask import Blueprint, redirect, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user

from app.database import DatabaseManager

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index() -> ResponseReturnValue:
    """Send each user to the right dashboard (login is enforced app-wide)."""
    if current_user.is_admin:
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("volunteer.dashboard"))


@main_bp.get("/health")
def health() -> dict[str, str]:
    """Used by CI and deployment checks. Raises DatabaseError (503) if MySQL is down."""
    DatabaseManager().ping()
    return {"status": "ok"}
