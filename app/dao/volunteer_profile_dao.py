from __future__ import annotations

from typing import Any

from app.dao.base_dao import BaseDAO
from app.models import VolunteerProfile


class VolunteerProfileDAO(BaseDAO):
    """SQL for the volunteer_profiles table."""

    @staticmethod
    def to_model(row: dict[str, Any]) -> VolunteerProfile:
        return VolunteerProfile(
            id=row["id"],
            user_id=row["user_id"],
            address=row["address"],
            birth_date=row["birth_date"],
            emergency_contact_name=row["emergency_contact_name"],
            emergency_contact_phone=row["emergency_contact_phone"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def find_by_user_id(self, user_id: int) -> VolunteerProfile | None:
        row = self.db.fetch_one(
            "SELECT id, user_id, address, birth_date, emergency_contact_name, "
            "emergency_contact_phone, created_at, updated_at "
            "FROM volunteer_profiles WHERE user_id = %s",
            (user_id,),
        )
        return self.to_model(row) if row else None

    def insert(self, profile: VolunteerProfile) -> int:
        new_id = self.db.execute(
            "INSERT INTO volunteer_profiles (user_id, address, birth_date, "
            "emergency_contact_name, emergency_contact_phone) VALUES (%s, %s, %s, %s, %s)",
            (
                profile.user_id,
                profile.address,
                profile.birth_date,
                profile.emergency_contact_name,
                profile.emergency_contact_phone,
            ),
        )
        profile.id = new_id
        return new_id

    def update(self, profile: VolunteerProfile) -> bool:
        affected = self.db.execute(
            "UPDATE volunteer_profiles SET address = %s, birth_date = %s, "
            "emergency_contact_name = %s, emergency_contact_phone = %s WHERE user_id = %s",
            (
                profile.address,
                profile.birth_date,
                profile.emergency_contact_name,
                profile.emergency_contact_phone,
                profile.user_id,
            ),
        )
        return affected > 0
