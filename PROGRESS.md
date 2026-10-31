# Progress

A feature is **done** only when it has validation, error handling, tests (one success +
one failure case), audit logging where needed, and a responsive UI.

## Where we are (updated 2026-10-17, night)

| Phase | Status | Branch / PR |
|---|---|---|
| 0 Project setup | **Merged** | `feat/project-setup`, PR #1 |
| 1 Authentication | **Merged** + review hardening | `feat/auth` PR #2, `fix/auth-review` PR #3 |
| 2 Volunteer profile | **Merged** | `feat/profile`, PR #4 |
| 3 Admin: volunteers, locations, activities | **Merged** | `feat/admin-manage`, PR #6 |
| 4 Browse activities | **Merged** | `feat/browse-activities`, PR #7 |
| 5 Register for an activity | **Merged** | `feat/register`, PR #8 |
| 6 Admin review of registrations | **Merged** | `feat/admin-review`, PR #9 |
| 7 My registrations, schedule, notifications | **Merged** | `feat/my-registrations`, PR #10 |
| 8 Reports and audit logs | **Merged** | `feat/reports`, PR #11 |
| 9 Polish and deploy | **Ready for review** (533 unit+integration, 12 e2e) | `feat/polish` (built in the main folder) |

`main` is on GitHub (default branch) and only moves through pull requests. 532 unit +
integration tests and 9 Playwright tests pass on `main` (Phases 0-8); CI (ruff, mypy, pytest,
e2e) is green on every merged PR.

### How to resume work on this machine
1. Start MySQL from the terminal: `.\scripts\mysql.ps1` (XAMPP's own MariaDB; `stop` / `status` work too).
2. `git checkout main && git pull`, then `python scripts\upgrade_db.py` so an existing database gets new columns without losing data.
3. Run the app: `flask --app app run --debug` and open http://127.0.0.1:5000.
   Demo logins come from `python seed.py`: `admin` (SEED_ADMIN_PASSWORD in `.env`) and
   `maria`, `juan`, `liza`, `paolo` (SEED_VOLUNTEER_PASSWORD). Admins have no profile page by design.
4. Checks before any commit: `ruff format . && ruff check . && mypy . && pytest -q && pytest tests/e2e`.
   If the pages look unstyled, rebuild CSS with `.\scripts\tailwind.ps1` (app.css is git-ignored).
5. Never run two pytest suites against the same test database at once. For parallel work use a
   git worktree and set `TEST_DB_NAME` to another name in that worktree's `.env`.

### How each phase is built
Plan the phase in this file -> branch `feat/<name>` off `main` -> backend (schema, DAO, Pydantic
schema, service + unit tests) -> frontend (controller, templates, nav, integration + e2e tests, docs)
-> independent review (security, correctness, tests/docs) with every finding verified before it is
fixed -> merge `main` into the branch, full checks -> pull request -> CI green -> merge. Design
patterns to keep naming in code and in the defense: Singleton (`DatabaseManager`), MVC
(controllers / templates / models), inheritance (`Person` -> `Volunteer` / `Admin`), DAO (one class
per table, all SQL), Template Method (`BaseReport`).

### Next steps, in order
1. Phase 9 (`feat/polish`): review, PR, merge. After that every phase of the brief is on `main`.
2. Nicole: add `docs/design/erd.png` and `docs/design/reference.png`, create the "Protect main"
   ruleset (Open items below), and decide the deployment target (`docs/DEPLOYMENT.md` section 2).
3. Before the defense: `python scripts\init_db.py && python seed.py`, then walk through `docs/DEMO.md` once.

### Open items
- **Branch protection:** create the "Protect main" ruleset in GitHub (Settings -> Rules -> Rulesets):
  target the default branch; tick Restrict deletions, Block force pushes, Require a pull request
  (0 approvals), Require status checks with the check named `checks` and "up to date" on. Leave the rest off.
- `docs/design/erd.png` and `docs/design/reference.png` are still missing from the repo (needs the files from Nicole).
- Decided 2026-10-17: "Change Photo" shipped in Phase 2; "Forgot password?" is an admin "Reset password"
  action in Phase 3 (the brief has no email service), and the login page says "Ask an administrator".


## Phase 0: Project setup
- [x] Repo structure (MVC: controllers / templates / models, plus services, dao, database)
- [x] `.gitignore`, `.gitattributes` (LF), `.env.example`, pinned `requirements.txt`, ruff + mypy strict
- [x] `database/schema.sql` (InnoDB, utf8mb4, ENUMs, CHECKs, indexes) + `scripts/init_db.py`
- [x] `DatabaseManager` singleton (reconnect, transactions, error translation for FR-8)
- [x] Domain models: `BaseEntity` -> abstract `Person.generate_report()` -> `Volunteer` / `Admin`
- [x] `BaseReport` template method (`fetch_data` -> `summarize` -> `format`)
- [x] DAO classes, one per table, all SQL with `%s` placeholders
- [x] Flask app factory, typed errors, JSON logging, friendly 503 page when MySQL is down
- [x] Seed script through the DAOs (`--big` adds 1,000 activities)
- [x] Tailwind v4 standalone build script with theme colours
- [x] Tests: models, singleton, template method, every DAO (happy + failure), integration (schema, FR-8 cases, round trips)
- [x] GitHub Actions CI (ruff, mypy, pytest on MySQL 8)
- [x] README, REQUIREMENTS.md (SRS mapping), PROGRESS.md
- [ ] `docs/design/erd.png` and `docs/design/reference.png` added to the repo (needs the files)

## Phase 1: Authentication (merged: PR #2, hardening PR #3)
- [x] Pydantic schemas `SignUpSchema` / `LoginSchema` (`app/schemas/auth.py`) + `validate()` helper
- [x] `AuthService` (`app/services/auth_service.py`): sign-up creates user + profile + audit entry in one transaction; generic login error; 5 failures -> 15-minute lockout; counter reset on success; inactive accounts blocked
- [x] Role checks: `role_required` decorator + `require_role()` for services (`app/auth/roles.py`)
- [x] Login required app-wide except login, sign-up, health (`before_request` in `app/__init__.py`)
- [x] Rate limit on login (10/min) and sign-up (5/min)
- [x] Controllers: `auth` (login/logout/signup), `volunteer` dashboard, `admin` dashboard (+ `DashboardService`)
- [x] Templates: `base.html` header + sidebar (mobile toggle), split-screen login, sign-up, both dashboards, SVG placeholder images
- [x] Smoke test of login / logout / sign-up / dashboards / lockout with the test client (2026-10-17). Two fixes: password-mismatch error now shows on the confirm field even when other fields fail; the lockout message appears on the attempt that triggers the lock, not one attempt later
- [x] Tests: `tests/unit/test_schemas_auth.py`, `tests/unit/test_auth_service.py` (fake DAOs), `tests/unit/test_roles.py`, `tests/integration/test_auth_flow.py`, `tests/e2e/test_login.py` (Playwright, real server, CSRF on). 125 unit+integration and 2 e2e tests pass; CI runs the e2e step too
- [x] REQUIREMENTS.md rows FR-1, FR-2, FR-4, FR-6 and Usability updated
- [x] Independent code review (2026-10-17) and fixes: FR-8 error page no longer crashes for logged-in users when MySQL is down; failed-login counter is incremented under a row lock (`SELECT ... FOR UPDATE`) so parallel guesses cannot skip the lockout; deactivated accounts lose their session on the next request; passwords are limited to 72 *bytes*; `next=` redirect survives the login form and rejects `/\host`; rate limits now have tests (`tests/integration/test_auth_hardening.py`)

## Phase 2: Volunteer profile (merged: PR #4)
- [x] Schema: `users.photo_path` in `database/schema.sql`; `scripts/upgrade_db.py` adds missing columns to an existing database without wiping data (run it after pulling)
- [x] Pydantic schemas `ProfileSchema` / `ChangePasswordSchema` (`app/schemas/profile.py`): names 1-50, phone shape, address, birth date in the past and 13+, emergency contact; new password follows the sign-up rules and must differ from the current one
- [x] `ProfileService` (`app/services/profile_service.py`): every method VOLUNTEER-only (`require_role`); profile update upserts the `volunteer_profiles` row; password change verifies the current password; `check_photo()` accepts PNG/JPG/WEBP by extension AND magic bytes, max 2 MB
- [x] View / edit profile with validation (names, phone, address, birth date, emergency contact): `app/controllers/profile.py` (`/profile`, `/profile/edit`), `templates/volunteer/profile.html`, `profile_edit.html`
- [x] Change password (current password required): `/profile/password`, `templates/volunteer/change_password.html`; passwords are never echoed back
- [x] Change Photo: upload, type/size checks, default avatar fallback: inline form on the profile page posting to `/profile/photo`; files land in `instance/uploads/avatars/user_<id>.<ext>` (git-ignored, outside the public static folder) and are served to logged-in users only by `/profile/photo/<path>`; `partials/_avatar.html` shows the photo or initials in the header and on the profile page; oversized uploads get a friendly 413 page (`MAX_CONTENT_LENGTH` in `app/config.py`)
- [x] Audit log entries for profile and password changes: `PROFILE_UPDATED` (changed field names only, never values), `PASSWORD_CHANGED`, `PHOTO_UPDATED`
- [x] Navigation: "My Profile" sidebar link (`app/navigation.py`, highlighted on every `/profile` page), dashboard card "Edit Profile" opens the profile; login page says "Forgot your password? Ask an administrator."
- [x] Tests: `tests/unit/test_schemas_profile.py`, `tests/unit/test_profile_service.py` (fake DAOs, photo checks), `tests/unit/test_dao.py` (photo/password updates), `tests/integration/test_profile_flow.py` (view, 403 for admins, edit + audit, inline errors, password change + re-login, photo upload to a temp folder, bad file, 413), `tests/e2e/test_profile.py` (Playwright: edit phone from My Profile)
- [x] REQUIREMENTS.md rows FR-3, FR-4, FR-6 updated; README notes `scripts/upgrade_db.py` and the uploads folder
- [x] Review fixes: new passwords are limited to 72 *bytes* (shared `check_password_strength()` in `app/schemas/auth.py`, used by sign-up and change password); the avatar file is written inside the database transaction; photos moved out of `app/static` behind a login-protected route; integration test asserts the real birth-date error, not the form hint

## Phase 3: Admin activities and locations (merged: PR #6)
- [x] Users list for admins with "Reset password" and activate/deactivate (replaces "Forgot password?"): `/admin/volunteers` (`app/controllers/admin_volunteers.py`, `templates/admin/volunteers.html`), 20 per page, search on name / username / email (`UserDAO.search_volunteers()` / `count_volunteers()`, LIKE wildcard in the value); `AdminUserService` (`app/services/admin_user_service.py`) lists volunteers only, refuses self-deactivation and admin targets, generates a 12-character temporary password with `secrets` (letter + digit guaranteed, no look-alike characters), stores only its hash, flashes it ONCE to the admin and notifies the volunteer
- [x] Locations CRUD: `/admin/locations` list with activity counts (`LocationDAO.list_with_activity_counts()`, LEFT JOIN + COUNT), new / edit (shared `templates/admin/locations/form.html`) and delete (`app/controllers/admin_locations.py`); `LocationSchema` (`app/schemas/location.py`); `LocationService` refuses duplicate names (inline field error) and deleting a location that still has activities
- [x] Activities CRUD; delete with registrations sets CANCELLED: `/admin/activities` list (10 per page, `?status=` filter, slots taken / max from `Activity.available_slots`), new / edit (shared `templates/admin/activities/form.html`, location drop-down), delete and status change (`app/controllers/admin_activities.py`); `ActivitySchema` (`app/schemas/activity.py`) parses the form text and refuses a past date only on create (validation context), end time must be after start; `ActivityService` keeps `max_volunteers` >= taken slots on edit, `delete_or_cancel()` deletes only when nobody ever registered, otherwise sets CANCELLED and notifies every PENDING / APPROVED registrant (`RegistrationDAO.list_user_ids_by_activity()`); `change_status()` to CANCELLED follows the same path
- [x] Audit log on every create / update / delete / cancel: `LOCATION_CREATED` / `_UPDATED` / `_DELETED`, `ACTIVITY_CREATED` / `_UPDATED` / `_DELETED` / `_CANCELLED` / `_STATUS_CHANGED` ("OPEN -> CLOSED"), `USER_ACTIVATED` / `USER_DEACTIVATED`, `PASSWORD_RESET` (details never contain the password), all written in the same transaction as the change
- [x] Shared pieces for later phases: `Page` dataclass (`app/services/pagination.py`) + `partials/_pagination.html` macro `paginate(page_obj, endpoint, **filters)`; `select_field` and `textarea_field` macros in `partials/_forms.html`; `status_badge` knows ACTIVE / INACTIVE
- [x] Navigation: sidebar "Manage Activities", "Manage Locations" and "Volunteers" open the new pages (highlighted on every page of their blueprint); the admin dashboard's "Total Activities" and "Total Volunteers" cards link to the lists ("Registrations", "Reports", "Audit Logs" stay at `#` until their phases)
- [x] Tests: `tests/unit/test_schemas_location_activity.py`, `test_location_service.py`, `test_activity_service.py`, `test_admin_user_service.py`, `test_pagination.py`, new DAO tests in `test_dao.py`; `tests/integration/test_admin_manage_flow.py` (403 for volunteers on every admin route, locations CRUD + duplicate name + delete refused, activities create / edit / filter / pagination / status change, delete-vs-cancel with notifications only for PENDING / APPROVED, volunteers search / pagination / deactivate blocks login / reset password then the temporary password logs in); `tests/e2e/test_admin_activities.py` (Playwright: admin creates a location and an activity through the forms, changes its status through the row form with `confirm()`). 371 unit+integration and 4 e2e tests pass
- [x] REQUIREMENTS.md rows FR-3, FR-4, FR-6 and Usability updated

## Phase 4: Browse activities (merged: PR #7)
- [x] DAO: `ActivityDAO.search()` / `count_search()` gained `date_from` (shared `_search_filters()` so list and count never drift; LIKE wildcard stays in the value) and `list_upcoming_open()` (`app/dao/activity_dao.py`)
- [x] Schema: `BrowseFilterSchema` (`app/schemas/browse.py`): keyword (max 100), location, exact date, page; `from_query()` is tolerant and drops bad URL values instead of showing an error page
- [x] `BrowseService` (`app/services/browse_service.py`): `list_open()` returns a `Page[Activity]` (12 per page, OPEN and dated today or later, soonest first, an out-of-range page clamps to the last page), `locations_for_filter()`, `get_activity()` (NotFoundError -> 404 page), `upcoming()`; every method accepts VOLUNTEER and ADMIN via `require_role` (`app/services/pagination.py` holds the generic `Page[T]`)
- [x] OPEN activities list with search, filters (date, location, keyword) and pagination: `app/controllers/activities.py` (`GET /activities`), `templates/volunteer/activities/list.html` (GET filter form, cards in 1/2/3 columns, slots left or "Full", status badge, empty state with clear-filters link), `partials/_pagination.html` (`paginate()` macro: "Showing X-Y of Z" + Previous/Next links that keep the filters), `select_field()` macro in `partials/_forms.html`
- [x] Details page with computed available slots: `GET /activities/<id>`, `templates/volunteer/activities/detail.html` (description, requirements, location address and details, slots computed from PENDING + APPROVED registrations, disabled "Register" button with "Registration opens in the next phase", "Back to activities")
- [x] Volunteer dashboard "Upcoming activities" (3 soonest OPEN activities with links, or an empty state); sidebar "Activities" link and dashboard card "Browse Activities" open the list (`app/navigation.py`, `templates/volunteer/dashboard.html`)
- [x] Tests: `tests/unit/test_schemas_browse.py`, `tests/unit/test_browse_service.py` (fake DAOs), `tests/unit/test_dao.py` (date_from and upcoming SQL), `tests/integration/test_browse_flow.py` (only OPEN future activities listed, filters, 13 activities -> 2 pages with the filters kept in the links, slots from PENDING + APPROVED only, 404 page, admin can view, anonymous redirected, dashboard upcoming), `tests/e2e/test_browse.py` (Playwright: filter by keyword, open details, see the slots text)
- [x] REQUIREMENTS.md rows FR-3, FR-4 and NFR Performance updated

## Phase 5: Register for an activity (merged: PR #8)
- [x] Checks: OPEN, not already registered, slots available: `RegistrationService.register()` (`app/services/registration_service.py`, VOLUNTEER-only via `require_role`) refuses a CLOSED / CANCELLED / COMPLETED or already-started activity ("This activity is not open for registration."), a PENDING / APPROVED row ("You are already registered for this activity."), a REJECTED / COMPLETED row ("You cannot register for this activity again.", those states are final) and a full activity ("This activity is full."); typed `ConflictError`s that the controller turns into flash messages
- [x] `SELECT ... FOR UPDATE` in one transaction; re-use cancelled row: the whole check-and-write runs inside `db.transaction()`; `ActivityDAO.lock_for_update()` locks the activity row first so racing volunteers queue up; slots are counted under that lock with a locking read (`RegistrationDAO.count_slot_taking(for_update=True)`, `LOCK IN SHARE MODE`) so the count is the latest committed one, not a snapshot; a CANCELLED row goes back to PENDING through `RegistrationDAO.reopen()` (same id, review fields cleared); a race that slips past the duplicate check is caught by `UNIQUE(activity_id, user_id)` -> `ConflictError`
- [x] Notify admins: one `REGISTRATION_SUBMITTED` notification per administrator (`UserDAO.list_admin_ids()` + `NotificationDAO.insert_many()`), written in the same transaction as the row and the `REGISTRATION_CREATED` audit entry (entity `registration`, details name the activity, never personal data)
- [x] UI: `POST /activities/<id>/register` (`app/controllers/activities.py`, `role_required(VOLUNTEER)`, CSRF form) redirects back to the details page with a success or error flash; the details page's slot card (`templates/volunteer/activities/detail.html`) shows exactly one state: Register button, "Register again" after a cancellation, "You are registered" + Pending / Approved badge, "Your registration" + Rejected / Completed badge (with the admin's remarks when rejected), disabled button with "This activity is full." / "Registration is closed.", or "Administrators cannot register for activities." (`RegistrationService.can_register()` is the single rule behind the button)
- [x] Tests: `tests/unit/test_registration_service.py` (fake DAOs: one transaction, lock inside it, locking count, audit + admin notifications, every refusal, cancelled row re-used, `can_register` table), `tests/integration/test_register_flow.py` (row + audit + one notification per admin, details page flips to Pending and slots drop by one, duplicate / full / closed / rejected refused with no new row, admin 403, 404 page, cancelled row re-used with the same id, second volunteer loses the last slot), `tests/e2e/test_register.py` (Playwright: click Register, see "You are registered" and 24 of 25 slots left); Phase 4's two placeholder-button assertions updated. 459 unit+integration and 6 e2e tests pass
- [x] REQUIREMENTS.md rows FR-3, FR-6 updated

## Phase 6: Admin review (merged: PR #9)
- [x] Pending list; approve re-checks capacity; reject requires remarks: `/admin/registrations` (`app/controllers/admin_registrations.py`, `templates/admin/registrations.html`), 20 per page, oldest request first, `?status=` filter (PENDING by default, `all` for every status; `RegistrationDAO.search()` / `count_search()` share `_status_filter()`), each pending row has an Approve form (`confirm()`) and a Reject form with a required remarks box; `RegistrationReviewService` (`app/services/review_service.py`, every method ADMIN-only via `require_role`): only a PENDING row can be reviewed (a second review is refused with "already APPROVED"), `approve()` locks the activity row (`ActivityDAO.lock_for_update()`) and re-checks capacity with a locking count of APPROVED rows (`RegistrationDAO.count_for_activity(..., for_update=True)`), refuses CANCELLED / COMPLETED activities (CLOSED is fine: it only stops new sign-ups); `reject()` validates `RejectSchema` (`app/schemas/review.py`, remarks 3-500 characters) before touching the database
- [x] reviewed_by / reviewed_at, notify volunteer, audit log: `RegistrationDAO.review()` stores status, `reviewed_by`, `reviewed_at`, `remarks`; the volunteer gets `REGISTRATION_APPROVED` or `REGISTRATION_REJECTED` (the message repeats the remarks); audit `REGISTRATION_APPROVED` / `REGISTRATION_REJECTED` (entity `registration`); all three writes in one transaction. The volunteer's details page (Phase 5) shows the Rejected badge with the remarks
- [x] Navigation: sidebar "Registrations" opens the pending list (highlighted on the whole blueprint); the admin dashboard's "Pending Registrations" / "Approved Registrations" cards link to the filtered list, and each "Recent Registrations" row has a Review / View link that jumps to its row (`#registration-<id>`); `Registration.activity_date` is filled by the DAO join for the list
- [x] Tests: `tests/unit/test_review_service.py` (fake DAOs: one transaction with the lock inside it, locking APPROVED count, review fields, volunteer notification, audit, capacity refusal, cancelled / completed refusal, CLOSED allowed, non-PENDING refused, remarks required, list filter), `tests/unit/test_dao.py` (search / count_search / count_for_activity SQL), `tests/integration/test_admin_review_flow.py` (403 for volunteers, pending list, approve with reviewed_by / reviewed_at / notification / audit, reject without then with remarks, double review refused, approve refused when approved slots are full or the activity is cancelled, 404, filter + pagination with 22 rows, dashboard links, volunteer sees the rejection and remarks), `tests/e2e/test_admin_review.py` (Playwright: approve one row, reject another with remarks, see the remarks under the Rejected badge). 489 unit+integration and 7 e2e tests pass
- [x] REQUIREMENTS.md rows FR-3, FR-4, FR-6 updated

## Phase 7: My registrations, schedule, notifications (merged: PR #10)
- [x] Registration status list with tabs: `/registrations` (`app/controllers/registrations.py`, `templates/volunteer/registrations/list.html`), tabs All / Pending / Approved / Rejected / Cancelled / Completed with counts (`MyRegistrationsService.list_mine()` in `app/services/my_registrations_service.py`, VOLUNTEER-only, reads only the actor's own rows via `RegistrationDAO.list_by_user()`); each row links to the activity and shows date, time, location, review date and the admin's remarks; `RegistrationDAO` now joins `locations` and exposes `activity_start_time` / `activity_end_time` / `activity_status` / `location_name` on `Registration`
- [x] Cancel rules (PENDING/APPROVED and not started); notify admin + audit log: `POST /registrations/<id>/cancel` -> `MyRegistrationsService.cancel()` inside one transaction under the activity row lock (same lock order as registering and reviewing): someone else's row is a 404 (never revealed), REJECTED / CANCELLED / COMPLETED rows are refused, a started activity is refused, otherwise `set_status(CANCELLED)`, one `REGISTRATION_CANCELLED` notification per administrator and the `REGISTRATION_CANCELLED` audit entry ("APPROVED -> CANCELLED"); the slot is free again and registering again re-uses the row (Phase 5); `Registration.can_cancel()` / `activity_has_started()` / `activity_hours` are the model-side rules used by the template
- [x] Schedule + history: `/registrations/schedule` (`schedule.html`): Upcoming = PENDING / APPROVED rows dated today or later (soonest first), History = COMPLETED rows or past PENDING / APPROVED rows (most recent first; rejected and cancelled rows never appear), cards for upcoming count, completed count and hours volunteered (APPROVED + COMPLETED rows in the history)
- [x] Notifications with mark-as-read: `/notifications` for BOTH roles (`app/controllers/notifications.py`, `templates/notifications/list.html`): newest 50 messages with a type label, unread rows highlighted, "Mark as read" per row (`POST /notifications/<id>/read`, the DAO's WHERE includes the user id so another user's message is a 404) and "Mark all as read" (`POST /notifications/read-all`); `NotificationService.mark_read()` / `mark_all_read()`; the header bell now opens the inbox and keeps its unread badge
- [x] Navigation: sidebar "My Registrations", "My Schedule" (new calendar icon) and "Notifications" open the pages; dashboard card "View Registrations" and the details page's "View my registrations" link too
- [x] Tests: `tests/unit/test_my_registrations_service.py` (fake DAOs: own rows only with tab counts, schedule split + hours, cancel for PENDING / APPROVED with lock inside the transaction + admin notifications + audit, refusals for no-slot rows / started activity / someone else's row, role check, mark-read uses the actor's id and 404s), `tests/integration/test_my_registrations_flow.py` (admin 403, tabs and counts, empty state, cancel frees the slot + notifies every admin + audits + register again re-uses the row, refusals, schedule split, inbox with per-row and mark-all read, badge count, admin inbox gets registration events), `tests/e2e/test_my_registrations.py` (Playwright: cancel from My Registrations, see the Cancelled tab, empty schedule, read a notification from the bell). 509 unit+integration and 8 e2e tests pass
- [x] REQUIREMENTS.md rows FR-3, FR-6 updated

## Phase 8: Reports and audit logs (merged: PR #11)
- [x] Reports on screen with filters; CSV export; printable view: `/admin/reports` index (`app/controllers/admin_reports.py`, `templates/admin/reports/index.html`) lists three reports, all built on the `BaseReport` template method (`generate()` = `fetch_data` -> `summarize` -> `format`): `SystemTotalsReport` (existing), `ActivityParticipationReport` (one row per activity with pending / approved / completed slots and fill rate, from `ActivityDAO.report_rows()`: LEFT JOIN + conditional SUM so empty activities still appear) and `VolunteerHoursReport` (one row per volunteer with registrations by status and hours of APPROVED / COMPLETED activities, grouped in `summarize()` from `RegistrationDAO.report_rows()`), both in `app/services/reports/admin_reports.py`; `ReportFilterSchema` (`app/schemas/report.py`, tolerant GET filters: activity date range, status; a backwards range drops its end date); `ReportService` (`app/services/report_service.py`, ADMIN-only catalogue / generate, 404 for unknown names) renders one `templates/reports/show.html` (filter form, summary cards, table, Download CSV + Printable view buttons that keep the filters), `GET /admin/reports/<name>.csv` (standard `csv` module, header + rows + blank line + summary, UTF-8 BOM, `Content-Disposition: attachment`) and `GET /admin/reports/<name>/print` (`templates/reports/print.html`: plain page without header or sidebar, generated-at line with the active filters, `print:hidden` toolbar with a Print button); `cell_text()` formats dates, times, PyMySQL timedeltas and floats the same way for HTML, CSV and print
- [x] Volunteer's own report through polymorphism: `GET /registrations/report` (+ `.csv`, `/print`) calls `ReportService.for_person()` -> `current_user.generate_report()`, so a Volunteer gets `VolunteerActivityReport` and an Admin would get `SystemTotalsReport` without the service knowing the subclass; linked from My Schedule ("My activity report")
- [x] Audit log viewer with filters: `/admin/audit-logs` (`app/controllers/admin_audit.py`, `templates/admin/audit_logs.html`), 25 per page newest first, filters action (drop-down of every distinct code, `AuditLogDAO.list_actions()`), username (partial match, wildcard in the value), date range (`AuditFilterSchema`, tolerant, `?page=99` clamps to the last page); `AuditService` (`app/services/audit_service.py`, ADMIN-only); `AuditLogDAO.search()` / `count_search()` share `_filters()` so the page and its total never disagree
- [x] Navigation: sidebar "Reports" and "Audit Logs" open the pages (highlighted on their blueprints); every sidebar link now has a page
- [x] Tests: `tests/unit/test_report_service.py` (tolerant schemas, both reports through `generate()` with fake DAO rows including timedelta times, catalogue / 404 / role checks, polymorphic `for_person`, `cell_text`, CSV layout, `AuditService` paging and clamping), `tests/unit/test_dao.py` (report SQL, audit search / count / distinct actions), `tests/integration/test_reports_flow.py` (403 for volunteers on every report and audit route, index, system totals, activity participation with status / date filters and empty state, volunteer hours, CSV headers + content, printable view without navigation, volunteer's own report + CSV + print and 403 for admins, audit viewer with 28 entries over 2 pages, action / username / date filters, clamping), `tests/e2e/test_reports.py` (Playwright: open Activity Participation, filter by status, download the CSV, find an entry in Audit Logs and filter by action). 532 unit+integration and 9 e2e tests pass
- [x] REQUIREMENTS.md rows FR-6 (viewer), FR-7 updated

## Phase 9: Polish and deploy (branch `feat/polish`, ready for review)
- [x] Responsive + accessible UI, empty/error/loading states: `base.html` gained a "Skip to main content" link (first Tab, `sr-only` until focused) and a focusable `<main id="main">` landmark, a `<meta name="description">`, and a double-submit guard (the only other JavaScript besides the sidebar toggle: once a form really submits, its button is disabled, `aria-busy="true"` and reads "Please wait..."; a cancelled `confirm()` leaves it alone); the error page names each code (403 / 404 / 413 / 429 / 503) with a one-line hint; every page already had one `h1`, labelled fields with inline errors, text badges, `aria-current` on the active link, horizontally scrolling tables and empty states (verified page by page). Tailwind now scans `app/controllers` and `app/navigation.py` (the old `blueprints` path never existed)
- [x] Demo seed data: `python seed.py` also writes 10 registrations in every status (3 APPROVED, 3 PENDING, 2 COMPLETED, 1 REJECTED with remarks, 1 CANCELLED) through the DAOs with the notifications and audit entries the real flows would have written (`Seeder.ensure_registration()`, `ACTIVITY_CREATED` on each new activity); still idempotent (`tests/integration/test_seed.py` runs it twice)
- [x] README screenshots: `scripts/screenshots.py` rebuilds a scratch database (`greenhands_demo`, never the dev one) from `schema.sql`, seeds it, starts the real app with CSRF on and captures 14 PNGs into `docs/screenshots/` (login, admin dashboard / activities / registrations / report / audit logs, volunteer dashboard / activities / detail / registrations / schedule / notifications, phone list + open menu); README shows them in a two-column table and documents the script
- [x] 15-minute demo checklist: `docs/DEMO.md` (set-up steps, a minute-by-minute table that names the pattern or FR each step proves, the code questions to expect with their answers, and what to do if something goes wrong)
- [x] Deployment guide: `docs/DEPLOYMENT.md` (defense setup on XAMPP, production changes: `FLASK_ENV=production`, dedicated DB user with a GRANT snippet, WSGI options with waitress recommended and Apache + mod_wsgi only described because the brief asks for a decision first, HTTPS note, pre-launch checklist, backups, operations notes)
- [x] User guide: `docs/USER_GUIDE.md` (how to use every page as a volunteer and as an administrator, plus the messages users may see and what to do), linked from the README and the demo checklist
- [x] README: Screenshots, Documentation and Accessibility sections, Commands table updated
- [x] Tests: `tests/e2e/test_accessibility.py` (phone viewport: menu button with `aria-expanded`, Escape closes, no horizontal scroll; skip link focuses `#main`; a held POST shows the disabled "Please wait" button), `tests/integration/test_seed.py` (counts per table and status, notifications and audit totals, idempotent second run, demo accounts log in). 533 unit+integration and 12 e2e tests pass
- [x] REQUIREMENTS.md NFR rows Usability, Reliability, Portability updated

