"""BrowseService: volunteers (and admins) look at the activity catalogue (FR-3).

Read-only business rules, no SQL here:
- Only OPEN activities dated today or later are listed; a past activity stays
  hidden even if an admin forgot to close it.
- Lists come back as a Page (12 per page) so the template can show
  "Showing 1-12 of 30" and Previous/Next links.
- Available slots are never stored; the DAO counts PENDING + APPROVED
  registrations into `taken_slots` and the Activity model does the subtraction.
- Every method checks the role (FR-2), even though the routes also check it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.auth.roles import require_role
from app.dao import ActivityDAO, LocationDAO
from app.database import DatabaseManager
from app.errors import NotFoundError
from app.models import Activity, ActivityStatus, Location, Person, RoleName
from app.schemas.browse import BrowseFilterSchema
from app.services.pagination import Page, clamp_page, offset_for

PER_PAGE = 12
UPCOMING_LIMIT = 3
BROWSE_ROLES = (RoleName.VOLUNTEER, RoleName.ADMIN)


@dataclass
class BrowseService:
    activities: ActivityDAO
    locations: LocationDAO

    @classmethod
    def build(cls, db: DatabaseManager | None = None) -> BrowseService:
        """Convenience constructor used by controllers."""
        manager = db or DatabaseManager()
        return cls(activities=ActivityDAO(manager), locations=LocationDAO(manager))

    # --------------------------------------------------------------- list
    def list_open(
        self, actor: Person, filters: BrowseFilterSchema, today: date | None = None
    ) -> Page[Activity]:
        """One page of OPEN, not-yet-past activities matching the filters.

        `today` is a parameter so tests can freeze the calendar; the app passes None
        and gets the real date.
        """
        require_role(actor, *BROWSE_ROLES)
        date_from = today or date.today()
        total = self.activities.count_search(
            keyword=filters.keyword,
            location_id=filters.location_id,
            activity_date=filters.activity_date,
            date_from=date_from,
            status=ActivityStatus.OPEN,
        )
        # ?page=99 on a two-page list lands on the last page instead of an empty one.
        last_page = Page[Activity](per_page=PER_PAGE, total=total).pages
        page = min(clamp_page(filters.page), last_page)
        items = self.activities.search(
            keyword=filters.keyword,
            location_id=filters.location_id,
            activity_date=filters.activity_date,
            date_from=date_from,
            status=ActivityStatus.OPEN,
            limit=PER_PAGE,
            offset=offset_for(page, PER_PAGE),
        )
        return Page(items=items, page=page, per_page=PER_PAGE, total=total)

    def locations_for_filter(self, actor: Person) -> list[Location]:
        """All locations, for the <select> in the filter form."""
        require_role(actor, *BROWSE_ROLES)
        return self.locations.list_all()

    # --------------------------------------------------------------- detail
    def get_activity(self, actor: Person, activity_id: int) -> tuple[Activity, Location]:
        """The activity plus its location (address and details) for the details page."""
        require_role(actor, *BROWSE_ROLES)
        activity = self.activities.find_by_id(activity_id)
        if activity is None:
            msg = "Activity not found."
            raise NotFoundError(msg)
        location = self.locations.find_by_id(activity.location_id)
        if location is None:  # cannot happen with the FK in place, but never crash a page
            msg = "Activity not found."
            raise NotFoundError(msg)
        return activity, location

    # --------------------------------------------------------------- dashboard
    def upcoming(
        self, actor: Person, limit: int = UPCOMING_LIMIT, today: date | None = None
    ) -> list[Activity]:
        """The next few OPEN activities for the dashboard's "Upcoming activities" box."""
        require_role(actor, *BROWSE_ROLES)
        return self.activities.list_upcoming_open(limit=limit, today=today or date.today())
