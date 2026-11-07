from __future__ import annotations

from fastapi import APIRouter, Query, Request

from lumen.api.deps import Connection, wake_task_runner
from lumen.geo.tasks import GEO_TASK, needs_locating
from lumen.schemas.duplicates import DuplicateReport, MergeRequest, MergeResult
from lumen.schemas.tasks import Task
from lumen.services import duplicates as service
from lumen.services import tasks as task_service
from lumen.tasks import queue

router = APIRouter(prefix="/duplicates", tags=["duplicates"])


@router.get("", response_model=DuplicateReport, operation_id="listDuplicates")
def list_duplicates(
    conn: Connection,
    limit: int = Query(default=500, ge=1, le=5000),
    kind: service.DuplicateKind = Query(default="identical"),
) -> DuplicateReport:
    """Photos listed more than once: their files are identical copies, or (``copies``) the
    same shot saved again in another quality (recompressed, converted or resized)."""
    return service.find_duplicates(conn, limit=limit, kind=kind)


@router.post(
    "/merge-all", response_model=Task, status_code=202, operation_id="mergeAllDuplicates"
)
def merge_all(
    conn: Connection, request: Request, kind: service.DuplicateKind = Query(default="identical")
) -> Task:
    """Merge every group into its suggested copy, as a background task (no file touched)."""
    task_id = queue.enqueue(conn, service.MERGE_ALL_TASK, payload={"kind": kind})
    wake_task_runner(request)
    return task_service.get_task(conn, task_id)


@router.post("/merge", response_model=MergeResult, operation_id="mergeDuplicates")
def merge_duplicates(conn: Connection, request: Request, body: MergeRequest) -> MergeResult:
    """Fold copies into one photo with several file locations. No file is touched."""
    result = service.merge_duplicates(conn, body)
    if needs_locating(conn):  # a copy's location may now belong to the kept photo
        queue.enqueue(conn, GEO_TASK)
        wake_task_runner(request)
    return result
