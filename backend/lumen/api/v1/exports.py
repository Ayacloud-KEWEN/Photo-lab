from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Request, status
from starlette.concurrency import run_in_threadpool

from lumen.api.deps import Connection, wake_task_runner
from lumen.schemas.common import ErrorResponse
from lumen.schemas.exports import ExportRequest, ExportStatus
from lumen.services import exports as service

router = APIRouter(tags=["exports"])

ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse, "description": "The folder is missing or not writable"},
}


@router.post(
    "/exports", response_model=ExportStatus, status_code=status.HTTP_202_ACCEPTED,
    operation_id="startExport", responses=ERRORS,
)  # fmt: skip
async def start_export(conn: Connection, request: Request, body: ExportRequest) -> ExportStatus:
    """Export photos, with their edits, as new JPEG files in a background task.

    Existing files are never replaced; videos are skipped.
    """
    task_id = await run_in_threadpool(service.start_export, conn, body)
    wake_task_runner(request)
    return service.export_status(conn, task_id)


@router.get(
    "/exports/{task_id}", response_model=ExportStatus, operation_id="getExport",
    responses=ERRORS,
)  # fmt: skip
def get_export(conn: Connection, task_id: int = Path(ge=1)) -> ExportStatus:
    """Progress of an export, and what it wrote once finished."""
    return service.export_status(conn, task_id)
