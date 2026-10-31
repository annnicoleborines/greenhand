# ruff: noqa: E501  (inline SVG icon strings are long on purpose)
"""Sidebar navigation built once per request from the user's role (used by base.html).

Links to pages from later phases point at '#' until those pages exist; the
sidebar order and labels follow the design reference (Section 10 of the brief).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask import request, url_for
from flask_login import current_user
from markupsafe import Markup

from app.errors import DatabaseError
from app.models import RoleName
from app.services.notification_service import NotificationService

# Inline SVG icons (Heroicons outline, MIT licence) keep the sidebar dependency-free.
_ICON = {
    "home": '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 12l9-9 9 9M5 10v10a1 1 0 001 1h4v-6h4v6h4a1 1 0 001-1V10"/></svg>',
    "tree": '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3l5 7h-3l4 6h-5v5h-2v-5H6l4-6H7l5-7z"/></svg>',
    "list": '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>',
    "user": '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>',
    "bell": '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 10-12 0v3.2a2 2 0 01-.6 1.4L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/></svg>',
    "pin": '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17.7 13.7L12 19.4l-5.7-5.7a8 8 0 1111.4 0z"/><circle cx="12" cy="11" r="3"/></svg>',
    "users": '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.4-1.8M17 20H7m10 0v-2c0-.7-.1-1.3-.4-1.8M7 20H2v-2a3 3 0 015.4-1.8M7 20v-2c0-.7.1-1.3.4-1.8m0 0a5 5 0 019.2 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>',
    "chart": '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 19V13M15 19V5M21 19H3M3 19v-6"/></svg>',
    "calendar": '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3M4 11h16M5 5h14a1 1 0 011 1v13a1 1 0 01-1 1H5a1 1 0 01-1-1V6a1 1 0 011-1z"/></svg>',
    "log": '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6M7 4h7l5 5v11a2 2 0 01-2 2H7a2 2 0 01-2-2V6a2 2 0 012-2z"/></svg>',
}


@dataclass
class NavItem:
    label: str
    url: str
    icon: str
    active: bool


@dataclass
class Nav:
    """A class (not a dict) so `nav.items` in templates is the list, not dict.items()."""

    items: list[NavItem]
    unread_count: int = 0
    notifications_url: str = "#"


def _item(label: str, icon: str, endpoint: str | None, *, section: str | None = None) -> NavItem:
    """One sidebar link. `section` is a blueprint name: the link also counts as active
    on that blueprint's other pages (e.g. "My Profile" stays highlighted on /profile/edit)."""
    url = url_for(endpoint) if endpoint else "#"
    on_endpoint = (request.endpoint or "") == endpoint
    in_section = section is not None and request.blueprint == section
    active = endpoint is not None and (on_endpoint or in_section)
    return NavItem(label=label, url=url, icon=_ICON[icon], active=active)


def build_nav() -> dict[str, Any]:
    """Context processor: exposes `nav` to every template.

    It must never raise: it also runs while the FR-8 error page is rendered,
    when MySQL may be down. The page then simply gets an empty menu.
    """
    try:
        return {"nav": _nav_for_current_user()}
    except DatabaseError:
        return {"nav": Nav(items=[])}


def _nav_for_current_user() -> Nav:
    if not current_user.is_authenticated:
        return Nav(items=[])

    if current_user.role_name == RoleName.ADMIN:
        items = [
            _item("Dashboard", "home", "admin.dashboard"),
            _item(
                "Manage Activities",
                "tree",
                "admin_activities.list_activities",
                section="admin_activities",
            ),
            _item(
                "Manage Locations",
                "pin",
                "admin_locations.list_locations",
                section="admin_locations",
            ),
            _item(
                "Registrations",
                "list",
                "admin_registrations.list_registrations",
                section="admin_registrations",
            ),
            _item(
                "Volunteers",
                "users",
                "admin_volunteers.list_volunteers",
                section="admin_volunteers",
            ),
            _item("Reports", "chart", "admin_reports.index", section="admin_reports"),
            _item("Audit Logs", "log", "admin_audit.list_logs", section="admin_audit"),
        ]
    else:
        items = [
            _item("Dashboard", "home", "volunteer.dashboard"),
            _item("Activities", "tree", "activities.list_activities", section="activities"),
            _item("My Registrations", "list", "registrations.list_registrations"),
            _item("My Schedule", "calendar", "registrations.schedule"),
            _item("My Profile", "user", "profile.view", section="profile"),
            _item(
                "Notifications",
                "bell",
                "notifications.list_notifications",
                section="notifications",
            ),
        ]
    unread = NotificationService.build().unread_count(int(current_user.get_id()))
    return Nav(
        items=items,
        unread_count=unread,
        notifications_url=url_for("notifications.list_notifications"),
    )


def nav_icon(name: str) -> Markup:
    """Template global: `{{ nav_icon("tree") }}` renders one of the inline SVG icons."""
    return Markup(_ICON[name])
