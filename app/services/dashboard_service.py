"""DashboardService: numbers and lists shown on the two dashboards."""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.roles import require_role
from app.dao import ActivityDAO, RegistrationDAO, UserDAO
from app.database import DatabaseManager
from app.models import Person, Registration, RoleName


@dataclass
class AdminOverview:
    total_activities: int
    total_volunteers: int
    pending_registrations: int
    approved_registrations: int
    recent_registrations: list[Registration]


@dataclass
class DashboardService:
    users: UserDAO
    activities: ActivityDAO
    registrations: RegistrationDAO

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> DashboardService:
        manager = db or DatabaseManager()
        return cls(
            users=UserDAO(manager),
            activities=ActivityDAO(manager),
            registrations=RegistrationDAO(manager),
        )

    def admin_overview(self, actor: Person) -> AdminOverview:
        require_role(actor, RoleName.ADMIN)  # service-level role check (FR-2)
        by_status = self.registrations.count_by_status()
        return AdminOverview(
            total_activities=self.activities.count_all(),
            total_volunteers=self.users.count_by_role(RoleName.VOLUNTEER),
            pending_registrations=by_status.get("PENDING", 0),
            approved_registrations=by_status.get("APPROVED", 0),
            recent_registrations=self.registrations.list_recent(limit=8),
        )
