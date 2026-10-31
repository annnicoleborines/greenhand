"""Activities controller: volunteers (and admins) browse the activity catalogue,
and volunteers register for an activity.

Thin by design (Controller in MVC): read the query string or form, call a
service, pick a template or redirect. The filter form is a GET form, so its
values live in the URL and a page can be bookmarked or shared;
`BrowseFilterSchema.from_query` turns them into typed filters and quietly drops
anything invalid (FR-4). Browsing accepts any logged-in role (FR-2); registering
is VOLUNTEER-only. Anonymous visitors are sent to the login page by the
app-wide gate in `create_app`.
"""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user

from app.auth.roles import role_required
from app.errors import ConflictError, NotFoundError
from app.models import RoleName
from app.schemas.browse import BrowseFilterSchema
from app.services.browse_service import BrowseService
from app.services.registration_service import RegistrationService

activities_bp = Blueprint("activities", __name__, url_prefix="/activities")


@activities_bp.get("")  # the empty rule means exactly "/activities" (no trailing slash)
@role_required(RoleName.VOLUNTEER, RoleName.ADMIN)
def list_activities() -> ResponseReturnValue:
    """GET /activities?keyword=&location_id=&activity_date=&page= : one page of OPEN activities."""
    service = BrowseService.build()
    filters = BrowseFilterSchema.from_query(request.args)
    page = service.list_open(current_user, filters)
    # The <select> macro wants (value, label) pairs.
    location_options = [
        (loc.id, loc.location_name) for loc in service.locations_for_filter(current_user)
    ]
    return render_template(
        "volunteer/activities/list.html",
        page=page,
        filters=filters,
        location_options=location_options,
    )


@activities_bp.get("/<int:activity_id>")
@role_required(RoleName.VOLUNTEER, RoleName.ADMIN)
def detail(activity_id: int) -> ResponseReturnValue:
    """GET /activities/<id> : everything about one activity, or the 404 page."""
    activity, location = BrowseService.build().get_activity(current_user, activity_id)
    # The volunteer's own registration (None for admins or when they never signed up)
    # decides what the slot card shows: a Register button, "Pending", "Approved", ...
    registration = RegistrationService.build().registration_for(current_user, activity_id)
    return render_template(
        "volunteer/activities/detail.html",
        activity=activity,
        location=location,
        registration=registration,
        can_register=RegistrationService.can_register(activity, registration),
    )


@activities_bp.post("/<int:activity_id>/register")
@role_required(RoleName.VOLUNTEER)
def register(activity_id: int) -> ResponseReturnValue:
    """POST /activities/<id>/register : sign the current volunteer up (PENDING)."""
    try:
        registration = RegistrationService.build().register(current_user, activity_id)
    except NotFoundError:
        raise  # the 404 page
    except ConflictError as err:
        flash(err.message, "error")  # full, closed, already registered, ...
        return redirect(url_for("activities.detail", activity_id=activity_id))

    flash(
        f"You are registered for {registration.activity_title}. "
        "An administrator will review your request.",
        "success",
    )
    return redirect(url_for("activities.detail", activity_id=activity_id))
