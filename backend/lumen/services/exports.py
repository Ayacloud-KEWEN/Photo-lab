"""Starting exports and reporting on them (the work itself: ``lumen.library.exports``)."""

from __future__ import annotations

import sqlite3

from lumen.core.errors import NotFoundError
from lumen.library.exports import EXPORT_TASK
from lumen.schemas.exports import ExportRequest, ExportResult, ExportStatus
from lumen.services.folders import check_folder
from lumen.services.tasks import get_task
from lumen.tasks import queue


def start_export(conn: sqlite3.Connection, request: ExportRequest) -> int:
    """Queue an export of ``request.asset_ids`` into an existing folder; returns the task id."""
    folder = check_folder(request.destination)
    payload = request.model_copy(update={"destination": str(folder)}).model_dump()
    return queue.enqueue(conn, EXPORT_TASK, payload=payload, unique=False)


def export_status(conn: sqlite3.Connection, task_id: int) -> ExportStatus:
    task = get_task(conn, task_id)
    if task.kind != EXPORT_TASK:
        raise NotFoundError("Export not found", details={"id": task_id})
    result = ExportResult.model_validate(task.result) if task.result else None
    return ExportStatus(task=task, result=result)
