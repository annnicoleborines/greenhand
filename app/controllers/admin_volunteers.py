"""Admin volunteers controller: list, search, (de)activate and reset passwords.

Thin by design (Controller in MVC): read the request, call AdminUserService, pick
a template or redirect. Every route is ADMIN-only (`role_required`), and the
service checks the role again (FR-2). The row actions are small POST forms; the
search text and page number travel in the form's action URL so the admin lands
back on the same page of the list.
"""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user

from app.auth.roles import role_required
from app.errors import ConflictError
from app.models import RoleName
from app.services.admin_user_service import AdminUserService

admin_volunteers_bp = Blueprint("admin_volunteers", __name__, url_prefix="/admin/volunteers")


def _back_to_list() -> ResponseReturnValue:
    """Redirect to the list page the admin came from (same search, same page)."""
    return redirect(
        url_for(
            "admin_volunteers.list_volunteers",
            q=request.args.get("q") or None,
            page=request.args.get("page", type=int),
        )
    )


@admin_volunteers_bp.get("/")
@role_required(RoleName.ADMIN)
def list_volunteers() -> ResponseReturnValue:
    search = request.args.get("q", "").strip()
    page_number = request.args.get("page", 1, type=int)
    page = AdminUserService.build().list_volunteers_page(current_user, search, page_number)
    return render_template("admin/volunteers.html", page=page, search=search)


@admin_volunteers_bp.post("/<int:user_id>/deactivate")
@role_required(RoleName.ADMIN)
def deactivate(user_id: int) -> ResponseReturnValue:
    try:
        user = AdminUserService.build().set_active(current_user, user_id, False)
    except ConflictError as err:
        flash(err.message, "error")
        return _back_to_list()
    flash(f"{user.full_name} ({user.username}) has been deactivated.", "success")
    return _back_to_list()


@admin_volunteers_bp.post("/<int:user_id>/activate")
@role_required(RoleName.ADMIN)
def activate(user_id: int) -> ResponseReturnValue:
    try:
        user = AdminUserService.build().set_active(current_user, user_id, True)
    except ConflictError as err:
        flash(err.message, "error")
        return _back_to_list()
    flash(f"{user.full_name} ({user.username}) has been activated.", "success")
    return _back_to_list()


@admin_volunteers_bp.post("/<int:user_id>/reset-password")
@role_required(RoleName.ADMIN)
def reset_password(user_id: int) -> ResponseReturnValue:
    service = AdminUserService.build()
    try:
        user = service.get(current_user, user_id)
        temporary = service.reset_password(current_user, user_id)
    except ConflictError as err:
        flash(err.message, "error")
        return _back_to_list()
    # Shown exactly once, to the admin who pressed the button; it is stored nowhere else.
    flash(f"Temporary password for {user.username}: {temporary}", "warning")
    flash("Give it to the volunteer and ask them to change it after logging in.", "info")
    return _back_to_list()
