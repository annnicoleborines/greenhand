"""Profile controller: a volunteer views and edits their own profile (Controller in MVC).

Thin by design: read the request, call ProfileService, pick a template. Every
route is VOLUNTEER-only; admins have no profile and get a 403 page (FR-2). The
one exception is `photo_file`, which serves a stored avatar to any logged-in
user, because photos live outside the public static folder.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask.typing import ResponseReturnValue
from flask_login import current_user

from app.auth.roles import role_required
from app.errors import ValidationError
from app.models import RoleName, Volunteer
from app.services.profile_service import ProfileService

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")


def _service() -> ProfileService:
    # Tests point UPLOAD_FOLDER at a temporary directory, so read it from the app config.
    return ProfileService.build(upload_folder=current_app.config["UPLOAD_FOLDER"])


def _form_from(user: Volunteer) -> dict[str, str]:
    """Turn the model into the string values an HTML form shows (None becomes "")."""
    profile = user.profile
    return {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone or "",
        "address": (profile.address if profile else None) or "",
        "birth_date": profile.birth_date.isoformat() if profile and profile.birth_date else "",
        "emergency_contact_name": (profile.emergency_contact_name if profile else None) or "",
        "emergency_contact_phone": (profile.emergency_contact_phone if profile else None) or "",
    }


@profile_bp.get("/")
@role_required(RoleName.VOLUNTEER)
def view() -> ResponseReturnValue:
    user = _service().get_profile(current_user)
    return render_template("volunteer/profile.html", user=user)


@profile_bp.route("/edit", methods=["GET", "POST"])
@role_required(RoleName.VOLUNTEER)
def edit() -> ResponseReturnValue:
    service = _service()
    if request.method == "GET":
        user = service.get_profile(current_user)
        return render_template("volunteer/profile_edit.html", form=_form_from(user), errors={})

    form = request.form.to_dict()
    try:
        service.update_profile(current_user, form)
    except ValidationError as err:
        flash(err.message, "error")
        return render_template("volunteer/profile_edit.html", form=form, errors=err.errors), 200

    flash("Your profile has been updated.", "success")
    return redirect(url_for("profile.view"))


@profile_bp.route("/password", methods=["GET", "POST"])
@role_required(RoleName.VOLUNTEER)
def password() -> ResponseReturnValue:
    if request.method == "GET":
        return render_template("volunteer/change_password.html", form={}, errors={})

    form = request.form.to_dict()
    try:
        _service().change_password(current_user, form)
    except ValidationError as err:
        flash(err.message, "error")
        # Passwords are never echoed back, so the form is re-rendered empty.
        return render_template("volunteer/change_password.html", form={}, errors=err.errors), 200

    flash("Your password has been changed.", "success")
    return redirect(url_for("profile.view"))


@profile_bp.post("/photo")
@role_required(RoleName.VOLUNTEER)
def photo() -> ResponseReturnValue:
    upload = request.files.get("photo")
    if upload is None or not upload.filename:
        flash("Please choose a file.", "error")
        return redirect(url_for("profile.view"))

    try:
        _service().update_photo(current_user, upload)
    except ValidationError as err:
        flash(err.errors.get("photo", err.message), "error")
        return redirect(url_for("profile.view"))

    flash("Your photo has been updated.", "success")
    return redirect(url_for("profile.view"))


@profile_bp.get("/photo/<path:filename>")
@role_required(RoleName.VOLUNTEER, RoleName.ADMIN)  # any logged-in user, never anonymous
def photo_file(filename: str) -> ResponseReturnValue:
    # `filename` is the stored users.photo_path, e.g. "avatars/user_5.png".
    # send_from_directory refuses paths that escape UPLOAD_FOLDER and 404s on a miss.
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)
