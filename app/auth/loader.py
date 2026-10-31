"""Flask-Login user loader: turns the user id stored in the session cookie into a Person."""

from __future__ import annotations

from flask_login import LoginManager

from app.dao import UserDAO
from app.models import Person


def register_user_loader(manager: LoginManager) -> None:
    def load_user(user_id: str) -> Person | None:
        if not user_id.isdigit():
            return None
        return UserDAO().find_by_id(int(user_id))

    # Registered as a plain call (not a decorator) so mypy keeps the function typed.
    manager.user_loader(load_user)
