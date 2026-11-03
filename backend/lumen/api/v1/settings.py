from __future__ import annotations

from fastapi import APIRouter, Request

from lumen.ai.engine import model_downloaded, torch_installed
from lumen.ai.models import get_spec
from lumen.ai.pipeline import AI_DOWNLOAD_TASK, AI_INDEX_TASK
from lumen.api.deps import Connection, wake_task_runner
from lumen.schemas.settings import AppSettings, AppSettingsUpdate
from lumen.services import settings as service
from lumen.tasks import queue

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettings, operation_id="getSettings")
def get_settings(conn: Connection) -> AppSettings:
    return service.get_settings(conn)


@router.patch("", response_model=AppSettings, operation_id="updateSettings")
def update_settings(conn: Connection, request: Request, body: AppSettingsUpdate) -> AppSettings:
    updated = service.update_settings(conn, body)
    if updated.ai_enabled and (body.ai_enabled or body.ai_model) and torch_installed():
        # Enabling AI (or switching model) downloads the model if needed, then indexes.
        downloaded = model_downloaded(get_spec(updated.ai_model))
        queue.enqueue(conn, AI_INDEX_TASK if downloaded else AI_DOWNLOAD_TASK)
        wake_task_runner(request)
    return updated
