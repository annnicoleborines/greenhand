from __future__ import annotations

from dataclasses import dataclass

from app.models.base_entity import BaseEntity
from app.models.enums import RoleName


@dataclass(kw_only=True)
class Role(BaseEntity):
    """roles table: VOLUNTEER or ADMIN."""

    name: RoleName
