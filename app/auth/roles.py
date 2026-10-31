"""Role checks on the server, in two places (FR-2):

1. `role_required(...)`: a decorator for controller routes.
2. `require_role(...)`: a plain function services call, so business rules are
   protected even if a route forgot the decorator.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from flask import Response, current_app
from flask_login import current_user

from app.errors import ForbiddenError
from app.models import Person, RoleName

P = ParamSpec("P")
R = TypeVar("R")


def require_role(actor: Person, *roles: RoleName) -> None:
    """Service-level check. Raises ForbiddenError when the actor lacks the role."""
    if actor.role_name not in roles:
        msg = "You do not have permission to do this."
        raise ForbiddenError(msg)


def role_required(*roles: RoleName) -> Callable[[Callable[P, R]], Callable[P, R | Response]]:
    """Route decorator: must be logged in AND have one of the given roles."""

    def decorator(view: Callable[P, R]) -> Callable[P, R | Response]:
        @wraps(view)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | Response:
            if not current_user.is_authenticated:
                unauthorized: Response = current_app.login_manager.unauthorized()  # type: ignore[attr-defined]
                return unauthorized
            require_role(current_user, *roles)
            return view(*args, **kwargs)

        return wrapper

    return decorator
