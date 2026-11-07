from __future__ import annotations

from fastapi import APIRouter, Request

from lumen.api.deps import Connection, wake_task_runner
from lumen.core.config import Settings
from lumen.schemas.cache import CacheStatus, MoveCacheRequest
from lumen.schemas.common import ErrorResponse
from lumen.schemas.tasks import Task
from lumen.services import cache as service
from lumen.services import tasks as tasks_service

router = APIRouter(prefix="/cache", tags=["cache"])


@router.get("", response_model=CacheStatus, operation_id="getCacheStatus")
def get_cache_status(conn: Connection, request: Request) -> CacheStatus:
    settings: Settings = request.app.state.settings
    return service.status(conn, settings)


@router.post(
    "/move", response_model=Task, status_code=202, operation_id="moveCache",
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse},
               422: {"model": ErrorResponse}},
)  # fmt: skip
def move_cache(conn: Connection, request: Request, body: MoveCacheRequest) -> Task:
    """Move thumbnails and previews to another folder (a background task)."""
    settings: Settings = request.app.state.settings
    task_id = service.start_move(conn, settings, body.folder)
    wake_task_runner(request)
    return tasks_service.get_task(conn, task_id)
