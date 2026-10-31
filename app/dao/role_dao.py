from __future__ import annotations

from typing import Any

from app.dao.base_dao import BaseDAO
from app.errors import NotFoundError
from app.models import Role, RoleName


class RoleDAO(BaseDAO):
    """SQL for the roles table."""

    @staticmethod
    def _to_model(row: dict[str, Any]) -> Role:
        return Role(id=row["id"], name=RoleName(row["name"]))

    def find_by_name(self, name: RoleName) -> Role:
        row = self.db.fetch_one("SELECT id, name FROM roles WHERE name = %s", (name.value,))
        if row is None:
            raise NotFoundError(f"Role {name.value} is missing. Import database/schema.sql.")
        return self._to_model(row)

    def list_all(self) -> list[Role]:
        rows = self.db.fetch_all("SELECT id, name FROM roles ORDER BY id")
        return [self._to_model(r) for r in rows]
