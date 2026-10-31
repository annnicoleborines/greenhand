"""LocationService: admins add, edit and remove the places that host activities.

Rules from the brief:
- Every method is ADMIN-only (`require_role`, checked here as well as on the route).
- A location name is unique; a duplicate gives ConflictError with a field error so
  the form can highlight the name box.
- A location that still has activities cannot be deleted (ConflictError). Admins
  cancel or move the activities first; nothing is ever deleted in a cascade.
- Every create / update / delete writes an audit_logs entry in the same
  transaction (FR-6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.auth.roles import require_role
from app.dao import AuditLogDAO, LocationDAO
from app.database import DatabaseManager
from app.errors import ConflictError, NotFoundError
from app.models import AuditLog, Location, Person, RoleName
from app.schemas.base import validate
from app.schemas.location import LocationSchema

log = logging.getLogger(__name__)

LOCATION_FIELDS = ("location_name", "address", "details")
DUPLICATE_NAME = "A location with that name already exists."


@dataclass
class LocationService:
    db: DatabaseManager
    locations: LocationDAO
    audit: AuditLogDAO

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> LocationService:
        """Convenience constructor used by controllers."""
        manager = db or DatabaseManager()
        return cls(db=manager, locations=LocationDAO(manager), audit=AuditLogDAO(manager))

    # --------------------------------------------------------------- read
    def list_all(self, actor: Person) -> list[Location]:
        """Every location, with `activity_count` filled for the list page."""
        require_role(actor, RoleName.ADMIN)
        return self.locations.list_with_activity_counts()

    def get(self, actor: Person, location_id: int) -> Location:
        require_role(actor, RoleName.ADMIN)
        location = self.locations.find_by_id(location_id)
        if location is None:
            msg = "Location not found."
            raise NotFoundError(msg)
        return location

    # ------------------------------------------------------------- create
    def create(self, actor: Person, form: dict[str, Any]) -> Location:
        """Validate, refuse a duplicate name, then insert the row and its audit entry."""
        require_role(actor, RoleName.ADMIN)
        data = validate(LocationSchema, form)
        self._check_name_is_free(data.location_name)

        location = Location(
            location_name=data.location_name, address=data.address, details=data.details
        )
        with self.db.transaction():
            self.locations.insert(location)
            self._audit(
                actor, "LOCATION_CREATED", location, f"Created location {location.location_name}."
            )
        log.info("location created", extra={"user_id": actor.id, "action": "LOCATION_CREATED"})
        return location

    # ------------------------------------------------------------- update
    def update(self, actor: Person, location_id: int, form: dict[str, Any]) -> Location:
        """Validate, refuse a name another location already uses, then save + audit."""
        require_role(actor, RoleName.ADMIN)
        location = self.get(actor, location_id)
        data = validate(LocationSchema, form)
        self._check_name_is_free(data.location_name, except_id=location.id)

        changed = [f for f in LOCATION_FIELDS if getattr(location, f) != getattr(data, f)]
        if not changed:
            return location  # nothing to save, nothing to audit

        for name in LOCATION_FIELDS:
            setattr(location, name, getattr(data, name))
        with self.db.transaction():
            self.locations.update(location)
            self._audit(actor, "LOCATION_UPDATED", location, "Changed: " + ", ".join(changed) + ".")
        log.info("location updated", extra={"user_id": actor.id, "action": "LOCATION_UPDATED"})
        return location

    # ------------------------------------------------------------- delete
    def delete(self, actor: Person, location_id: int) -> Location:
        """Delete the row, unless activities still point at it (then refuse)."""
        require_role(actor, RoleName.ADMIN)
        location = self.get(actor, location_id)

        in_use = self.locations.activity_count(location_id)
        if in_use > 0:
            msg = (
                f"{location.location_name} cannot be deleted: {in_use} "
                f"{'activity uses' if in_use == 1 else 'activities use'} this location. "
                "Cancel or move them first."
            )
            raise ConflictError(msg)

        with self.db.transaction():
            self.locations.delete(location_id)
            self._audit(
                actor, "LOCATION_DELETED", location, f"Deleted location {location.location_name}."
            )
        log.info("location deleted", extra={"user_id": actor.id, "action": "LOCATION_DELETED"})
        return location

    # ------------------------------------------------------------ helpers
    def _check_name_is_free(self, name: str, *, except_id: int | None = None) -> None:
        """Raise ConflictError when another location already has this name."""
        existing = self.locations.find_by_name(name)
        if existing is not None and existing.id != except_id:
            raise ConflictError(DUPLICATE_NAME, {"location_name": DUPLICATE_NAME})

    def _audit(self, actor: Person, action: str, location: Location, details: str) -> None:
        self.audit.insert(
            AuditLog(
                user_id=actor.id or 0,
                action=action,
                entity="location",
                record_reference=location.id,
                details=details,
            )
        )
