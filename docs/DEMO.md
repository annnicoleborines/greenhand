# GreenHands: 15-minute demo checklist

A scripted walkthrough for the defense. Times are a guide; the whole run fits in
15 minutes with questions at the end. Every step names the design pattern or
requirement it demonstrates, so the graders can tick them off as you go.

For what each page does from the user's point of view, see [USER_GUIDE.md](USER_GUIDE.md).

## Before you start (5 minutes, not part of the demo)

1. Start MySQL from the terminal: `.\scripts\mysql.ps1`
2. Fresh demo data: `python scripts\init_db.py` then `python seed.py`
   (or `python seed.py --big` to show 1,000+ activities paging quickly).
3. Start the app: `flask --app app run --debug` and open http://127.0.0.1:5000
4. Open a second browser window (or a private window) so the admin and a volunteer
   can be logged in side by side.
5. Have `database/schema.sql`, `app/database/db_manager.py`, `app/services/reports/base_report.py`
   and `app/dao/registration_dao.py` open in the editor for the code questions.

Demo accounts (passwords are the `SEED_*` values in your `.env`):
`admin` (administrator), `maria`, `juan`, `liza`, `paolo` (volunteers).

## The demo

| Min | Step | What to show | Pattern / requirement |
|---|---|---|---|
| 0-1 | **Login** as `maria` | The split-screen login, generic "Invalid username or password" on a wrong password, 5 failures lock the account for 15 minutes | FR-1, FR-2, bcrypt, lockout |
| 1-2 | **Volunteer dashboard** | Upcoming activities box, cards to Activities / My Registrations / My Profile, unread bell | MVC: `volunteer` controller -> `DashboardService` / `BrowseService` -> template |
| 2-4 | **Browse activities** | Keyword / location / date filters in the URL, 12 per page, "Showing 1-12 of N", slots left computed live | FR-3 read, FR-4 tolerant filters, NFR pagination; `ActivityDAO.search()` + `count_search()` share one WHERE |
| 4-5 | **Register** for an open activity | Click Register, see "Pending", slots drop by one; click again: "already registered" | `SELECT ... FOR UPDATE` in `RegistrationService.register()`, one transaction, UNIQUE backstop |
| 5-6 | **My Registrations** | Status tabs with counts, cancel a pending one (confirm dialog), "Register again" appears; My Schedule shows upcoming vs history and hours | Cancel rules: PENDING/APPROVED and not started; admins notified; audit `REGISTRATION_CANCELLED` |
| 6-7 | **My Profile** | Edit phone, change password, upload a photo (type + size + magic bytes checked, 2 MB limit, served only when logged in) | FR-3 update, FR-4 validation (`ProfileSchema`), FR-6 audit |
| 7-8 | **Switch to `admin`** (second window) | Admin dashboard counts and recent registrations, the bell shows Maria's new registration | Inheritance: `Person` -> `Volunteer` / `Admin`; `role_required` + `require_role` on every admin page |
| 8-10 | **Registrations review** | Approve one (capacity re-checked under the activity lock), reject one with remarks (required), try approving again: refused; the volunteer window now shows Approved / Rejected + remarks and a notification | FR-3, FR-4 (`RejectSchema`), FR-6 audit, notifications |
| 10-11 | **Manage Activities / Locations / Volunteers** | Create an activity (past date refused), edit capacity below taken slots: refused; delete an activity with registrations: it is CANCELLED and registrants notified; reset a volunteer's password: temporary password shown once | FR-3 CRUD, FR-4, FR-6, FR-8 duplicates handled |
| 11-13 | **Reports** | Activity Participation with a status filter, Volunteer Hours, Download CSV (opens in Excel), Printable view (no navigation, Print button) | FR-7; **Template Method**: `BaseReport.generate()` = `fetch_data` -> `summarize` -> `format`; **Polymorphism**: `/registrations/report` calls `current_user.generate_report()` |
| 13-14 | **Audit Logs** | Filter by action (e.g. `REGISTRATION_APPROVED`), by username, by date; every demo action you just did is there | FR-6 complete trail, DAO: `AuditLogDAO.search()` / `count_search()` share `_filters()` |
| 14-15 | **Stop MySQL** (`.\scripts\mysql.ps1 stop`) and refresh | Friendly 503 page "Is MySQL running in XAMPP?" instead of a crash; start it again and the page recovers (reconnect) | FR-8; **Singleton**: `DatabaseManager` holds one configuration and one connection per thread |

## Code questions you should expect

- **Where is the SQL?** Only in `app/dao/*.py`, one class per table, every value a `%s`
  parameter (DAO pattern). Controllers and templates never touch the database.
- **Why a Singleton?** `DatabaseManager.__new__` returns the same instance; `configure()`
  points every DAO at one database; `transaction()` makes several DAO calls commit or roll
  back together (registration + audit + notifications).
- **Where is inheritance used?** `BaseEntity` -> abstract `Person` (`generate_report()`
  abstract) -> `Volunteer` / `Admin`. `Person.full_name`, `is_locked()` are shared; each
  subclass returns its own report.
- **Template Method?** `BaseReport.generate()` never changes; `SystemTotalsReport`,
  `ActivityParticipationReport`, `VolunteerHoursReport`, `VolunteerActivityReport` fill in the
  three steps.
- **How are slots never over-booked?** The activity row is locked (`FOR UPDATE`) before the
  count; parallel registrations queue up; the second sees the slot gone. The UNIQUE key on
  (activity, user) catches a duplicate that slips through and becomes a friendly 409.
- **Tests?** 532 unit + integration tests and 9 Playwright browser tests; CI runs ruff,
  mypy strict, pytest on MySQL 8 and the e2e suite on every pull request.

## If something goes wrong

- Page says 503: MySQL is not running -> `.\scripts\mysql.ps1`.
- Styles missing: `.\scripts\tailwind.ps1` to rebuild `app/static/css/app.css`.
- Locked out: wait 15 minutes, or log in as another demo account.
- Demo data looks odd: `python scripts\init_db.py` (drops and recreates the database) then `python seed.py`.
