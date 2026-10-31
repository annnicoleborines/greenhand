from __future__ import annotations

from typing import Any

from app.dao.base_dao import BaseDAO
from app.models import Notification


class NotificationDAO(BaseDAO):
    """SQL for the notifications table."""

    def to_model(self, row: dict[str, Any]) -> Notification:
        return Notification(
            id=row["id"],
            user_id=row["user_id"],
            type=row["type"],
            message=row["message"],
            is_read=self.to_bool(row["is_read"]),
            created_at=row["created_at"],
        )

    def insert(self, notification: Notification) -> int:
        new_id = self.db.execute(
            "INSERT INTO notifications (user_id, type, message) VALUES (%s, %s, %s)",
            (notification.user_id, notification.type, notification.message),
        )
        notification.id = new_id
        return new_id

    def insert_many(self, user_ids: list[int], type_: str, message: str) -> int:
        """Send the same message to several users (for example, all admins)."""
        count = 0
        for user_id in user_ids:
            self.insert(Notification(user_id=user_id, type=type_, message=message))
            count += 1
        return count

    def list_by_user(self, user_id: int, *, limit: int = 50) -> list[Notification]:
        rows = self.db.fetch_all(
            "SELECT id, user_id, type, message, is_read, created_at FROM notifications "
            "WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT %s",
            (user_id, limit),
        )
        return [self.to_model(r) for r in rows]

    def unread_count(self, user_id: int) -> int:
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s AND is_read = FALSE",
            (user_id,),
        )
        return int(row["n"]) if row else 0

    def mark_read(self, notification_id: int, user_id: int) -> bool:
        """user_id is part of the WHERE so one user can never mark another's message."""
        affected = self.db.execute(
            "UPDATE notifications SET is_read = TRUE WHERE id = %s AND user_id = %s",
            (notification_id, user_id),
        )
        return affected > 0

    def mark_all_read(self, user_id: int) -> int:
        return self.db.execute(
            "UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND is_read = FALSE",
            (user_id,),
        )
