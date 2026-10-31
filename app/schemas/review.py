"""Pydantic schema for the admin's reject form (FR-4: validate before saving).

Rejecting a registration requires remarks: the volunteer reads them in their
notification, so a blank or one-word reason is refused. Approving needs no form.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

REMARKS_MIN = 3
REMARKS_MAX = 500
REMARKS_MESSAGE = f"Remarks are required to reject ({REMARKS_MIN}-{REMARKS_MAX} characters)."


class RejectSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    remarks: str = Field(min_length=REMARKS_MIN, max_length=REMARKS_MAX)
