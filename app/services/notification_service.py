"""NotificationService: in-app messages for any logged-in user.

Phase 1 needed only the unread badge count; Phase 7 adds the notifications page
with mark-as-read. Every write carries the user's id in the WHERE clause (see
NotificationDAO), so one user can never mark another user's message as read.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.dao import NotificationDAO
from app.database import DatabaseManager
from app.errors import NotFoundError
from app.models import Notification, Person

MSG_NOT_FOUND = "Notification not found."
LIST_LIMIT = 50


@dataclass
class NotificationService:
    notifications: NotificationDAO

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> NotificationService:
        return cls(notifications=NotificationDAO(db or DatabaseManager()))

    def unread_count(self, user_id: int) -> int:
        return self.notifications.unread_count(user_id)

    def list_for_user(self, user_id: int) -> list[Notification]:
        return self.notifications.list_by_user(user_id, limit=LIST_LIMIT)

    def mark_read(self, actor: Person, notification_id: int) -> None:
        """Mark one of the actor's own messages as read; someone else's id is a 404."""
        if not self.notifications.mark_read(notification_id, actor.id or 0):
            raise NotFoundError(MSG_NOT_FOUND)

    def mark_all_read(self, actor: Person) -> int:
        """Mark every unread message of the actor as read; returns how many changed."""
        return self.notifications.mark_all_read(actor.id or 0)
