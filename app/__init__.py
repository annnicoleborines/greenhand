"""Flask application factory.

`create_app()` builds and returns a fully configured Flask app. Keeping it in a
function (instead of a global) lets tests create isolated apps with different
settings, and lets `flask --app app run --debug` discover it automatically.

MVC wiring: controllers (app/controllers) are registered here; they call
services, which call DAOs, which use the DatabaseManager singleton.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, Response, flash, g, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user, logout_user
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from app.config import Config
from app.database import DatabaseManager
from app.errors import AppError, DatabaseError
from app.extensions import csrf, limiter, login_manager
from app.logging_config import configure_logging

log = logging.getLogger(__name__)


def create_app(
    config_object: type[Config] | None = None,
    *,
    overrides: dict[str, Any] | None = None,
) -> Flask:
    """Build the app.

    Args:
        config_object: settings class (defaults to `Config`; tests pass `TestConfig`).
        overrides: extra config values applied last (tests use this).
    """
    configure_logging()

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_object or Config)
    if overrides:
        app.config.update(overrides)

    if not app.config.get("SECRET_KEY"):
        msg = "SECRET_KEY is not set. Copy .env.example to .env and set a random value."
        raise RuntimeError(msg)

    # --- database: one DatabaseManager for the whole app (Singleton) ---
    db = DatabaseManager()
    app.extensions["db_manager"] = db

    @app.teardown_appcontext
    def close_db_connection(_exc: BaseException | None) -> None:
        # Give the thread's connection back at the end of every request.
        db.close()

    # --- extensions ---
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to continue."
    login_manager.login_message_category = "warning"

    # --- controllers (blueprints) ---
    from app.auth.loader import register_user_loader
    from app.controllers.activities import activities_bp
    from app.controllers.admin import admin_bp
    from app.controllers.admin_activities import admin_activities_bp
    from app.controllers.admin_audit import admin_audit_bp
    from app.controllers.admin_locations import admin_locations_bp
    from app.controllers.admin_registrations import admin_registrations_bp
    from app.controllers.admin_reports import admin_reports_bp
    from app.controllers.admin_volunteers import admin_volunteers_bp
    from app.controllers.auth import auth_bp
    from app.controllers.main import main_bp
    from app.controllers.notifications import notifications_bp
    from app.controllers.profile import profile_bp
    from app.controllers.registrations import registrations_bp
    from app.controllers.volunteer import volunteer_bp
    from app.navigation import build_nav, nav_icon

    register_user_loader(login_manager)
    blueprints = (
        main_bp,
        auth_bp,
        volunteer_bp,
        profile_bp,
        activities_bp,
        registrations_bp,
        notifications_bp,
        admin_bp,
        admin_activities_bp,
        admin_locations_bp,
        admin_registrations_bp,
        admin_volunteers_bp,
        admin_reports_bp,
        admin_audit_bp,
    )
    for blueprint in blueprints:
        app.register_blueprint(blueprint)
    app.context_processor(build_nav)
    app.jinja_env.globals["nav_icon"] = nav_icon

    # --- FR-1: login is required for every page except these ---
    public_endpoints = {"auth.login", "auth.signup", "main.health", "static"}

    @app.before_request
    def require_login() -> ResponseReturnValue | None:
        endpoint = request.endpoint
        if endpoint is None or endpoint in public_endpoints:
            return None
        if not current_user.is_authenticated:
            unauthorized: Response = login_manager.unauthorized()
            return unauthorized
        if not current_user.is_active:
            # Deactivated while logged in: the next request ends the session.
            logout_user()
            flash("This account is inactive. Please contact an administrator.", "warning")
            return redirect(url_for("auth.login"))
        return None

    register_error_handlers(app)
    log.info("app created", extra={"action": "startup"})
    return app


def register_error_handlers(app: Flask) -> None:
    """Turn typed service errors and HTTP errors into friendly pages (FR-8)."""

    def render_error(code: int, message: str | None) -> tuple[str, int]:
        # The error page extends base.html, which looks at current_user. If MySQL
        # died inside the user loader, Flask-Login cached nothing and every
        # current_user access would hit the database again and fail again, so the
        # error page itself would crash. Load the user once here; if that fails,
        # show the page as an anonymous visitor.
        try:
            _ = current_user.is_authenticated
        except DatabaseError:
            g._login_user = app.login_manager.anonymous_user()  # type: ignore[attr-defined]
        return render_template("errors/error.html", code=code, message=message), code

    @app.errorhandler(AppError)
    def handle_app_error(err: AppError) -> tuple[str, int]:
        if err.status_code >= 500:
            log.error("application error: %s", err.message, extra={"action": "app_error"})
        return render_error(err.status_code, err.message)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(_err: RequestEntityTooLarge) -> tuple[str, int]:
        # Flask stops requests above MAX_CONTENT_LENGTH before the view runs; the
        # default text talks about "the server", which does not help the user.
        max_mb = app.config["MAX_PHOTO_BYTES"] // (1024 * 1024)
        return render_error(413, f"The file is too large (max {max_mb} MB).")

    @app.errorhandler(HTTPException)
    def handle_http_error(err: HTTPException) -> tuple[str, int]:
        code = err.code or 500
        return render_error(code, err.description)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception) -> tuple[str, int]:
        log.exception("unhandled error")
        if app.config.get("TESTING") or app.debug:
            raise err
        return render_error(500, "Something went wrong.")
