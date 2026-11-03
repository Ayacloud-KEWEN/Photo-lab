"""Read access to assets, their renditions and duplicate files."""

from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
from pathlib import Path

from lumen.core.errors import LumenError, NotFoundError
from lumen.media import thumbnails
from lumen.media.fingerprint import fingerprint_digest
from lumen.media.formats import format_for
from lumen.schemas.assets import (
    AssetDetail,
    AssetFile,
    AssetLocation,
    AssetMetadata,
    AssetPage,
    AssetSummary,
    DuplicateFile,
    DuplicateGroup,
    DuplicateReport,
    RenditionVariant,
)

logger = logging.getLogger(__name__)


class RenditionUnavailableError(LumenError):
    status_code = 404
    code = "rendition_unavailable"


def _version(fingerprint: str | None) -> str:
    return fingerprint_digest(fingerprint)[:16] if fingerprint else ""


def _encode_cursor(capture_time: str, asset_id: int) -> str:
    raw = json.dumps([capture_time, asset_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        capture_time, asset_id = json.loads(base64.urlsafe_b64decode(padded))
        return str(capture_time), int(asset_id)
    except (ValueError, TypeError) as exc:
        raise LumenError("Invalid cursor") from exc


def list_assets(
    conn: sqlite3.Connection, *, storage_root_id: int | None, cursor: str | None, limit: int
) -> AssetPage:
    """Assets with a rendered cover, newest capture first (keyset pagination)."""
    clauses = ["a.capture_time IS NOT NULL"]
    params: list[object] = []
    if storage_root_id is not None:
        clauses.append("c.storage_root_id = ?")
        params.append(storage_root_id)
    if cursor:
        capture_time, asset_id = _decode_cursor(cursor)
        clauses.append("(a.capture_time, a.id) < (?, ?)")
        params.extend([capture_time, asset_id])

    rows = conn.execute(
        f"""
        SELECT a.id, a.media_type, a.capture_time, a.rating, a.is_favorite,
               c.file_name, c.fingerprint, m.width, m.height, m.duration_ms,
               (SELECT GROUP_CONCAT(ext, ',') FROM (
                    SELECT DISTINCT UPPER(f.extension) AS ext FROM media_files f
                    WHERE f.asset_id = a.id AND f.file_role != 'sidecar' ORDER BY ext
               )) AS formats
        FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
             AND c.ingest_state = 'done' AND c.status = 'present'
        LEFT JOIN media_metadata m ON m.file_id = c.id
        WHERE {" AND ".join(clauses)}
        ORDER BY a.capture_time DESC, a.id DESC
        LIMIT ?
        """,
        (*params, limit + 1),
    ).fetchall()

    items = [
        AssetSummary(
            id=row["id"],
            media_type=row["media_type"],
            capture_time=row["capture_time"],
            rating=row["rating"],
            is_favorite=bool(row["is_favorite"]),
            file_name=row["file_name"],
            formats=(row["formats"] or "").split(",") if row["formats"] else [],
            width=row["width"],
            height=row["height"],
            duration_ms=row["duration_ms"],
            rendition_version=_version(row["fingerprint"]),
        )
        for row in rows[:limit]
    ]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(last["capture_time"], int(last["id"]))
    return AssetPage(items=items, next_cursor=next_cursor)


def _file_rows(conn: sqlite3.Connection, asset_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT f.*, r.path AS root_path FROM media_files f
        JOIN storage_roots r ON r.id = f.storage_root_id
        WHERE f.asset_id = ?
        ORDER BY CASE f.file_role WHEN 'primary' THEN 0 WHEN 'companion' THEN 1 ELSE 2 END, f.id
        """,
        (asset_id,),
    ).fetchall()


def get_asset(conn: sqlite3.Connection, asset_id: int) -> AssetDetail:
    asset = conn.execute("SELECT * FROM media_assets WHERE id = ?", (asset_id,)).fetchone()
    if asset is None:
        raise NotFoundError("Asset not found", details={"id": asset_id})
    files = _file_rows(conn, asset_id)

    # Metadata of the primary file, falling back to the cover.
    meta_row = conn.execute(
        """
        SELECT m.* FROM media_metadata m JOIN media_files f ON f.id = m.file_id
        WHERE f.asset_id = ? AND f.file_role != 'sidecar'
        ORDER BY f.file_role = 'primary' DESC, f.id = ? DESC LIMIT 1
        """,
        (asset_id, asset["cover_file_id"]),
    ).fetchone()
    metadata = (
        AssetMetadata(**{k: meta_row[k] for k in AssetMetadata.model_fields}) if meta_row else
        AssetMetadata()
    )  # fmt: skip
    location_row = conn.execute(
        "SELECT * FROM media_locations WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    cover = next((f for f in files if f["id"] == asset["cover_file_id"]), None)

    return AssetDetail(
        id=asset["id"],
        uuid=asset["uuid"],
        media_type=asset["media_type"],
        capture_time=asset["capture_time"],
        rating=asset["rating"],
        is_favorite=bool(asset["is_favorite"]),
        notes=asset["notes"],
        rendition_version=_version(cover["fingerprint"]) if cover else None,
        metadata=metadata,
        location=AssetLocation(
            latitude=location_row["latitude"],
            longitude=location_row["longitude"],
            altitude_m=location_row["altitude_m"],
            source=location_row["source"],
        )
        if location_row
        else None,
        files=[
            AssetFile(
                id=f["id"],
                storage_root_id=f["storage_root_id"],
                role=f["file_role"],
                path=os.path.join(f["root_path"], f["relative_path"]),
                relative_path=f["relative_path"],
                size_bytes=f["size_bytes"],
                status=f["status"],
                ingest_state=f["ingest_state"],
                ingest_error=f["ingest_error"],
                fingerprint=f["fingerprint"],
            )
            for f in files
        ],
    )


def rendition_path(
    conn: sqlite3.Connection, cache_dir: Path, asset_id: int, variant: RenditionVariant,
    *, ffmpeg: str | None,
) -> Path:  # fmt: skip
    """Path of the asset's thumbnail/preview, re-rendering it if the cache was cleared."""
    row = conn.execute(
        """
        SELECT c.fingerprint, c.relative_path, c.extension, c.status, r.path AS root_path
        FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
        JOIN storage_roots r ON r.id = c.storage_root_id
        WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("Asset not found", details={"id": asset_id})
    if not row["fingerprint"]:
        raise RenditionUnavailableError("Asset has not been processed yet")

    target = thumbnails.rendition_paths(cache_dir, row["fingerprint"])
    path = target.thumb if variant == "thumb" else target.preview
    if path.exists():
        return path

    media_format = format_for(row["extension"])
    source = Path(row["root_path"]) / row["relative_path"]
    if media_format is None or row["status"] != "present" or not source.exists():
        raise RenditionUnavailableError("Original file is not available to render a preview")
    try:
        thumbnails.render(source, media_format, target, ffmpeg=ffmpeg)
    except (thumbnails.RenderError, OSError) as exc:
        logger.warning("on-demand render failed", extra={"asset_id": asset_id, "error": str(exc)})
        raise RenditionUnavailableError(f"Cannot render preview: {exc}") from exc
    return path


def find_duplicates(conn: sqlite3.Connection, *, limit: int) -> DuplicateReport:
    groups_rows = conn.execute(
        """
        SELECT fingerprint, MAX(size_bytes) AS size_bytes, COUNT(*) AS copies
        FROM media_files
        WHERE fingerprint IS NOT NULL AND status = 'present' AND file_role != 'sidecar'
        GROUP BY fingerprint
        HAVING COUNT(*) > 1
        ORDER BY MAX(size_bytes) * (COUNT(*) - 1) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    groups: list[DuplicateGroup] = []
    reclaimable = 0
    for group in groups_rows:
        files = conn.execute(
            """
            SELECT f.id, f.asset_id, f.storage_root_id, f.relative_path, r.path AS root_path
            FROM media_files f JOIN storage_roots r ON r.id = f.storage_root_id
            WHERE f.fingerprint = ? AND f.status = 'present' AND f.file_role != 'sidecar'
            ORDER BY f.id
            """,
            (group["fingerprint"],),
        ).fetchall()
        groups.append(
            DuplicateGroup(
                fingerprint=group["fingerprint"],
                size_bytes=group["size_bytes"],
                files=[
                    DuplicateFile(
                        file_id=f["id"],
                        asset_id=f["asset_id"],
                        storage_root_id=f["storage_root_id"],
                        path=os.path.join(f["root_path"], f["relative_path"]),
                    )
                    for f in files
                ],
            )
        )
        reclaimable += int(group["size_bytes"]) * (int(group["copies"]) - 1)
    return DuplicateReport(groups=groups, reclaimable_bytes=reclaimable)
