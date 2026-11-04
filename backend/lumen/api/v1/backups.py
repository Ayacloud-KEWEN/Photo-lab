from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from lumen.ai.index import index
from lumen.api.deps import Connection, get_database, wake_task_runner
from lumen.core.config import Settings
from lumen.core.errors import ConflictError, LumenError
from lumen.core.reveal import reveal_in_explorer
from lumen.db.connection import bump_write_generation
from lumen.db.migrator import current_version
from lumen.geo.tasks import GEO_TASK, needs_locating
from lumen.schemas.backups import (
    BackupInfo,
    BackupList,
    RestoreRequest,
    RestoreResult,
    RevealRequest,
)
from lumen.services import backups as service
from lumen.tasks import queue
from lumen.tasks.runner import RunnerBusyError, TaskRunner

router = APIRouter(prefix="/backups", tags=["backups"])


@router.get("", response_model=BackupList, operation_id="listBackups")
def list_backups(conn: Connection, request: Request) -> BackupList:
    settings: Settings = request.app.state.settings
    return service.list_backups(conn, settings)


@router.post("", response_model=BackupInfo, status_code=201, operation_id="createBackup")
def create_backup(conn: Connection, request: Request) -> BackupInfo:
    settings: Settings = request.app.state.settings
    return service.create_backup(conn, settings, "manual")


@router.post("/reveal", status_code=204, operation_id="revealBackup")
def reveal_backup(conn: Connection, request: Request, body: RevealRequest) -> None:
    settings: Settings = request.app.state.settings
    reveal_in_explorer(service.find_backup(conn, settings, body.name))


@router.post("/restore", response_model=RestoreResult, operation_id="restoreBackup")
def restore_backup(conn: Connection, request: Request, body: RestoreRequest) -> RestoreResult:
    settings: Settings = request.app.state.settings
    if body.name:
        source = service.find_backup(conn, settings, body.name)
    elif body.path:
        source = Path(body.path)
    else:
        raise LumenError("Choose a backup to restore")
    conn.close()  # the database is about to be replaced: hold no connection

    db = get_database(request)
    runner: TaskRunner | None = request.app.state.task_runner
    try:
        if runner is None:
            restored, safety = service.restore(db, settings, source)
        else:
            with runner.paused():
                restored, safety = service.restore(db, settings, source)
    except RunnerBusyError as exc:
        raise ConflictError("A background task is busy; try again in a moment") from exc
    index.clear()
    bump_write_generation()  # cached library views are out of date
    with db.session() as fresh:
        if needs_locating(fresh):
            queue.enqueue(fresh, GEO_TASK)
        version = current_version(fresh)
    wake_task_runner(request)
    return RestoreResult(restored=restored, safety_backup=safety, schema_version=version)
