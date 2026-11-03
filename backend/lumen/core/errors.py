"""Domain errors raised by services and mapped to HTTP responses by the API layer."""

from __future__ import annotations

from typing import Any


class LumenError(Exception):
    """Base class for expected, user-facing errors."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(LumenError):
    status_code = 404
    code = "not_found"


class ConflictError(LumenError):
    status_code = 409
    code = "conflict"


class InvalidPathError(LumenError):
    status_code = 422
    code = "invalid_path"


class DatabaseMigrationError(Exception):
    """The database schema cannot be brought to the expected version."""
