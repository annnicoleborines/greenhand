"""Password hashing with bcrypt (cost 12).

bcrypt only looks at the first 72 bytes of a password. bcrypt 5.x raises an
error for longer input instead of silently truncating, so the sign-up schema
caps passwords at 72 characters and we also guard here.
"""

from __future__ import annotations

import bcrypt

BCRYPT_ROUNDS = 12
MAX_PASSWORD_BYTES = 72


def hash_password(plain: str) -> str:
    """Return a bcrypt hash (as text) for storing in users.password_hash."""
    raw = plain.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        msg = f"Password must be at most {MAX_PASSWORD_BYTES} bytes."
        raise ValueError(msg)
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain: str, password_hash: str) -> bool:
    """Constant-time comparison of a plain password against a stored hash."""
    raw = plain.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database: treat as no match rather than crash.
        return False
