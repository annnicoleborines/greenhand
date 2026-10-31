"""BaseEntity: fields and behaviour shared by every domain object (Inheritance).

Every table has an `id`; most also have `created_at` / `updated_at`.
`to_dict()` is the one place that turns a model into a plain dict for
templates, JSON responses and CSV export.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any


@dataclass(kw_only=True)
class BaseEntity:
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = field(default=None, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Plain dict with JSON-friendly values (enums -> text, dates -> ISO strings)."""
        return {key: _plain(value) for key, value in asdict(self).items()}

    @property
    def is_new(self) -> bool:
        return self.id is None


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, timedelta):  # PyMySQL returns TIME columns as timedelta
        return str(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value
