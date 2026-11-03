"""Read access to assets, their renditions and duplicate files."""

from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
from pathlib import Path

from lumen.core.errors import LumenError, NotFoundError
from lumen.library.live import CLIP_EXTENSION
from lumen.library.search import like_pattern, search_terms
from lumen.media import thumbnails
from lumen.media.fingerprint import fingerprint_digest
from lumen.media.formats import format_for
from lumen.schemas.assets import (
    AssetDetail,
    AssetFacets,
    AssetFile,
    AssetLocation,
    AssetMetadata,
    AssetPage,
    AssetQuery,
    AssetSummary,
    AssetTag,
    DuplicateFile,
    DuplicateGroup,
    DuplicateReport,
    FacetValue,
    MapPoint,
    MapPoints,
    RenditionVariant,
    Tag,
    Timeline,
    TimelineBucket,
)

logger = logging.getLogger(__name__)


class RenditionUnavailableError(LumenError):
    status_code = 404
    code = "rendition_unavailable"


def _version(fingerprint: str | None) -> str:
    return fingerprint_digest(fingerprint)[:16] if fingerprint else ""


# Every listable asset has a processed, present cover file and a capture time.
_BASE_FROM = """
    FROM media_assets a
    JOIN media_files c ON c.id = a.cover_file_id
         AND c.ingest_state = 'done' AND c.status = 'present'
    LEFT JOIN media_metadata m ON m.file_id = c.id
"""
_BASE_WHERE = "a.capture_time IS NOT NULL"

_ORDER = {
    "capture_desc": ("a.capture_time DESC, a.id DESC", "(a.capture_time, a.id) < (?, ?)"),
    "capture_asc": ("a.capture_time ASC, a.id ASC", "(a.capture_time, a.id) > (?, ?)"),
    "added_desc": ("a.id DESC", "a.id < ?"),
}


def _filters(query: AssetQuery) -> tuple[list[str], list[object]]:
    """WHERE clauses (ANDed) and their parameters for an asset query."""
    clauses = [_BASE_WHERE]
    params: list[object] = []
    for term in search_terms(query.q or ""):
        clauses.append(r"a.id IN (SELECT rowid FROM asset_search WHERE body LIKE ? ESCAPE '\')")
        params.append(like_pattern(term))
    if query.media_type:
        clauses.append("a.media_type = ?")
        params.append(query.media_type)
    if query.min_rating is not None:
        clauses.append("a.rating >= ?")
        params.append(query.min_rating)
    if query.favorite is not None:
        clauses.append("a.is_favorite = ?")
        params.append(int(query.favorite))
    if query.camera:
        clauses.append("m.camera_model = ?")
        params.append(query.camera)
    if query.lens:
        clauses.append("m.lens_model = ?")
        params.append(query.lens)
    if query.format:
        clauses.append(
            "EXISTS (SELECT 1 FROM media_files f WHERE f.asset_id = a.id "
            "AND f.extension = ? AND f.file_role != 'sidecar')"
        )
        params.append(query.format.lower().lstrip("."))
    if query.storage_root_id is not None:
        clauses.append("c.storage_root_id = ?")
        params.append(query.storage_root_id)
    for tag_id in query.tag_id:
        clauses.append(
            "EXISTS (SELECT 1 FROM media_tags mt WHERE mt.asset_id = a.id AND mt.tag_id = ?)"
        )
        params.append(tag_id)
    if query.date_from:
        clauses.append("a.capture_time >= ?")
        params.append(query.date_from)
    if query.date_to:
        clauses.append("a.capture_time < ?")
        params.append(query.date_to)
    if query.has_location is not None:
        clauses.append(
            ("" if query.has_location else "NOT ")
            + "EXISTS (SELECT 1 FROM media_locations l WHERE l.asset_id = a.id)"
        )
    return clauses, params


def _encode_cursor(sort: str, row: sqlite3.Row) -> str:
    key = [row["id"]] if sort == "added_desc" else [row["capture_time"], row["id"]]
    raw = json.dumps([sort, *key]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, sort: str) -> list[object]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        cursor_sort, *key = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError) as exc:
        raise LumenError("Invalid cursor") from exc
    if cursor_sort != sort or len(key) != (1 if sort == "added_desc" else 2):
        raise LumenError("Cursor does not match the requested sort order")
    return list(key)


_SUMMARY_COLUMNS = """
    a.id, a.media_type, a.capture_time, a.rating, a.is_favorite,
    c.file_name, c.extension, c.fingerprint, m.width, m.height, m.duration_ms,
    EXISTS (SELECT 1 FROM media_files lf WHERE lf.asset_id = a.id
            AND lf.file_role = 'companion' AND lf.extension = 'mov') AS is_live,
    (SELECT GROUP_CONCAT(ext, ',') FROM (
         SELECT DISTINCT UPPER(f.extension) AS ext FROM media_files f
         WHERE f.asset_id = a.id AND f.file_role != 'sidecar' ORDER BY ext
    )) AS formats
"""


def _summary(row: sqlite3.Row) -> AssetSummary:
    return AssetSummary(
        id=row["id"],
        media_type=row["media_type"],
        capture_time=row["capture_time"],
        rating=row["rating"],
        is_favorite=bool(row["is_favorite"]),
        file_name=row["file_name"],
        formats=row["formats"].split(",") if row["formats"] else [],
        width=row["width"],
        height=row["height"],
        duration_ms=row["duration_ms"],
        is_live=bool(row["is_live"]),
        cover_extension=row["extension"],
        rendition_version=_version(row["fingerprint"]),
    )


def summaries_by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[AssetSummary]:
    """Summaries for listable assets among ``ids``, in the order given."""
    if not ids:
        return []
    found: dict[int, AssetSummary] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        rows = conn.execute(
            f"""
            SELECT {_SUMMARY_COLUMNS} {_BASE_FROM}
            WHERE {_BASE_WHERE} AND a.id IN ({",".join("?" * len(chunk))})
            """,
            chunk,
        )
        found.update((int(row["id"]), _summary(row)) for row in rows)
    return [found[i] for i in ids if i in found]


def has_filters(query: AssetQuery) -> bool:
    return any(
        value not in (None, [], "") for key, value in query.model_dump().items() if key != "sort"
    )


def list_assets(
    conn: sqlite3.Connection, query: AssetQuery, *, cursor: str | None, limit: int
) -> AssetPage:
    """Assets matching the filters, in the requested order (keyset pagination)."""
    clauses, params = _filters(query)
    order, after = _ORDER[query.sort]
    if cursor:
        clauses.append(after)
        params.extend(_decode_cursor(cursor, query.sort))

    rows = conn.execute(
        f"""
        SELECT {_SUMMARY_COLUMNS}
        {_BASE_FROM}
        WHERE {" AND ".join(clauses)}
        ORDER BY {order}
        LIMIT ?
        """,
        (*params, limit + 1),
    ).fetchall()

    items = [_summary(row) for row in rows[:limit]]
    next_cursor = _encode_cursor(query.sort, rows[limit - 1]) if len(rows) > limit else None
    return AssetPage(items=items, next_cursor=next_cursor)


def list_asset_ids(conn: sqlite3.Connection, query: AssetQuery, *, limit: int) -> list[int]:
    """All matching ids (for "select all"), in display order."""
    clauses, params = _filters(query)
    order, _ = _ORDER[query.sort]
    rows = conn.execute(
        f"SELECT a.id {_BASE_FROM} WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT ?",
        (*params, limit),
    )
    return [int(row[0]) for row in rows]


def timeline(conn: sqlite3.Connection, query: AssetQuery, granularity: str) -> Timeline:
    length = {"year": 4, "month": 7, "day": 10}[granularity]
    clauses, params = _filters(query)
    rows = conn.execute(
        f"""
        SELECT substr(a.capture_time, 1, {length}) AS period, COUNT(*) AS count
        {_BASE_FROM}
        WHERE {" AND ".join(clauses)}
        GROUP BY period
        ORDER BY period DESC
        """,
        params,
    )
    return Timeline(
        granularity=granularity,  # type: ignore[arg-type]
        buckets=[TimelineBucket(period=row["period"], count=row["count"]) for row in rows],
    )


def map_points(conn: sqlite3.Connection, query: AssetQuery, *, limit: int) -> MapPoints:
    clauses, params = _filters(query)
    rows = conn.execute(
        f"""
        SELECT a.id, l.latitude, l.longitude, c.fingerprint
        {_BASE_FROM}
        JOIN media_locations l ON l.asset_id = a.id
        WHERE {" AND ".join(clauses)}
        ORDER BY a.capture_time DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return MapPoints(
        points=[MapPoint(id=row[0], lat=row[1], lon=row[2], v=_version(row[3])) for row in rows]
    )


def facets(conn: sqlite3.Connection) -> AssetFacets:
    """Values available for filtering, with counts, over the whole library."""
    where = f"WHERE {_BASE_WHERE}"
    totals = conn.execute(
        f"""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE a.media_type = 'photo') AS photos,
               COUNT(*) FILTER (WHERE a.media_type = 'video') AS videos,
               COUNT(*) FILTER (WHERE a.is_favorite = 1) AS favorites,
               COUNT(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM media_locations l WHERE l.asset_id = a.id)) AS with_location
        {_BASE_FROM} {where}
        """
    ).fetchone()

    def grouped(expression: str, limit: int = 200) -> list[FacetValue]:
        rows = conn.execute(
            f"""
            SELECT {expression} AS value, COUNT(*) AS count {_BASE_FROM}
            {where} AND {expression} IS NOT NULL AND {expression} != ''
            GROUP BY value ORDER BY count DESC, value LIMIT ?
            """,
            (limit,),
        )
        return [FacetValue(value=str(row["value"]), count=row["count"]) for row in rows]

    formats = conn.execute(
        f"""
        SELECT UPPER(f.extension) AS value, COUNT(DISTINCT a.id) AS count
        {_BASE_FROM}
        JOIN media_files f ON f.asset_id = a.id AND f.file_role != 'sidecar'
        {where}
        GROUP BY value ORDER BY count DESC
        """
    )
    years = conn.execute(
        f"""
        SELECT substr(a.capture_time, 1, 4) AS value, COUNT(*) AS count
        {_BASE_FROM} {where} GROUP BY value ORDER BY value DESC
        """
    )
    return AssetFacets(
        total=totals["total"],
        photos=totals["photos"],
        videos=totals["videos"],
        favorites=totals["favorites"],
        with_location=totals["with_location"],
        cameras=grouped("m.camera_model"),
        lenses=grouped("m.lens_model"),
        formats=[FacetValue(value=r["value"], count=r["count"]) for r in formats],
        years=[FacetValue(value=r["value"], count=r["count"]) for r in years],
        tags=list_tags(conn),
    )


def list_tags(conn: sqlite3.Connection) -> list[Tag]:
    rows = conn.execute(
        """
        SELECT t.id, t.name, COUNT(mt.asset_id) AS asset_count
        FROM tags t LEFT JOIN media_tags mt ON mt.tag_id = t.id
        GROUP BY t.id
        ORDER BY t.name_key
        """
    )
    return [Tag(id=r["id"], name=r["name"], asset_count=r["asset_count"]) for r in rows]


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


def _is_motion(file: sqlite3.Row) -> bool:
    """The clip of a Live Photo (see lumen.library.live)."""
    return bool(file["file_role"] == "companion" and file["extension"] == CLIP_EXTENSION)


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
    motion = next((f for f in files if _is_motion(f)), None)

    return AssetDetail(
        id=asset["id"],
        uuid=asset["uuid"],
        media_type=asset["media_type"],
        capture_time=asset["capture_time"],
        rating=asset["rating"],
        is_favorite=bool(asset["is_favorite"]),
        rating_source=asset["rating_source"],
        notes=asset["notes"],
        tags=[
            AssetTag(id=t["id"], name=t["name"], source=t["source"], confidence=t["confidence"])
            for t in conn.execute(
                "SELECT t.id, t.name, mt.source, mt.confidence FROM media_tags mt "
                "JOIN tags t ON t.id = mt.tag_id WHERE mt.asset_id = ? ORDER BY t.name_key",
                (asset_id,),
            )
        ],
        cover_file_id=asset["cover_file_id"],
        motion_file_id=motion["id"] if motion else None,
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


def original_file(conn: sqlite3.Connection, asset_id: int) -> tuple[Path, str]:
    """The cover file on disk (for video playback and 1:1 viewing) and its MIME type."""
    row = conn.execute(
        """
        SELECT c.relative_path, c.mime_type, c.status, r.path AS root_path
        FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
        JOIN storage_roots r ON r.id = c.storage_root_id
        WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("Asset not found", details={"id": asset_id})
    path = Path(row["root_path"]) / row["relative_path"]
    if row["status"] != "present" or not path.is_file():
        raise NotFoundError("Original file is not available", details={"id": asset_id})
    return path, row["mime_type"] or "application/octet-stream"


def motion_file(conn: sqlite3.Connection, asset_id: int) -> tuple[Path, str]:
    """A Live Photo's motion clip on disk and its MIME type."""
    clip = next((f for f in _file_rows(conn, asset_id) if _is_motion(f)), None)
    if clip is None:
        raise NotFoundError("Asset has no motion clip", details={"id": asset_id})
    path = Path(clip["root_path"]) / clip["relative_path"]
    if clip["status"] != "present" or not path.is_file():
        raise NotFoundError("Motion clip is not available", details={"id": asset_id})
    return path, clip["mime_type"] or "video/quicktime"
