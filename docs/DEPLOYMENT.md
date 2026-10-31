# Deployment guide

GreenHands is a Flask application that talks to MySQL / MariaDB through PyMySQL. This
guide covers the setup used for the defense (Windows + XAMPP), what to change for a
small production install, and the checks to run before going live.

## 1. Defense setup (Windows 11 + XAMPP)

This is the configuration the project was built and tested on.

1. Install XAMPP (MariaDB 10.4+) and Python 3.12.
2. Clone the repository and create the virtual environment:
   ```powershell
   py -3.12 -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and set:
   - `SECRET_KEY`: a long random value (`python -c "import secrets; print(secrets.token_hex(32))"`)
   - `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`: the XAMPP MariaDB defaults are
     `127.0.0.1`, `3306`, `root`, empty password, `greenhands`
   - `SEED_ADMIN_PASSWORD`, `SEED_VOLUNTEER_PASSWORD`: passwords for the demo accounts
4. Start MySQL from the terminal: `.\scripts\mysql.ps1` (`stop` / `status` also work).
5. Create the schema: `python scripts\init_db.py` (or import `database/schema.sql` in
   phpMyAdmin). Existing databases: `python scripts\upgrade_db.py` adds new columns and keeps data.
6. Load demo data: `python seed.py` (add `--big` for 1,000 extra activities).
7. Build the CSS once: `.\scripts\tailwind.ps1`.
8. Run: `flask --app app run --debug` and open http://127.0.0.1:5000.

Uploaded profile photos are stored in `instance/uploads/` (outside the public static
folder); back that folder up together with the database.

## 2. Small production install (same machine or a LAN server)

Keep the same steps, then change the following.

| Setting | Development | Production |
|---|---|---|
| `FLASK_ENV` in `.env` | `development` | `production` (turns on `SESSION_COOKIE_SECURE`; needs HTTPS) |
| Database user | `root`, no password | A dedicated user with rights only on the `greenhands` database and a real password |
| Server | `flask run --debug` | A WSGI server, see below; never the debug server |
| Rate-limit storage | in-memory (`memory://`) | Fine for one process; for several processes set `RATELIMIT_STORAGE_URI` to a shared store |
| Secrets | `.env` on disk | `.env` with restricted file permissions, or real environment variables |

### WSGI server options

- **Waitress** (pure Python, works on Windows): `pip install waitress` then
  `waitress-serve --listen=0.0.0.0:8000 "app:create_app()"`. Put Apache (from XAMPP) or
  nginx in front of it for HTTPS and static files.
- **Apache + mod_wsgi** (XAMPP's Apache): possible, but it needs a mod_wsgi build that
  matches XAMPP's Apache and Python 3.12. The project brief asks for a decision before
  going this way; it is documented here for completeness only.
- **Linux**: gunicorn behind nginx is the usual pairing (`gunicorn "app:create_app()"`).

Create the database user in MySQL (replace the password):

```sql
CREATE USER 'greenhands'@'localhost' IDENTIFIED BY 'change-me';
GRANT SELECT, INSERT, UPDATE, DELETE ON greenhands.* TO 'greenhands'@'localhost';
FLUSH PRIVILEGES;
```

Then set `DB_USER=greenhands` and `DB_PASSWORD=change-me` in `.env`.

### HTTPS

The session cookie is marked `Secure` in production, so the site must be served over
HTTPS or logins will not stick. Terminate TLS in Apache / nginx and forward to the WSGI
server on localhost.

## 3. Pre-launch checklist

- [ ] `.\scripts\check.ps1` passes (ruff, format, mypy, pytest) and `pytest tests/e2e` is green.
- [ ] `.env` has a unique `SECRET_KEY`, a dedicated DB user, `FLASK_ENV=production`.
- [ ] `python scripts\upgrade_db.py` ran against the production database.
- [ ] CSS built (`.\scripts\tailwind.ps1`); `app/static/css/app.css` exists.
- [ ] `instance/uploads/` is writable by the server user and included in backups.
- [ ] A first admin account exists (`python seed.py` creates `admin`; change its password after login).
- [ ] Health check answers: `GET /health` returns 200 while MySQL is up and the friendly 503 page when it is down.

## 4. Backups and recovery

- Database: `mysqldump -u root greenhands > greenhands-YYYY-MM-DD.sql` (XAMPP's `mysql\bin`).
- Photos: copy `instance/uploads/`.
- Restore: `python scripts\init_db.py` (empty schema) then `mysql -u root greenhands < backup.sql`, or import the dump in phpMyAdmin.

## 5. Operations notes

- Logs are JSON lines on stdout (`app/logging_setup`), one per request-level event, with
  `user_id` and `action` fields; redirect stdout to a file or a log collector.
- The audit trail (`audit_logs` table, Audit Logs page) records every business change;
  it is append-only by design and is not cleaned up automatically.
- Login lockout: 5 failures lock an account for 15 minutes (`Config.LOGIN_*`); an admin can
  reset a volunteer's password from the Volunteers page.
