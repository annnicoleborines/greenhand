"""Admin activities controller: create, edit, cancel/delete and re-status activities.

Thin by design (Controller in MVC): read the request, call ActivityService, pick a
template or redirect. Every route is ADMIN-only (`role_required`), and the service
checks the role again (FR-2). The list keeps its `?status=` filter and `?page=`
in every row action URL so the admin lands back on the same view afterwards.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user

from app.auth.roles import role_required
from app.errors import ConflictError, ValidationError
from app.models import Activity, ActivityStatus, RoleName
from app.services.activity_service import ActivityService
from app.services.location_service import LocationService

admin_activities_bp = Blueprint("admin_activities", __name__, url_prefix="/admin/activities")

STATUS_CHOICES = [(status.value, status.value.capitalize()) for status in ActivityStatus]


def _status_filter(raw: str | None) -> ActivityStatus | None:
    """Turn ?status=open into ActivityStatus.OPEN; anything unknown or blank means all."""
    try:
        return ActivityStatus(str(raw or "").strip().upper())
    except ValueError:
        return None


def _back_to_list() -> ResponseReturnValue:
    """Redirect to the list page the admin came from (same filter, same page)."""
    return redirect(
        url_for(
            "admin_activities.list_activities",
            status=request.args.get("status") or None,
            page=request.args.get("page", type=int),
        )
    )


def _form_from(activity: Activity) -> dict[str, str]:
    """Turn the model into the string values an HTML form shows (None becomes "")."""
    return {
        "title": activity.title,
        "description": activity.description or "",
        "location_id": str(activity.location_id),
        "activity_date": activity.activity_date.isoformat(),
        "start_time": activity.start_time.strftime("%H:%M"),
        "end_time": activity.end_time.strftime("%H:%M"),
        "max_volunteers": str(activity.max_volunteers),
        "requirements": activity.requirements or "",
    }


def _render_form(form: dict[str, Any], errors: dict[str, str], activity: Activity | None) -> str:
    """The shared New / Edit page; the location drop-down is filled from the database."""
    locations = LocationService.build().list_all(current_user)
    choices = [(str(location.id), location.location_name) for location in locations]
    return render_template(
        "admin/activities/form.html",
        form=form,
        errors=errors,
        activity=activity,
        location_choices=choices,
    )


@admin_activities_bp.get("/")
@role_required(RoleName.ADMIN)
def list_activities() -> ResponseReturnValue:
    status = _status_filter(request.args.get("status"))
    page_number = request.args.get("page", 1, type=int)
    page = ActivityService.build().list_page(current_user, status, page_number)
    return render_template(
        "admin/activities/list.html",
        page=page,
        status_filter=status.value if status else "",
        status_choices=STATUS_CHOICES,
    )


@admin_activities_bp.route("/new", methods=["GET", "POST"])
@role_required(RoleName.ADMIN)
def new_activity() -> ResponseReturnValue:
    if request.method == "GET":
        return _render_form({}, {}, None)

    form = request.form.to_dict()
    try:
        activity = ActivityService.build().create(current_user, form)
    except (ValidationError, ConflictError) as err:
        flash(err.message, "error")
        return _render_form(form, err.errors, None), 200

    flash(f"Activity {activity.title} has been created.", "success")
    return redirect(url_for("admin_activities.list_activities"))


@admin_activities_bp.route("/<int:activity_id>/edit", methods=["GET", "POST"])
@role_required(RoleName.ADMIN)
def edit_activity(activity_id: int) -> ResponseReturnValue:
    service = ActivityService.build()
    activity = service.get(current_user, activity_id)  # 404 page when it does not exist
    if request.method == "GET":
        return _render_form(_form_from(activity), {}, activity)

    form = request.form.to_dict()
    try:
        activity = service.update(current_user, activity_id, form)
    except (ValidationError, ConflictError) as err:
        flash(err.message, "error")
        return _render_form(form, err.errors, activity), 200

    flash(f"Activity {activity.title} has been updated.", "success")
    return redirect(url_for("admin_activities.list_activities"))


@admin_activities_bp.post("/<int:activity_id>/delete")
@role_required(RoleName.ADMIN)
def delete_activity(activity_id: int) -> ResponseReturnValue:
    service = ActivityService.build()
    try:
        activity = service.get(current_user, activity_id)
        outcome = service.delete_or_cancel(current_user, activity_id)
    except ConflictError as err:
        flash(err.message, "error")  # e.g. the activity is already cancelled
        return _back_to_list()

    if outcome == "deleted":
        flash(f"Activity {activity.title} has been deleted.", "success")
    else:
        flash(
            f"Activity {activity.title} has registrations, so it was cancelled instead of "
            "deleted. Registered volunteers have been notified.",
            "warning",
        )
    return _back_to_list()


@admin_activities_bp.post("/<int:activity_id>/status")
@role_required(RoleName.ADMIN)
def change_status(activity_id: int) -> ResponseReturnValue:
    new_status = request.form.get("status", "")
    try:
        activity = ActivityService.build().change_status(current_user, activity_id, new_status)
    except (ValidationError, ConflictError) as err:
        flash(err.message, "error")
        return _back_to_list()

    if activity.status == ActivityStatus.CANCELLED:
        flash(
            f"Activity {activity.title} has been cancelled and registered volunteers notified.",
            "warning",
        )
    else:
        flash(f"Activity {activity.title} is now {activity.status.value}.", "success")
    return _back_to_list()
