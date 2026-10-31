"""Unit tests for LocationService (FR-2 role check, FR-4 validation, FR-6 audit entries).

No database: the DAOs are small in-memory fakes, like tests/unit/test_profile_service.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models import Admin, AuditLog, Location, RoleName, Volunteer
from app.services.location_service import LocationService


# ----------------------------------------------------------------- fakes
class FakeDB:
    def __init__(self) -> None:
        self.transactions = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.transactions += 1
        yield None


class FakeLocationDAO:
    def __init__(self, *locations: Location) -> None:
        self.locations = list(locations)
        self.activity_counts: dict[int, int] = {}
        self.inserted: list[Location] = []
        self.updated: list[Location] = []
        self.deleted: list[int] = []

    def find_by_id(self, location_id: int) -> Location | None:
        return next((loc for loc in self.locations if loc.id == location_id), None)

    def find_by_name(self, name: str) -> Location | None:
        return next((loc for loc in self.locations if loc.location_name == name), None)

    def list_with_activity_counts(self) -> list[Location]:
        for loc in self.locations:
            loc.activity_count = self.activity_counts.get(loc.id or 0, 0)
        return list(self.locations)

    def activity_count(self, location_id: int) -> int:
        return self.activity_counts.get(location_id, 0)

    def insert(self, location: Location) -> int:
        location.id = 100 + len(self.inserted)
        self.inserted.append(location)
        self.locations.append(location)
        return location.id

    def update(self, location: Location) -> bool:
        self.updated.append(location)
        return True

    def delete(self, location_id: int) -> bool:
        self.deleted.append(location_id)
        return True


class FakeAuditDAO:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def insert(self, entry: AuditLog) -> int:
        entry.id = len(self.entries) + 1
        self.entries.append(entry)
        return entry.id


def make_admin() -> Admin:
    return Admin(
        id=1,
        role_id=2,
        role_name=RoleName.ADMIN,
        username="admin",
        email="admin@example.com",
        first_name="Ada",
        last_name="Min",
    )


def make_volunteer() -> Volunteer:
    return Volunteer(
        id=5,
        role_id=1,
        role_name=RoleName.VOLUNTEER,
        username="maria",
        email="maria@example.com",
        first_name="Maria",
        last_name="Santos",
    )


def make_location(**overrides: Any) -> Location:
    fields: dict[str, Any] = {
        "id": 7,
        "location_name": "Riverside Park",
        "address": "12 River Road",
        "details": None,
    }
    fields.update(overrides)
    return Location(**fields)


def make_service(
    *locations: Location,
) -> tuple[LocationService, FakeDB, FakeLocationDAO, FakeAuditDAO]:
    db = FakeDB()
    location_dao = FakeLocationDAO(*locations)
    audit_dao = FakeAuditDAO()
    service = LocationService(
        db=db,  # type: ignore[arg-type]
        locations=location_dao,  # type: ignore[arg-type]
        audit=audit_dao,  # type: ignore[arg-type]
    )
    return service, db, location_dao, audit_dao


def location_form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "location_name": "Riverside Park",
        "address": "12 River Road",
        "details": "",
    }
    form.update(overrides)
    return form


# ------------------------------------------------------------ role check
@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("list_all", ()),
        ("get", (7,)),
        ("create", ({},)),
        ("update", (7, {})),
        ("delete", (7,)),
    ],
)
def test_volunteers_are_refused_before_anything_is_read_or_written(
    method: str, args: tuple[Any, ...]
) -> None:
    service, db, locations, audit = make_service(make_location())
    with pytest.raises(ForbiddenError):
        getattr(service, method)(make_volunteer(), *args)
    assert db.transactions == 0 and audit.entries == []
    assert locations.inserted == [] and locations.updated == [] and locations.deleted == []


# --------------------------------------------------------------- reading
def test_list_all_returns_locations_with_activity_counts() -> None:
    service, _, locations, _ = make_service(make_location(), make_location(id=8, location_name="B"))
    locations.activity_counts = {7: 3}

    result = service.list_all(make_admin())

    assert [(loc.id, loc.activity_count) for loc in result] == [(7, 3), (8, 0)]


def test_get_raises_not_found_for_unknown_id() -> None:
    service, _, _, _ = make_service()
    with pytest.raises(NotFoundError):
        service.get(make_admin(), 99)


# ---------------------------------------------------------------- create
def test_create_inserts_and_audits_in_one_transaction() -> None:
    service, db, locations, audit = make_service()

    location = service.create(make_admin(), location_form(details="Main gate"))

    assert db.transactions == 1
    assert locations.inserted == [location]
    assert location.id == 100 and location.details == "Main gate"
    entry = audit.entries[0]
    assert (entry.user_id, entry.action, entry.entity, entry.record_reference) == (
        1,
        "LOCATION_CREATED",
        "location",
        100,
    )
    assert entry.details is not None and "Riverside Park" in entry.details


def test_create_refuses_a_duplicate_name_with_a_field_error() -> None:
    service, db, locations, audit = make_service(make_location())

    with pytest.raises(ConflictError) as exc_info:
        service.create(make_admin(), location_form(address="Somewhere else"))

    assert "location_name" in exc_info.value.errors
    assert db.transactions == 0 and locations.inserted == [] and audit.entries == []


def test_create_rejects_invalid_form_before_touching_the_database() -> None:
    service, db, locations, audit = make_service()

    with pytest.raises(ValidationError) as exc_info:
        service.create(make_admin(), location_form(location_name="A", address=""))

    assert set(exc_info.value.errors) == {"location_name", "address"}
    assert db.transactions == 0 and locations.inserted == [] and audit.entries == []


# ---------------------------------------------------------------- update
def test_update_saves_changed_fields_and_audits_their_names() -> None:
    existing = make_location()
    service, db, locations, audit = make_service(existing)

    result = service.update(make_admin(), 7, location_form(address="1 New Street", details="x"))

    assert result is existing and result.address == "1 New Street" and result.details == "x"
    assert db.transactions == 1 and locations.updated == [existing]
    entry = audit.entries[0]
    assert (entry.action, entry.record_reference) == ("LOCATION_UPDATED", 7)
    assert entry.details == "Changed: address, details."


def test_update_with_no_changes_writes_nothing() -> None:
    service, db, locations, audit = make_service(make_location())

    service.update(make_admin(), 7, location_form())

    assert db.transactions == 0 and locations.updated == [] and audit.entries == []


def test_update_may_keep_its_own_name_but_not_take_another_locations_name() -> None:
    service, _, locations, _ = make_service(
        make_location(), make_location(id=8, location_name="Hill")
    )

    service.update(make_admin(), 7, location_form(address="Moved"))  # own name: fine
    assert len(locations.updated) == 1

    with pytest.raises(ConflictError) as exc_info:
        service.update(make_admin(), 7, location_form(location_name="Hill"))
    assert exc_info.value.errors == {"location_name": "A location with that name already exists."}
    assert len(locations.updated) == 1


def test_update_unknown_location_raises_not_found() -> None:
    service, _, _, _ = make_service()
    with pytest.raises(NotFoundError):
        service.update(make_admin(), 99, location_form())


# ---------------------------------------------------------------- delete
def test_delete_removes_the_row_and_audits_when_no_activities_use_it() -> None:
    service, db, locations, audit = make_service(make_location())

    deleted = service.delete(make_admin(), 7)

    assert deleted.id == 7
    assert db.transactions == 1 and locations.deleted == [7]
    assert [(e.action, e.entity, e.record_reference) for e in audit.entries] == [
        ("LOCATION_DELETED", "location", 7)
    ]


def test_delete_is_refused_while_activities_use_the_location() -> None:
    service, db, locations, audit = make_service(make_location())
    locations.activity_counts = {7: 2}

    with pytest.raises(ConflictError) as exc_info:
        service.delete(make_admin(), 7)

    assert "2 activities use" in exc_info.value.message
    assert db.transactions == 0 and locations.deleted == [] and audit.entries == []


def test_delete_unknown_location_raises_not_found() -> None:
    service, _, locations, _ = make_service()
    with pytest.raises(NotFoundError):
        service.delete(make_admin(), 99)
    assert locations.deleted == []
