from __future__ import annotations

from fastapi import APIRouter, Path, Query, Request

from lumen.api.deps import Connection, wake_task_runner
from lumen.schemas.common import ErrorResponse
from lumen.schemas.tasks import Task, TaskList
from lumen.services import tasks as service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskList, operation_id="listTasks")
def list_tasks(
    conn: Connection,
    active: bool = Query(default=False, description="Only pending and running tasks"),
    limit: int = Query(default=50, ge=1, le=500),
) -> TaskList:
    return TaskList(items=service.list_tasks(conn, active_only=active, limit=limit))


@router.get(
    "/{task_id}", response_model=Task, operation_id="getTask",
    responses={404: {"model": ErrorResponse}},
)  # fmt: skip
def get_task(conn: Connection, task_id: int = Path(ge=1)) -> Task:
    return service.get_task(conn, task_id)


@router.post(
    "/{task_id}/cancel", response_model=Task, operation_id="cancelTask",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)  # fmt: skip
def cancel_task(conn: Connection, task_id: int = Path(ge=1)) -> Task:
    return service.cancel_task(conn, task_id)


@router.post(
    "/{task_id}/retry", response_model=Task, operation_id="retryTask",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)  # fmt: skip
def retry_task(conn: Connection, request: Request, task_id: int = Path(ge=1)) -> Task:
    task = service.retry_task(conn, task_id)
    wake_task_runner(request)
    return task
