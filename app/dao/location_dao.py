from __future__ import annotations

from typing import Any

from app.dao.base_dao import BaseDAO
from app.models import Location


class LocationDAO(BaseDAO):
    """SQL for the locations table."""

    @staticmethod
    def to_model(row: dict[str, Any]) -> Location:
        return Location(
            id=row["id"],
            location_name=row["location_name"],
            address=row["address"],
            details=row["details"],
        )

    def find_by_id(self, location_id: int) -> Location | None:
        row = self.db.fetch_one(
            "SELECT id, location_name, address, details FROM locations WHERE id = %s",
            (location_id,),
        )
        return self.to_model(row) if row else None

    def find_by_name(self, name: str) -> Location | None:
        row = self.db.fetch_one(
            "SELECT id, location_name, address, details FROM locations WHERE location_name = %s",
            (name,),
        )
        return self.to_model(row) if row else None

    def list_all(self) -> list[Location]:
        rows = self.db.fetch_all(
            "SELECT id, location_name, address, details FROM locations ORDER BY location_name"
        )
        return [self.to_model(r) for r in rows]

    def count_all(self) -> int:
        row = self.db.fetch_one("SELECT COUNT(*) AS n FROM locations")
        return int(row["n"]) if row else 0

    def insert(self, location: Location) -> int:
        new_id = self.db.execute(
            "INSERT INTO locations (location_name, address, details) VALUES (%s, %s, %s)",
            (location.location_name, location.address, location.details),
        )
        location.id = new_id
        return new_id

    def update(self, location: Location) -> bool:
        affected = self.db.execute(
            "UPDATE locations SET location_name = %s, address = %s, details = %s WHERE id = %s",
            (location.location_name, location.address, location.details, location.id),
        )
        return affected > 0

    def delete(self, location_id: int) -> bool:
        affected = self.db.execute("DELETE FROM locations WHERE id = %s", (location_id,))
        return affected > 0

    def activity_count(self, location_id: int) -> int:
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM activities WHERE location_id = %s", (location_id,)
        )
        return int(row["n"]) if row else 0

    def list_with_activity_counts(self) -> list[Location]:
        """Every location with `activity_count` filled in (one query, LEFT JOIN + COUNT).

        LEFT JOIN keeps locations that have no activities yet (their count is 0).
        """
        rows = self.db.fetch_all(
            "SELECT l.id, l.location_name, l.address, l.details, "
            "COUNT(a.id) AS activity_count "
            "FROM locations l LEFT JOIN activities a ON a.location_id = l.id "
            "GROUP BY l.id, l.location_name, l.address, l.details "
            "ORDER BY l.location_name"
        )
        locations = []
        for r in rows:
            location = self.to_model(r)
            location.activity_count = int(r.get("activity_count") or 0)
            locations.append(location)
        return locations
