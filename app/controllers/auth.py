"""Auth controller: login, logout, sign-up (Controller in MVC: thin, no business rules)."""

from __future__ import annotations

from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_user, logout_user

from app.errors import AppError
from app.extensions import limiter
from app.services.auth_service import AuthService

auth_bp = Blueprint("auth", __name__)


def _safe_next_url(candidate: str | None) -> str | None:
    """Accept only a path on this site: '/x?y' yes; '//evil', '/\\evil', 'http://evil' no."""
    if not candidate or "\\" in candidate:
        return None
    parts = urlsplit(candidate)
    if parts.scheme or parts.netloc or not candidate.startswith("/") or candidate.startswith("//"):
        return None
    return candidate


def _home_for(user: object) -> str:
    """Where a logged-in user lands: admin or volunteer dashboard."""
    is_admin = getattr(user, "is_admin", False)
    return url_for("admin.dashboard") if is_admin else url_for("volunteer.dashboard")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login() -> ResponseReturnValue:
    if current_user.is_authenticated:
        return redirect(_home_for(current_user))
    # Flask-Login adds ?next= on the GET; the form carries it through the POST.
    next_url = _safe_next_url(request.form.get("next") or request.args.get("next"))
    if request.method == "GET":
        return render_template("auth/login.html", next_url=next_url)

    try:
        user = AuthService.build().login(request.form.to_dict())
    except AppError as err:
        flash(err.message, "error")
        page = render_template(
            "auth/login.html", username=request.form.get("username", ""), next_url=next_url
        )
        return page, (err.status_code if err.status_code != 422 else 200)

    login_user(user)
    flash(f"Welcome back, {user.first_name}!", "success")
    return redirect(next_url or _home_for(user))


@auth_bp.post("/logout")
def logout() -> ResponseReturnValue:
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def signup() -> ResponseReturnValue:
    if current_user.is_authenticated:
        return redirect(_home_for(current_user))
    if request.method == "GET":
        return render_template("auth/signup.html", form={}, errors={})

    form = request.form.to_dict()
    try:
        AuthService.build().register_volunteer(form)
    except AppError as err:
        flash(err.message, "error")
        safe_form = {k: v for k, v in form.items() if "password" not in k}
        return render_template("auth/signup.html", form=safe_form, errors=err.errors), 200

    flash("Your account is ready. Please log in.", "success")
    return redirect(url_for("auth.login"))
