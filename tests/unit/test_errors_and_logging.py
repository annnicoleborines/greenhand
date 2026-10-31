from __future__ import annotations

import json
import logging

from app.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.logging_config import JsonFormatter


def test_error_status_codes() -> None:
    assert ValidationError("bad").status_code == 422
    assert NotFoundError("missing").status_code == 404
    assert ConflictError("dup").status_code == 409
    assert ForbiddenError("no").status_code == 403


def test_validation_error_carries_field_errors() -> None:
    err = ValidationError("Invalid input", {"email": "already taken"})
    assert err.message == "Invalid input"
    assert err.errors == {"email": "already taken"}


def test_json_formatter_outputs_one_json_object() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.user_id = 7
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["user_id"] == 7
