"""Admin registrations controller: review (approve / reject) volunteer sign-ups.

Thin by design (Controller in MVC): read the request, call
RegistrationReviewService, redirect back to the list. Every route is ADMIN-only
(`role_required`), and the service checks the role again (FR-2). The list keeps
its `?status=` filter (PENDING by default, `all` for everything) and `?page=` in
every row action URL so the admin lands back on the same view afterwards.
"""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user

from app.auth.roles import role_required
from app.errors import ConflictError, ValidationError
from app.models import RegistrationStatus, RoleName
from app.services.review_service import RegistrationReviewService

admin_registrations_bp = Blueprint(
    "admin_registrations", __name__, url_prefix="/admin/registrations"
)

ALL = "all"
STATUS_CHOICES = [(status.value, status.value.capitalize()) for status in RegistrationStatus]


def _status_filter(raw: str | None) -> RegistrationStatus | None:
    """?status=pending -> PENDING (the default); ?status=all -> None (every status)."""
    text = str(raw or "").strip().upper()
    if text == ALL.upper():
        return None
    try:
        return RegistrationStatus(text)
    except ValueError:
        return RegistrationStatus.PENDING


def _back_to_list() -> ResponseReturnValue:
    """Redirect to the list page the admin came from (same filter, same page)."""
    return redirect(
        url_for(
            "admin_registrations.list_registrations",
            status=request.args.get("status") or None,
            page=request.args.get("page", type=int),
        )
    )


@admin_registrations_bp.get("/")
@role_required(RoleName.ADMIN)
def list_registrations() -> ResponseReturnValue:
    status = _status_filter(request.args.get("status"))
    page_number = request.args.get("page", 1, type=int)
    page = RegistrationReviewService.build().list_page(current_user, status, page_number)
    return render_template(
        "admin/registrations.html",
        page=page,
        status_filter=status.value if status else ALL,
        status_choices=STATUS_CHOICES,
    )


@admin_registrations_bp.post("/<int:registration_id>/approve")
@role_required(RoleName.ADMIN)
def approve(registration_id: int) -> ResponseReturnValue:
    try:
        registration = RegistrationReviewService.build().approve(current_user, registration_id)
    except ConflictError as err:
        flash(err.message, "error")
        return _back_to_list()
    flash(f"Approved {registration.volunteer_name} for {registration.activity_title}.", "success")
    return _back_to_list()


@admin_registrations_bp.post("/<int:registration_id>/reject")
@role_required(RoleName.ADMIN)
def reject(registration_id: int) -> ResponseReturnValue:
    try:
        registration = RegistrationReviewService.build().reject(
            current_user, registration_id, request.form.to_dict()
        )
    except (ValidationError, ConflictError) as err:
        flash(err.message, "error")
        return _back_to_list()
    flash(f"Rejected {registration.volunteer_name} for {registration.activity_title}.", "success")
    return _back_to_list()
