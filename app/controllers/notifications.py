"""Notifications controller: the in-app inbox, for volunteers and admins alike.

Thin by design (Controller in MVC): list the logged-in user's messages, mark one
or all of them as read, redirect back. Both roles get notifications (volunteers
about reviews and cancellations, admins about new and cancelled registrations),
so the routes accept either role; the service only touches the actor's own rows.
"""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user

from app.auth.roles import role_required
from app.models import RoleName
from app.services.notification_service import NotificationService

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")

# Short labels for the notification `type` codes written by the services.
TYPE_LABELS = {
    "REGISTRATION_SUBMITTED": "New registration",
    "REGISTRATION_CANCELLED": "Registration cancelled",
    "REGISTRATION_APPROVED": "Approved",
    "REGISTRATION_REJECTED": "Rejected",
    "ACTIVITY_CANCELLED": "Activity cancelled",
    "PASSWORD_RESET": "Password reset",
}


@notifications_bp.get("")  # exactly "/notifications"
@role_required(RoleName.VOLUNTEER, RoleName.ADMIN)
def list_notifications() -> ResponseReturnValue:
    service = NotificationService.build()
    user_id = current_user.id or 0
    return render_template(
        "notifications/list.html",
        notifications=service.list_for_user(user_id),
        unread=service.unread_count(user_id),
        type_labels=TYPE_LABELS,
    )


@notifications_bp.post("/<int:notification_id>/read")
@role_required(RoleName.VOLUNTEER, RoleName.ADMIN)
def mark_read(notification_id: int) -> ResponseReturnValue:
    NotificationService.build().mark_read(current_user, notification_id)  # 404 if not theirs
    return redirect(url_for("notifications.list_notifications"))


@notifications_bp.post("/read-all")
@role_required(RoleName.VOLUNTEER, RoleName.ADMIN)
def mark_all_read() -> ResponseReturnValue:
    changed = NotificationService.build().mark_all_read(current_user)
    if changed:
        flash(f"{changed} notification{'' if changed == 1 else 's'} marked as read.", "success")
    return redirect(url_for("notifications.list_notifications"))
