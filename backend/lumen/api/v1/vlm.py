from __future__ import annotations

from fastapi import APIRouter, Request, status
from starlette.concurrency import run_in_threadpool

from lumen.api.deps import Connection, wake_task_runner
from lumen.core.config import Settings
from lumen.schemas.tasks import Task
from lumen.schemas.vlm import VlmDescribeRequest, VlmDescribeResult, VlmDownloadRequest, VlmStatus
from lumen.services import tasks as task_service
from lumen.services import vlm as service

router = APIRouter(prefix="/vlm", tags=["vlm"])


@router.get("/status", response_model=VlmStatus, operation_id="getVlmStatus")
async def get_status(conn: Connection, request: Request) -> VlmStatus:
    """The local vision-language model: files present, photos read and still to read."""
    settings: Settings = request.app.state.settings
    return await run_in_threadpool(service.status, conn, settings)


@router.post(
    "/describe", response_model=VlmDescribeResult, operation_id="describeAssets",
    status_code=status.HTTP_202_ACCEPTED,
)  # fmt: skip
def describe_assets(
    conn: Connection, request: Request, body: VlmDescribeRequest
) -> VlmDescribeResult:
    """Read these photos first (again if read before); ``fine`` uses the careful model."""
    queued, task_id = service.describe_later(conn, body.asset_ids, fine=body.fine)
    wake_task_runner(request)
    return VlmDescribeResult(queued=queued, task_id=task_id)


@router.post(
    "/download", response_model=Task, operation_id="downloadVlm",
    status_code=status.HTTP_202_ACCEPTED,
)  # fmt: skip
def download(conn: Connection, request: Request, body: VlmDownloadRequest) -> Task:
    """Download llama.cpp (if missing) and a model into the model folder (resumable)."""
    task_id = service.start_download(conn, body.model)
    wake_task_runner(request)
    return task_service.get_task(conn, task_id)
