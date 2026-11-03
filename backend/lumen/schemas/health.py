from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DatabaseHealth(BaseModel):
    status: Literal["ok", "error"]
    schema_version: int
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app_version: str
    api_version: str
    uptime_seconds: float
    database: DatabaseHealth
