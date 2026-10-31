"""Flask extensions created once and attached to the app inside `create_app`.

Creating them at module level (without an app) is the standard pattern for the
app factory: blueprints can import them, and tests can build many apps.
"""

from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])
