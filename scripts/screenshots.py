"""Take the README screenshots with Playwright against a throw-away demo database.

Usage (MySQL running, `playwright install chromium` done once):

    python scripts\\screenshots.py            # writes docs/screenshots/*.png
    python scripts\\screenshots.py --db other # use another scratch database name

The script creates (or rebuilds) the database named by --db / SCREENSHOT_DB_NAME
(default `greenhands_demo`) from database/schema.sql, runs `seed.py` into it, starts
the real app on a free port with CSRF on, logs in as the demo admin and as Maria, and
saves one PNG per key page. Your development database is never touched.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pymysql
from dotenv import load_dotenv
from playwright.sync_api import Page, ViewportSize, sync_playwright
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env")

from init_db import import_schema  # noqa: E402

from app import create_app  # noqa: E402
from app.config import TestConfig  # noqa: E402
from app.database import DatabaseManager  # noqa: E402

OUT_DIR = ROOT / "docs" / "screenshots"
DESKTOP: ViewportSize = {"width": 1366, "height": 800}
PHONE: ViewportSize = {"width": 390, "height": 844}
# Fixed demo passwords for the scratch database only (never for a real deployment).
DEMO_ADMIN_PASSWORD = "Admin2026!"
DEMO_VOLUNTEER_PASSWORD = "Plant2026!"


def rebuild_database(name: str) -> None:
    raw = pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        charset="utf8mb4",
    )
    import_schema(raw, name)
    raw.close()


def seed(name: str) -> None:
    os.environ["SEED_ADMIN_PASSWORD"] = DEMO_ADMIN_PASSWORD
    os.environ["SEED_VOLUNTEER_PASSWORD"] = DEMO_VOLUNTEER_PASSWORD
    manager = DatabaseManager()
    manager.configure(database=name)
    import seed as seed_module  # noqa: PLC0415  (after the singleton points at the demo DB)

    seed_module.run(big=False)
    manager.close()


@contextmanager
def live_server() -> Iterator[str]:
    app = create_app(TestConfig, overrides={"WTF_CSRF_ENABLED": True})
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def log_in(page: Page, base: str, username: str, password: str) -> None:
    page.goto(f"{base}/login")
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Login").click()
    page.wait_for_url(lambda url: "/login" not in url)


def shoot(page: Page, base: str, path: str, name: str) -> None:
    page.goto(f"{base}{path}")
    page.wait_for_load_state("networkidle")
    target = OUT_DIR / f"{name}.png"
    page.screenshot(path=str(target), full_page=False)
    print(f"  {target.relative_to(ROOT)}")


def capture(base: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        desktop = browser.new_context(viewport=DESKTOP, device_scale_factor=1)
        page = desktop.new_page()
        shoot(page, base, "/login", "login")

        log_in(page, base, "admin", DEMO_ADMIN_PASSWORD)
        shoot(page, base, "/admin/dashboard", "admin-dashboard")
        shoot(page, base, "/admin/activities/", "admin-activities")
        shoot(page, base, "/admin/registrations/", "admin-registrations")
        shoot(page, base, "/admin/reports/activities", "admin-report-activities")
        shoot(page, base, "/admin/audit-logs/", "admin-audit-logs")
        page.get_by_role("button", name="Logout").click()

        log_in(page, base, "maria", DEMO_VOLUNTEER_PASSWORD)
        shoot(page, base, "/volunteer/dashboard", "volunteer-dashboard")
        shoot(page, base, "/activities", "volunteer-activities")
        shoot(page, base, "/activities/1", "volunteer-activity-detail")
        shoot(page, base, "/registrations", "volunteer-registrations")
        shoot(page, base, "/registrations/schedule", "volunteer-schedule")
        shoot(page, base, "/notifications", "volunteer-notifications")
        desktop.close()

        phone = browser.new_context(viewport=PHONE, device_scale_factor=1, is_mobile=True)
        page = phone.new_page()
        log_in(page, base, "maria", DEMO_VOLUNTEER_PASSWORD)
        shoot(page, base, "/activities", "phone-activities")
        page.get_by_role("button", name="Open menu").click()
        page.wait_for_timeout(300)  # let the slide-in finish
        page.screenshot(path=str(OUT_DIR / "phone-menu.png"))
        print(f"  {(OUT_DIR / 'phone-menu.png').relative_to(ROOT)}")
        phone.close()
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Take README screenshots.")
    parser.add_argument(
        "--db",
        default=os.environ.get("SCREENSHOT_DB_NAME", "greenhands_demo"),
        help="scratch database name (rebuilt from schema.sql)",
    )
    args = parser.parse_args()

    print(f"Rebuilding {args.db} from schema.sql and seeding demo data...")
    rebuild_database(args.db)
    seed(args.db)
    DatabaseManager().configure(database=args.db)
    print("Capturing screenshots...")
    with live_server() as base:
        capture(base)
    DatabaseManager().close()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
