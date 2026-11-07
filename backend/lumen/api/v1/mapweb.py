from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from lumen.api.deps import Connection, wake_task_runner
from lumen.schemas.common import ErrorResponse
from lumen.schemas.mapweb import (
    MapWebPlan,
    MapWebPlanRequest,
    MapWebSendRequest,
    MapWebStatus,
    MapWebTestRequest,
)
from lumen.schemas.tasks import Task
from lumen.services import mapweb as service
from lumen.services import tasks as tasks_service
from lumen.tasks import queue

router = APIRouter(prefix="/mapweb", tags=["mapweb"])

ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse}, 502: {"model": ErrorResponse},
}  # fmt: skip


@router.post(
    "/test", response_model=MapWebStatus, operation_id="testMapWeb", responses=ERRORS
)
def test_mapweb(body: MapWebTestRequest) -> MapWebStatus:
    """Check that an address answers like MapWeb (before saving it)."""
    return service.test_connection(body.url)


@router.post(
    "/plan", response_model=MapWebPlan, operation_id="planMapWebSend", responses=ERRORS
)
def plan_send(conn: Connection, body: MapWebPlanRequest) -> MapWebPlan:
    """Where these photos would go on the map: existing footprints, new ones, skipped."""
    return service.plan_summary(conn, body.asset_ids, body.language)


@router.post(
    "/send", response_model=Task, status_code=202, operation_id="sendToMapWeb",
    responses=ERRORS,
)  # fmt: skip
def send(conn: Connection, request: Request, body: MapWebSendRequest) -> Task:
    """Send the photos to MapWeb as planned (a background task)."""
    task_id = service.start_send(conn, body, queue.enqueue)
    wake_task_runner(request)
    return tasks_service.get_task(conn, task_id)
