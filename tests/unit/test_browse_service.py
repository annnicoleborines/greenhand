"""Unit tests for BrowseService (FR-2 role check, FR-3 read-only browse rules).

No database: the DAOs are small in-memory fakes that record the arguments they
were called with, so we can prove the service passes filters through, always
adds `date_from = today` and does the page arithmetic correctly.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

import pytest

from app.errors import ForbiddenError, NotFoundError
from app.models import Activity, ActivityStatus, Admin, Location, Person, RoleName, Volunteer
from app.schemas.browse import BrowseFilterSchema
from app.services.browse_service import PER_PAGE, BrowseService

TODAY = date(2030, 6, 15)


# ----------------------------------------------------------------- fakes
class FakeActivityDAO:
    def __init__(self, *activities: Activity, total: int | None = None) -> None:
        self.activities = list(activities)
        self.total = total if total is not None else len(self.activities)
        self.search_kwargs: dict[str, Any] = {}
        self.count_kwargs: dict[str, Any] = {}
        self.upcoming_kwargs: dict[str, Any] = {}

    def search(self, **kwargs: Any) -> list[Activity]:
        self.search_kwargs = kwargs
        return self.activities

    def count_search(self, **kwargs: Any) -> int:
        self.count_kwargs = kwargs
        return self.total

    def find_by_id(self, activity_id: int) -> Activity | None:
        return next((a for a in self.activities if a.id == activity_id), None)

    def list_upcoming_open(self, *, limit: int, today: date) -> list[Activity]:
        self.upcoming_kwargs = {"limit": limit, "today": today}
        return self.activities[:limit]


class FakeLocationDAO:
    def __init__(self, *locations: Location) -> None:
        self.locations = list(locations)

    def find_by_id(self, location_id: int) -> Location | None:
        return next((loc for loc in self.locations if loc.id == location_id), None)

    def list_all(self) -> list[Location]:
        return self.locations


# ----------------------------------------------------------------- helpers
def make_activity(activity_id: int = 1, *, location_id: int = 2, taken: int = 4) -> Activity:
    return Activity(
        id=activity_id,
        created_by=1,
        location_id=location_id,
        title="Planting",
        activity_date=TODAY,
        start_time=time(7, 0),
        end_time=time(11, 0),
        max_volunteers=10,
        status=ActivityStatus.OPEN,
        taken_slots=taken,
        location_name="Park",
    )


def volunteer() -> Volunteer:
    return Volunteer(
        id=5,
        role_id=1,
        role_name=RoleName.VOLUNTEER,
        username="maria",
        email="maria@example.com",
        first_name="Maria",
        last_name="Santos",
    )


def admin() -> Admin:
    return Admin(
        id=1,
        role_id=2,
        role_name=RoleName.ADMIN,
        username="admin",
        email="admin@example.com",
        first_name="Ada",
        last_name="Min",
    )


class Stranger(Person):
    """A Person with a role the browse pages do not accept (for the ForbiddenError tests)."""

    def generate_report(self, context: Any) -> Any:
        raise NotImplementedError


def stranger() -> Person:
    return Stranger(
        id=9,
        role_id=9,
        role_name="GUEST",  # type: ignore[arg-type]
        username="guest",
        email="g@example.com",
        first_name="G",
        last_name="U",
    )


def make_service(
    activities: FakeActivityDAO | None = None, locations: FakeLocationDAO | None = None
) -> BrowseService:
    return BrowseService(
        activities=activities or FakeActivityDAO(),  # type: ignore[arg-type]
        locations=locations or FakeLocationDAO(),  # type: ignore[arg-type]
    )


# ----------------------------------------------------------------- list_open
def test_list_open_passes_filters_and_adds_today_as_date_from() -> None:
    dao = FakeActivityDAO(make_activity())
    filters = BrowseFilterSchema(keyword="plant", location_id=2, activity_date=TODAY)

    page = make_service(dao).list_open(volunteer(), filters, today=TODAY)

    expected = {
        "keyword": "plant",
        "location_id": 2,
        "activity_date": TODAY,
        "date_from": TODAY,
        "status": ActivityStatus.OPEN,
    }
    assert dao.count_kwargs == expected
    assert dao.search_kwargs == {**expected, "limit": PER_PAGE, "offset": 0}
    assert page.items[0].available_slots == 6
    assert page.total == 1 and page.pages == 1


def test_list_open_uses_real_today_when_not_given() -> None:
    dao = FakeActivityDAO()
    make_service(dao).list_open(volunteer(), BrowseFilterSchema())
    assert dao.search_kwargs["date_from"] == date.today()
    assert dao.count_kwargs["date_from"] == date.today()


def test_list_open_page_math() -> None:
    dao = FakeActivityDAO(make_activity(), total=13)  # 13 rows -> 2 pages of 12
    page = make_service(dao).list_open(volunteer(), BrowseFilterSchema(page=2), today=TODAY)

    assert dao.search_kwargs["limit"] == 12
    assert dao.search_kwargs["offset"] == 12
    assert page.page == 2 and page.per_page == 12 and page.total == 13
    assert page.pages == 2
    assert page.has_prev is True and page.has_next is False
    assert (page.start, page.end) == (13, 13)


def test_list_open_first_page_numbers() -> None:
    dao = FakeActivityDAO(make_activity(), total=13)
    page = make_service(dao).list_open(volunteer(), BrowseFilterSchema(), today=TODAY)
    assert (page.start, page.end) == (1, 12)
    assert page.has_prev is False and page.has_next is True and page.next_page == 2


def test_list_open_empty_result() -> None:
    page = make_service(FakeActivityDAO()).list_open(volunteer(), BrowseFilterSchema())
    assert page.items == [] and page.total == 0
    assert page.pages == 1 and (page.start, page.end) == (0, 0)


def test_admin_may_browse_too() -> None:
    page = make_service(FakeActivityDAO(make_activity())).list_open(admin(), BrowseFilterSchema())
    assert len(page.items) == 1


def test_other_roles_are_forbidden_everywhere() -> None:
    service = make_service(FakeActivityDAO(make_activity()), FakeLocationDAO())
    with pytest.raises(ForbiddenError):
        service.list_open(stranger(), BrowseFilterSchema())
    with pytest.raises(ForbiddenError):
        service.locations_for_filter(stranger())
    with pytest.raises(ForbiddenError):
        service.get_activity(stranger(), 1)
    with pytest.raises(ForbiddenError):
        service.upcoming(stranger())


# ----------------------------------------------------------------- locations
def test_locations_for_filter_returns_all() -> None:
    park = Location(id=2, location_name="Park", address="Main")
    assert make_service(locations=FakeLocationDAO(park)).locations_for_filter(volunteer()) == [park]


# ----------------------------------------------------------------- get_activity
def test_get_activity_returns_activity_and_location() -> None:
    park = Location(id=2, location_name="Park", address="Main St", details="Gate B")
    service = make_service(FakeActivityDAO(make_activity(3)), FakeLocationDAO(park))

    activity, location = service.get_activity(volunteer(), 3)

    assert activity.id == 3 and activity.available_slots == 6
    assert location == park


def test_get_activity_missing_raises_not_found() -> None:
    with pytest.raises(NotFoundError, match="Activity not found."):
        make_service().get_activity(volunteer(), 404)


def test_get_activity_without_location_row_raises_not_found() -> None:
    service = make_service(FakeActivityDAO(make_activity(3, location_id=77)), FakeLocationDAO())
    with pytest.raises(NotFoundError):
        service.get_activity(volunteer(), 3)


# ----------------------------------------------------------------- upcoming
def test_upcoming_asks_dao_for_three_from_today() -> None:
    dao = FakeActivityDAO(make_activity(1), make_activity(2), make_activity(3), make_activity(4))
    items = make_service(dao).upcoming(volunteer(), today=TODAY)
    assert dao.upcoming_kwargs == {"limit": 3, "today": TODAY}
    assert [a.id for a in items] == [1, 2, 3]


def test_upcoming_defaults_to_real_today() -> None:
    dao = FakeActivityDAO()
    make_service(dao).upcoming(admin(), limit=5)
    assert dao.upcoming_kwargs == {"limit": 5, "today": date.today()}
