from __future__ import annotations

from dataclasses import dataclass

from app.models.base_entity import BaseEntity


@dataclass(kw_only=True)
class Notification(BaseEntity):
    """notifications table: an in-app message for one user."""

    user_id: int
    type: str
    message: str
    is_read: bool = False
