"""AuditService: the audit-log viewer for administrators (FR-6, read side).

ADMIN-only (`require_role`). Filters come from AuditFilterSchema (action code,
username, date range) and are passed to AuditLogDAO.search() / count_search(),
which share one WHERE builder so the page and its total never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.roles import require_role
from app.dao import AuditLogDAO
from app.database import DatabaseManager
from app.models import AuditLog, Person, RoleName
from app.schemas.report import AuditFilterSchema
from app.services.pagination import Page, clamp_page, offset_for

DEFAULT_PER_PAGE = 25


@dataclass
class AuditService:
    audit: AuditLogDAO

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> AuditService:
        return cls(audit=AuditLogDAO(db or DatabaseManager()))

    def list_page(
        self, actor: Person, filters: AuditFilterSchema, per_page: int = DEFAULT_PER_PAGE
    ) -> Page[AuditLog]:
        require_role(actor, RoleName.ADMIN)
        total = self.audit.count_search(
            action=filters.action,
            username=filters.username,
            date_from=filters.date_from,
            date_to=filters.date_to,
        )
        last_page = Page[AuditLog](per_page=per_page, total=total).pages
        page = min(clamp_page(filters.page), last_page)
        items = self.audit.search(
            action=filters.action,
            username=filters.username,
            date_from=filters.date_from,
            date_to=filters.date_to,
            limit=per_page,
            offset=offset_for(page, per_page),
        )
        return Page(items=items, page=page, per_page=per_page, total=total)

    def actions(self, actor: Person) -> list[str]:
        """Every distinct action code ever written, for the filter drop-down."""
        require_role(actor, RoleName.ADMIN)
        return self.audit.list_actions()
