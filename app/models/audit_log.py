from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.models.base_entity import BaseEntity


@dataclass(kw_only=True)
class AuditLog(BaseEntity):
    """audit_logs table: who did what, to which record, and when (FR-6)."""

    user_id: int
    action: str
    entity: str
    record_reference: int | None = None
    timestamp: datetime | None = None
    details: str | None = None

    username: str | None = field(default=None, compare=False)  # joined for the viewer
