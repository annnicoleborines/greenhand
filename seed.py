"""Seed the database with demo data through the DAO layer.

Usage:
    python seed.py            # roles exist from schema.sql; adds 1 admin, 4 volunteers,
                              # 3 locations, 6 activities, 10 registrations in every status
                              # with the matching notifications and audit trail.
                              # Safe to run again (skips what already exists).
    python seed.py --big      # also adds 1,000 extra activities for the performance check
                              # (NFR: CRUD on 1,000 records within 2 seconds).

Passwords come from .env (SEED_ADMIN_PASSWORD / SEED_VOLUNTEER_PASSWORD) and are
never printed.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import date, datetime, time, timedelta
from typing import Any

from dotenv import load_dotenv

from app.auth.passwords import hash_password
from app.dao import (
    ActivityDAO,
    AuditLogDAO,
    LocationDAO,
    NotificationDAO,
    RegistrationDAO,
    RoleDAO,
    UserDAO,
    VolunteerProfileDAO,
)
from app.database import DatabaseManager
from app.models import (
    Activity,
    ActivityStatus,
    Admin,
    AuditLog,
    Location,
    Notification,
    Person,
    Registration,
    RegistrationStatus,
    RoleName,
    Volunteer,
    VolunteerProfile,
)

load_dotenv()


class Seeder:
    """Small helper object so each step can share the DAOs."""

    def __init__(self) -> None:
        self.db = DatabaseManager()
        self.roles = RoleDAO(self.db)
        self.users = UserDAO(self.db)
        self.profiles = VolunteerProfileDAO(self.db)
        self.locations = LocationDAO(self.db)
        self.activities = ActivityDAO(self.db)
        self.registrations = RegistrationDAO(self.db)
        self.notifications = NotificationDAO(self.db)
        self.audit = AuditLogDAO(self.db)

    # ---- users ----
    def ensure_user(
        self,
        *,
        role: RoleName,
        username: str,
        email: str,
        first_name: str,
        last_name: str,
        phone: str,
        password: str,
    ) -> Person:
        existing = self.users.find_by_username(username)
        if existing is not None:
            return existing
        role_row = self.roles.find_by_name(role)
        common: dict[str, Any] = {
            "role_id": role_row.id or 0,
            "role_name": role,
            "username": username,
            "email": email,
            "password_hash": hash_password(password),
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
        }
        with self.db.transaction():  # user + profile succeed or fail together
            if role == RoleName.ADMIN:
                admin = Admin(**common)
                self.users.insert(admin)
                return admin
            volunteer = Volunteer(**common)
            self.users.insert(volunteer)
            profile = VolunteerProfile(
                user_id=volunteer.id or 0,
                address="123 Example Street, Green City",
                birth_date=date(2000, 1, 15),
                emergency_contact_name="Emergency Contact",
                emergency_contact_phone="0917-000-0000",
            )
            self.profiles.insert(profile)
            volunteer.profile = profile
            return volunteer

    # ---- locations ----
    def ensure_location(self, name: str, address: str, details: str) -> Location:
        existing = self.locations.find_by_name(name)
        if existing is not None:
            return existing
        location = Location(location_name=name, address=address, details=details)
        self.locations.insert(location)
        return location

    # ---- activities ----
    def ensure_activity(
        self,
        *,
        admin: Person,
        location: Location,
        title: str,
        days_from_now: int,
        max_volunteers: int,
        status: ActivityStatus,
    ) -> Activity:
        existing = self.activities.find_by_title(title)
        if existing is not None:
            return existing
        activity = Activity(
            created_by=admin.id or 0,
            location_id=location.id or 0,
            title=title,
            description=(
                f"Join us at {location.location_name} to plant native seedlings and "
                "help restore green cover in our community."
            ),
            activity_date=date.today() + timedelta(days=days_from_now),
            start_time=time(7, 0),
            end_time=time(11, 0),
            max_volunteers=max_volunteers,
            requirements="Bring water, wear closed shoes and a hat. Gloves provided.",
            status=status,
        )
        activity.validate()
        with self.db.transaction():
            self.activities.insert(activity)
            self.audit.insert(
                AuditLog(
                    user_id=admin.id or 0,
                    action="ACTIVITY_CREATED",
                    entity="activity",
                    record_reference=activity.id,
                    details=f"Created activity {activity.title}.",
                )
            )
        return activity

    # ---- registrations ----
    def ensure_registration(
        self,
        *,
        volunteer: Person,
        activity: Activity,
        status: RegistrationStatus,
        admin: Person,
        remarks: str | None = None,
    ) -> bool:
        """One demo registration with the notifications and audit entries the real flow
        would have written (Phases 5-7). Returns True when it was inserted."""
        existing = self.registrations.find_by_activity_and_user(activity.id or 0, volunteer.id or 0)
        if existing is not None:
            return False
        reviewed = status in {
            RegistrationStatus.APPROVED,
            RegistrationStatus.REJECTED,
            RegistrationStatus.COMPLETED,
        }
        now = datetime.now().replace(microsecond=0)
        when = activity.activity_date.isoformat()
        with self.db.transaction():
            registration = Registration(
                activity_id=activity.id or 0, user_id=volunteer.id or 0, status=status
            )
            self.registrations.insert(registration)
            self.audit.insert(
                AuditLog(
                    user_id=volunteer.id or 0,
                    action="REGISTRATION_CREATED",
                    entity="registration",
                    record_reference=registration.id,
                    details=f"Registered for activity {activity.title} (PENDING).",
                )
            )
            self.notifications.insert(
                Notification(
                    user_id=admin.id or 0,
                    type="REGISTRATION_SUBMITTED",
                    message=(
                        f"{volunteer.full_name} registered for {activity.title} on {when}. "
                        "Review it under Registrations."
                    ),
                )
            )
            if reviewed:
                review_status = (
                    RegistrationStatus.APPROVED
                    if status == RegistrationStatus.COMPLETED
                    else status
                )
                self.registrations.review(
                    registration.id or 0,
                    status=review_status,
                    reviewed_by=admin.id or 0,
                    reviewed_at=now - timedelta(days=1),
                    remarks=remarks,
                )
                if review_status == RegistrationStatus.APPROVED:
                    message = (
                        f"Your registration for {activity.title} on {when} was approved. "
                        "See you there!"
                    )
                    action = "REGISTRATION_APPROVED"
                else:
                    message = (
                        f"Your registration for {activity.title} on {when} was rejected. "
                        f"Remarks: {remarks}"
                    )
                    action = "REGISTRATION_REJECTED"
                self.notifications.insert(
                    Notification(user_id=volunteer.id or 0, type=action, message=message)
                )
                self.audit.insert(
                    AuditLog(
                        user_id=admin.id or 0,
                        action=action,
                        entity="registration",
                        record_reference=registration.id,
                        details=f"{action.split('_')[1].capitalize()} "
                        f"{volunteer.full_name} for {activity.title}.",
                    )
                )
            if status == RegistrationStatus.COMPLETED:
                self.registrations.set_status(registration.id or 0, status)
            if status == RegistrationStatus.CANCELLED:
                self.registrations.set_status(registration.id or 0, status)
                self.audit.insert(
                    AuditLog(
                        user_id=volunteer.id or 0,
                        action="REGISTRATION_CANCELLED",
                        entity="registration",
                        record_reference=registration.id,
                        details=(
                            f"Cancelled registration for {activity.title} (PENDING -> CANCELLED)."
                        ),
                    )
                )
                self.notifications.insert(
                    Notification(
                        user_id=admin.id or 0,
                        type="REGISTRATION_CANCELLED",
                        message=(
                            f"{volunteer.full_name} cancelled their pending registration "
                            f"for {activity.title} on {when}."
                        ),
                    )
                )
        return True

    def seed_big(self, admin: Person, locations: list[Location], count: int = 1000) -> int:
        """Bulk activities for the performance requirement. Inserted in one transaction."""
        rng = random.Random(42)  # fixed seed = same demo data every time
        created = 0
        with self.db.transaction():
            for n in range(1, count + 1):
                title = f"Bulk Planting Session #{n:04d}"
                if self.activities.find_by_title(title) is not None:
                    continue
                location = rng.choice(locations)
                start_hour = rng.choice([6, 7, 8, 13, 14])
                self.activities.insert(
                    Activity(
                        created_by=admin.id or 0,
                        location_id=location.id or 0,
                        title=title,
                        description=f"Generated demo activity {n} at {location.location_name}.",
                        activity_date=date.today() + timedelta(days=rng.randint(-120, 180)),
                        start_time=time(start_hour, 0),
                        end_time=time(start_hour + 3, 0),
                        max_volunteers=rng.randint(5, 40),
                        requirements="Standard field kit.",
                        status=rng.choice(list(ActivityStatus)),
                    )
                )
                created += 1
        return created


def run(big: bool = False) -> None:
    admin_password = os.environ.get("SEED_ADMIN_PASSWORD")
    volunteer_password = os.environ.get("SEED_VOLUNTEER_PASSWORD")
    if not admin_password or not volunteer_password:
        msg = "Set SEED_ADMIN_PASSWORD and SEED_VOLUNTEER_PASSWORD in .env first."
        raise RuntimeError(msg)

    seeder = Seeder()
    admin = seeder.ensure_user(
        role=RoleName.ADMIN,
        username="admin",
        email="admin@greenhands.local",
        first_name="Nicole",
        last_name="Borines",
        phone="0917-111-1111",
        password=admin_password,
    )
    volunteers = [
        ("maria", "maria@example.com", "Maria", "Santos"),
        ("juan", "juan@example.com", "Juan", "Dela Cruz"),
        ("liza", "liza@example.com", "Liza", "Reyes"),
        ("paolo", "paolo@example.com", "Paolo", "Garcia"),
    ]
    people: dict[str, Person] = {}
    for i, (username, email, first, last) in enumerate(volunteers, start=2):
        people[username] = seeder.ensure_user(
            role=RoleName.VOLUNTEER,
            username=username,
            email=email,
            first_name=first,
            last_name=last,
            phone=f"0917-{i:03d}-{i:04d}",
            password=volunteer_password,
        )

    riverside = seeder.ensure_location(
        "Riverside Park", "Riverside Drive, Green City", "Meet at the main gate. Parking available."
    )
    hillside = seeder.ensure_location(
        "Hillside Reserve", "Km 12, Mountain Road, Green City", "Steep trail, wear sturdy shoes."
    )
    campus = seeder.ensure_location(
        "Community Campus Grounds", "University Avenue, Green City", "Flat ground, family friendly."
    )

    plan = [
        ("Riverbank Reforestation Drive", riverside, 7, 25, ActivityStatus.OPEN),
        ("Hillside Native Tree Planting", hillside, 14, 15, ActivityStatus.OPEN),
        ("Campus Green Corridor", campus, 21, 40, ActivityStatus.OPEN),
        ("Mangrove Seedling Day", riverside, 30, 20, ActivityStatus.OPEN),
        ("Trail Restoration Weekend", hillside, -10, 12, ActivityStatus.COMPLETED),
        ("Storm Recovery Replanting", campus, 3, 10, ActivityStatus.CLOSED),
    ]
    acts: dict[str, Activity] = {}
    for title, location, days, max_vols, status in plan:
        acts[title] = seeder.ensure_activity(
            admin=admin,
            location=location,
            title=title,
            days_from_now=days,
            max_volunteers=max_vols,
            status=status,
        )

    # Registrations in every status, so every screen has something to show:
    # (volunteer, activity, status, remarks)
    demo_registrations = [
        ("maria", "Riverbank Reforestation Drive", RegistrationStatus.APPROVED, None),
        ("maria", "Hillside Native Tree Planting", RegistrationStatus.PENDING, None),
        ("maria", "Trail Restoration Weekend", RegistrationStatus.COMPLETED, None),
        ("juan", "Riverbank Reforestation Drive", RegistrationStatus.PENDING, None),
        ("juan", "Campus Green Corridor", RegistrationStatus.REJECTED, "Age requirement not met."),
        ("juan", "Trail Restoration Weekend", RegistrationStatus.COMPLETED, None),
        ("liza", "Hillside Native Tree Planting", RegistrationStatus.APPROVED, None),
        ("liza", "Riverbank Reforestation Drive", RegistrationStatus.CANCELLED, None),
        ("paolo", "Campus Green Corridor", RegistrationStatus.PENDING, None),
        ("paolo", "Mangrove Seedling Day", RegistrationStatus.APPROVED, None),
    ]
    inserted = 0
    for username, title, reg_status, remarks in demo_registrations:
        if seeder.ensure_registration(
            volunteer=people[username],
            activity=acts[title],
            status=reg_status,
            admin=admin,
            remarks=remarks,
        ):
            inserted += 1

    print(
        "Seed complete: admin, 4 volunteers, 3 locations, 6 activities, "
        f"{inserted} new registrations (10 in total) with notifications and audit entries."
    )
    if big:
        created = seeder.seed_big(admin, [riverside, hillside, campus])
        print(f"Big seed: {created} extra activities inserted.")
    print("Log in as 'admin' or 'maria' with the passwords from your .env.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo data.")
    parser.add_argument("--big", action="store_true", help="add 1,000 extra activities")
    args = parser.parse_args()
    run(big=args.big)
    return 0


if __name__ == "__main__":
    sys.exit(main())
