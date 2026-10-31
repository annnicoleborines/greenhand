"""Admin locations controller: the places that host activities (Controller in MVC).

Thin by design: read the request, call LocationService, pick a template or
redirect. Every route is ADMIN-only (`role_required`), and the service checks the
role again (FR-2). One template (`admin/locations/form.html`) serves both the
New and the Edit page; the controller only changes the title and the action URL.
"""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user

from app.auth.roles import role_required
from app.errors import ConflictError, ValidationError
from app.models import Location, RoleName
from app.services.location_service import LocationService

admin_locations_bp = Blueprint("admin_locations", __name__, url_prefix="/admin/locations")


def _form_from(location: Location) -> dict[str, str]:
    """Turn the model into the string values an HTML form shows (None becomes "")."""
    return {
        "location_name": location.location_name,
        "address": location.address,
        "details": location.details or "",
    }


@admin_locations_bp.get("/")
@role_required(RoleName.ADMIN)
def list_locations() -> ResponseReturnValue:
    locations = LocationService.build().list_all(current_user)
    return render_template("admin/locations/list.html", locations=locations)


@admin_locations_bp.route("/new", methods=["GET", "POST"])
@role_required(RoleName.ADMIN)
def new_location() -> ResponseReturnValue:
    if request.method == "GET":
        return render_template("admin/locations/form.html", form={}, errors={}, location=None)

    form = request.form.to_dict()
    try:
        location = LocationService.build().create(current_user, form)
    except (ValidationError, ConflictError) as err:
        flash(err.message, "error")
        page = render_template(
            "admin/locations/form.html", form=form, errors=err.errors, location=None
        )
        return page, 200

    flash(f"Location {location.location_name} has been added.", "success")
    return redirect(url_for("admin_locations.list_locations"))


@admin_locations_bp.route("/<int:location_id>/edit", methods=["GET", "POST"])
@role_required(RoleName.ADMIN)
def edit_location(location_id: int) -> ResponseReturnValue:
    service = LocationService.build()
    location = service.get(current_user, location_id)  # 404 page when it does not exist
    if request.method == "GET":
        return render_template(
            "admin/locations/form.html", form=_form_from(location), errors={}, location=location
        )

    form = request.form.to_dict()
    try:
        location = service.update(current_user, location_id, form)
    except (ValidationError, ConflictError) as err:
        flash(err.message, "error")
        page = render_template(
            "admin/locations/form.html", form=form, errors=err.errors, location=location
        )
        return page, 200

    flash(f"Location {location.location_name} has been updated.", "success")
    return redirect(url_for("admin_locations.list_locations"))


@admin_locations_bp.post("/<int:location_id>/delete")
@role_required(RoleName.ADMIN)
def delete_location(location_id: int) -> ResponseReturnValue:
    try:
        location = LocationService.build().delete(current_user, location_id)
    except ConflictError as err:
        flash(err.message, "error")  # the location still has activities
        return redirect(url_for("admin_locations.list_locations"))
    flash(f"Location {location.location_name} has been deleted.", "success")
    return redirect(url_for("admin_locations.list_locations"))
