from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Query

from lumen.api.deps import Connection
from lumen.core.errors import NotFoundError
from lumen.core.reveal import reveal_in_explorer
from lumen.schemas.cull import RejectedFiles, SimilarGroups, Suspects
from lumen.services import cull as service

router = APIRouter(tags=["cull"])


@router.get("/cull/similar", response_model=SimilarGroups, operation_id="listSimilarGroups")
def similar_groups(
    conn: Connection,
    window_minutes: int = Query(default=10, ge=1, le=24 * 60),
    similarity: float = Query(default=0.9, ge=0.5, le=0.995),
    pending_only: bool = Query(default=True),
    limit: int = Query(default=60, ge=1, le=5000, description="Groups returned (newest first)"),
) -> SimilarGroups:
    return service.similar_groups(
        conn,
        window_minutes=window_minutes,
        similarity=similarity,
        pending_only=pending_only,
        limit=limit,
    )


@router.get("/cull/suspects", response_model=Suspects, operation_id="listSuspects")
def suspects(conn: Connection, pending_only: bool = Query(default=True)) -> Suspects:
    return service.suspects(conn, pending_only=pending_only)


@router.get("/cull/rejected-files", response_model=RejectedFiles, operation_id="rejectedFiles")
def rejected_files(conn: Connection) -> RejectedFiles:
    return service.rejected_files(conn)


@router.post("/files/{file_id}/reveal", status_code=204, operation_id="revealFile")
def reveal_file(conn: Connection, file_id: int) -> None:
    row = conn.execute(
        "SELECT r.path, f.relative_path FROM media_files f "
        "JOIN storage_roots r ON r.id = f.storage_root_id WHERE f.id = ?",
        (file_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("File not found", details={"id": file_id})
    reveal_in_explorer(Path(os.path.join(row[0], row[1])))
