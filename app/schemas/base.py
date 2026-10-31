"""Helper that turns Pydantic errors into our typed ValidationError.

Services call `validate(SchemaClass, form_data)`; controllers never see Pydantic.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.errors import ValidationError


def validate[SchemaT: BaseModel](
    schema: type[SchemaT], data: dict[str, Any], *, context: dict[str, Any] | None = None
) -> SchemaT:
    """Validate raw form data; raise ValidationError with one message per field.

    `context` is handed to the schema's validators (`info.context`). Schemas use it
    for facts the form itself cannot know, such as today's date or whether the
    record is being created or edited.
    """
    try:
        return schema.model_validate(data, context=context)
    except PydanticValidationError as exc:
        errors: dict[str, str] = {}
        for err in exc.errors():
            field = ".".join(str(part) for part in err["loc"]) or "form"
            # Pydantic prefixes custom messages with "Value error, "; strip it for users.
            message = err["msg"].removeprefix("Value error, ")
            errors.setdefault(field, message)
        raise ValidationError("Please fix the highlighted fields.", errors) from exc
