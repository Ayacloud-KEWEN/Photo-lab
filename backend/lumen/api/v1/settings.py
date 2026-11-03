from __future__ import annotations

from fastapi import APIRouter

from lumen.api.deps import Connection
from lumen.schemas.settings import AppSettings, AppSettingsUpdate
from lumen.services import settings as service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettings, operation_id="getSettings")
def get_settings(conn: Connection) -> AppSettings:
    return service.get_settings(conn)


@router.patch("", response_model=AppSettings, operation_id="updateSettings")
def update_settings(conn: Connection, body: AppSettingsUpdate) -> AppSettings:
    return service.update_settings(conn, body)
