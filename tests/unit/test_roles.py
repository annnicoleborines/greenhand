"""Unit tests for the role checks (FR-2), without a database.

`require_role()` is a plain function, so it is tested directly.
`role_required()` is a route decorator that needs Flask-Login, so a tiny
throw-away app is built here with a fake user loader.
"""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask
from flask_login import LoginManager, login_user

from app.auth.roles import require_role, role_required
from app.errors import ForbiddenError
from app.models import Admin, RoleName, Volunteer


def make_user(role: RoleName) -> Admin | Volunteer:
    fields: dict[str, Any] = {
        "id": 1 if role == RoleName.ADMIN else 2,
        "role_id": 2 if role == RoleName.ADMIN else 1,
        "role_name": role,
        "username": role.value.lower(),
        "email": f"{role.value.lower()}@example.com",
        "first_name": "Test",
        "last_name": role.value.title(),
    }
    return Admin(**fields) if role == RoleName.ADMIN else Volunteer(**fields)


USERS = {str(u.id): u for u in (make_user(RoleName.ADMIN), make_user(RoleName.VOLUNTEER))}


# ---------------------------------------------------------- require_role
def test_require_role_passes_when_actor_has_one_of_the_roles() -> None:
    require_role(make_user(RoleName.ADMIN), RoleName.ADMIN)
    require_role(make_user(RoleName.VOLUNTEER), RoleName.ADMIN, RoleName.VOLUNTEER)


def test_require_role_raises_forbidden_otherwise() -> None:
    with pytest.raises(ForbiddenError) as exc_info:
        require_role(make_user(RoleName.VOLUNTEER), RoleName.ADMIN)
    assert exc_info.value.status_code == 403


# --------------------------------------------------------- role_required
@pytest.fixture
def tiny_app() -> Flask:
    app = Flask(__name__)
    app.config.update(SECRET_KEY="unit-test", TESTING=True)
    manager = LoginManager(app)
    manager.user_loader(lambda user_id: USERS.get(user_id))

    @app.errorhandler(ForbiddenError)
    def forbidden(_err: ForbiddenError) -> tuple[str, int]:
        return "forbidden", 403

    @app.post("/login-as/<role>")
    def login_as(role: str) -> str:
        login_user(make_user(RoleName(role)))
        return "ok"

    @app.get("/admin-only")
    @role_required(RoleName.ADMIN)
    def admin_only() -> str:
        return "admin page"

    return app


def test_role_required_lets_the_right_role_through(tiny_app: Flask) -> None:
    client = tiny_app.test_client()
    client.post("/login-as/ADMIN")
    response = client.get("/admin-only")
    assert response.status_code == 200 and b"admin page" in response.data


def test_role_required_blocks_the_wrong_role_with_403(tiny_app: Flask) -> None:
    client = tiny_app.test_client()
    client.post("/login-as/VOLUNTEER")
    assert client.get("/admin-only").status_code == 403


def test_role_required_sends_anonymous_users_to_log_in(tiny_app: Flask) -> None:
    assert tiny_app.test_client().get("/admin-only").status_code == 401  # no login_view set
