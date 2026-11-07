"""Ingest: fingerprint, group into assets, extract metadata and render thumbnails.

Work is tracked per file (``media_files.ingest_state``), so an interrupted run
resumes where it stopped. Each file's attempt counter is incremented *before*
it is processed: a file that crashes the process is skipped after
``MAX_FILE_ATTEMPTS`` restarts instead of blocking the queue forever.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import threading
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

from lumen.ai.pipeline import AI_INDEX_TASK
from lumen.core.volumes import incurs_seek_penalty
from lumen.db.connection import transaction, utc_now
from lumen.geo.tasks import GEO_TASK
from lumen.library.common import (
    load_root,
    mtime_wall_clock,
    root_status_guard,
    set_root_status,
)
from lumen.library.live import pair_live_photo
from lumen.library.quality import QUALITY_TASK, Quality, measure_preview, store_quality
from lumen.library.search import reindex_assets
from lumen.library.tags import get_or_create_tag, normalize_tag_name, tag_assets
from lumen.media import thumbnails
from lumen.media.fingerprint import FingerprintCancelled, fingerprint_file
from lumen.media.formats import MediaFormat, format_for
from lumen.media.metadata import (
    ExifToolSession,
    Metadata,
    merge_video,
    parse_exiftool,
    parse_ffprobe,
    run_ffprobe,
)
from lumen.services.settings import get_settings
from lumen.tasks.runner import PermanentTaskError, TaskContext, TaskInterrupted

logger = logging.getLogger(__name__)

# Finished files are saved in groups of this size (one ExifTool call and one transaction).
STORE_SIZE = 16
# Files being processed at once, per worker: keeps every worker busy while a group is saved.
WINDOW_PER_WORKER = 3
# Parallel reads (fingerprints) on a spinning disk: more only adds seeks.
HDD_READERS = 2
MAX_FILE_ATTEMPTS = 3


@dataclass
class WorkItem:
    file_id: int
    relative_path: str
    path: Path
    format: MediaFormat
    size: int
    mtime_ns: int
    group_key: str
    asset_id: int | None
    fingerprint: str | None
    metadata: Metadata | None = None
    probed: Metadata | None = None  # FFprobe result (videos)
    quality: Quality | None = None  # photos: measured on the preview just rendered
    measured: bool = False
    read_failed: bool = False  # could not be read or fingerprinted
    error: str | None = None
    vanished: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class Tools:
    exiftool: ExifToolSession | None
    exiftool_version: str
    ffprobe: str | None
    ffmpeg: str | None


def ingest_storage_root(ctx: TaskContext) -> None:
    with root_status_guard(ctx):
        _ingest(ctx)


def _ingest(ctx: TaskContext) -> None:
    conn = ctx.conn
    root, root_path = load_root(ctx)
    root_id = int(root["id"])
    set_root_status(conn, root_id, "scanning")

    total = _count_pending(conn, root_id)
    done = 0
    ctx.progress(0, total, force=True)

    exiftool_path = ctx.settings.tool("exiftool")
    if exiftool_path is None:
        logger.warning("exiftool not found: photo metadata will not be extracted")

    with contextlib.ExitStack() as stack:
        session = stack.enter_context(ExifToolSession(exiftool_path)) if exiftool_path else None
        tools = Tools(
            exiftool=session,
            exiftool_version=session.version if session else "",
            ffprobe=ctx.settings.tool("ffprobe"),
            ffmpeg=ctx.settings.tool("ffmpeg"),
        )
        workers = ctx.settings.ingest_workers
        pool = stack.enter_context(ThreadPoolExecutor(workers, thread_name_prefix="ingest"))
        spinning = incurs_seek_penalty(root_path)
        readers = threading.BoundedSemaphore(HDD_READERS if spinning is not False else workers)
        logger.info(
            "ingest started",
            extra={"storage_root_id": root_id, "pending": total, "workers": workers,
                   "readers": HDD_READERS if spinning is not False else workers},
        )  # fmt: skip
        done = _run_window(ctx, root_id, root_path, tools, pool, readers, total)

    set_root_status(conn, root_id, "ready", scanned=True)
    ctx.progress(done, max(total, done), force=True)
    if done:
        ctx.enqueue(GEO_TASK)
        ctx.enqueue(QUALITY_TASK)
    if done and get_settings(conn).ai_enabled:
        ctx.enqueue(AI_INDEX_TASK)


def _count_pending(conn: sqlite3.Connection, root_id: int) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM media_files
        WHERE storage_root_id = ? AND ingest_state = 'pending' AND status = 'present'
          AND ingest_attempts < ?
        """,
        (root_id, MAX_FILE_ATTEMPTS),
    ).fetchone()
    return int(row[0])


def _claimable(conn: sqlite3.Connection, root_id: int) -> bool:
    return _count_pending(conn, root_id) > 0


def _claim_batch(
    *, conn: sqlite3.Connection, root_id: int, root_path: Path, limit: int, exclude: list[int]
) -> list[WorkItem]:
    """Pending files not being processed yet (in id order, so roughly folder by folder)."""
    with transaction(conn):
        rows = conn.execute(
            f"""
            SELECT id, relative_path, extension, size_bytes, mtime_ns, group_key, asset_id,
                   fingerprint
            FROM media_files
            WHERE storage_root_id = ? AND ingest_state = 'pending' AND status = 'present'
              AND ingest_attempts < ? AND id NOT IN ({",".join("?" * len(exclude))})
            ORDER BY id
            LIMIT ?
            """,
            (root_id, MAX_FILE_ATTEMPTS, *exclude, limit),
        ).fetchall()
        conn.executemany(
            "UPDATE media_files SET ingest_attempts = ingest_attempts + 1 WHERE id = ?",
            [(row["id"],) for row in rows],
        )

    items = []
    for row in rows:
        media_format = format_for(row["extension"])
        if media_format is None:  # extension no longer supported
            conn.execute(
                "UPDATE media_files SET ingest_state = 'error', ingest_error = ? WHERE id = ?",
                ("unsupported format", row["id"]),
            )
            continue
        items.append(
            WorkItem(
                file_id=int(row["id"]),
                relative_path=row["relative_path"],
                path=root_path / row["relative_path"],
                format=media_format,
                size=int(row["size_bytes"]),
                mtime_ns=int(row["mtime_ns"]),
                group_key=row["group_key"],
                asset_id=row["asset_id"],
                fingerprint=row["fingerprint"],
            )
        )
    return items


def _run_window(
    ctx: TaskContext,
    root_id: int,
    root_path: Path,
    tools: Tools,
    pool: ThreadPoolExecutor,
    readers: threading.BoundedSemaphore,
    total: int,
) -> int:
    """Process pending files as a sliding window and return how many were stored.

    Each file is fingerprinted (reads gated by ``readers``), probed and rendered on its
    own as soon as a worker is free, so reading one file overlaps decoding another.
    Finished files are saved in claim order (assets are created in file order, as
    before), up to ``STORE_SIZE`` at a time, while the workers keep going ahead.
    """
    window = ctx.settings.ingest_workers * WINDOW_PER_WORKER
    queued: deque[tuple[WorkItem, Future[None]]] = deque()  # claimed, in file order
    done = 0
    exhausted = False
    try:
        while True:
            ctx.check()
            if not exhausted and len(queued) < window:
                claimed = _claim_batch(
                    conn=ctx.conn, root_id=root_id, root_path=root_path,
                    limit=window - len(queued), exclude=[item.file_id for item, _ in queued],
                )  # fmt: skip
                exhausted = not claimed
                for item in claimed:
                    queued.append((item, pool.submit(_prepare, item, ctx, tools, readers)))
            if not queued:
                if exhausted and _claimable(ctx.conn, root_id):
                    exhausted = False  # failed files go back to pending: retry them
                    continue
                break
            if not queued[0][1].done():
                wait([queued[0][1]], timeout=1.0)
                if ctx.should_stop():
                    raise TaskInterrupted()
                continue
            group: list[tuple[WorkItem, Future[None]]] = []
            while queued and len(group) < STORE_SIZE and queued[0][1].done():
                entry = queued.popleft()
                entry[1].result()  # _prepare records errors on the item; re-raise bugs
                group.append(entry)
            items = [item for item, _ in group]
            if any(item.vanished or item.read_failed for item in items) and not root_path.is_dir():
                # The drive went away: its files are not missing, the import is just paused.
                queued.extendleft(reversed(group))  # not charged an attempt (see below)
                set_root_status(ctx.conn, root_id, "offline")
                raise PermanentTaskError(f"Storage root is not reachable: {root_path}")
            _store_group(ctx, items, tools)
            done += len(group)
            ctx.progress(done, max(total, done))
    finally:
        # Claimed but not finished (cancelled or shutting down): not charged an attempt.
        unfinished = [item.file_id for item, _ in queued]
        if unfinished:
            with transaction(ctx.conn):
                ctx.conn.executemany(
                    "UPDATE media_files SET ingest_attempts = MAX(ingest_attempts - 1, 0) "
                    "WHERE id = ? AND ingest_state = 'pending'",
                    [(file_id,) for file_id in unfinished],
                )
    return done


def _prepare(
    item: WorkItem, ctx: TaskContext, tools: Tools, readers: threading.BoundedSemaphore
) -> None:
    """The per-file work that needs no database: fingerprint, probe, render."""
    with readers:
        _fingerprint(item, ctx)
    item.read_failed = item.error is not None
    if item.error or item.vanished or ctx.should_stop() or item.format.media_type is None:
        return
    if item.format.kind == "video" and tools.ffprobe:
        try:
            item.probed = parse_ffprobe(run_ffprobe(tools.ffprobe, item.path))
        except Exception as exc:
            item.warnings.append(f"ffprobe: {exc}")
    # Thumbnails and previews (CPU bound; Pillow/LibRaw release the GIL).
    _render(item, ctx, tools)
    if item.error is None and item.fingerprint and item.format.media_type == "photo":
        # The preview was just written (still in the file cache): measuring it now saves
        # reading every preview again in a separate pass after the import.
        item.quality = measure_preview(
            ctx.settings.cache_dir, item.fingerprint, item.path.suffix.lower().lstrip(".")
        )
        item.measured = True


def _store_group(ctx: TaskContext, items: list[WorkItem], tools: Tools) -> None:
    # Read and fingerprinted (a failed thumbnail still belongs to its asset, e.g. a RAW
    # next to its JPEG; the error is recorded when storing).
    ok = [i for i in items if i.fingerprint and not i.vanished and not i.read_failed]
    # Group into assets (serialized by SQLite transactions).
    for item in ok:
        _assign_asset(ctx.conn, item)
    # Metadata: one ExifTool call for the group. Sidecars are read too: Lightroom keeps
    # RAW ratings and keywords in the .xmp next to the file.
    _extract_metadata(ok, tools)
    _store_results(ctx.conn, items, tools)


def _fingerprint(item: WorkItem, ctx: TaskContext) -> None:
    if item.fingerprint:
        return
    try:
        item.fingerprint = fingerprint_file(item.path, ctx.should_stop)
        info = item.path.stat()
        if (info.st_size, info.st_mtime_ns) != (item.size, item.mtime_ns):
            item.error = "file changed while being processed"
            item.fingerprint = None
    except FileNotFoundError:
        item.vanished = True
    except FingerprintCancelled:
        item.error = "interrupted"
    except OSError as exc:
        item.error = f"cannot read file: {exc}"


def _assign_asset(conn: sqlite3.Connection, item: WorkItem) -> None:
    if item.asset_id is not None:
        return  # content changed on an already grouped file: keep its asset
    now = utc_now()
    with transaction(conn):
        if item.format.kind == "sidecar":
            sibling = conn.execute(
                """
                SELECT asset_id FROM media_files
                WHERE storage_root_id = (SELECT storage_root_id FROM media_files WHERE id = ?)
                  AND group_key = ? AND asset_id IS NOT NULL AND file_role != 'sidecar'
                ORDER BY id LIMIT 1
                """,
                (item.file_id, item.group_key),
            ).fetchone()
            if sibling is not None:
                _attach(conn, item, int(sibling["asset_id"]), "sidecar", now)
            return

        # A missing file with identical content in the same root: the file was moved.
        moved = conn.execute(
            """
            SELECT m.id, m.asset_id, m.file_role FROM media_files m
            WHERE m.storage_root_id = (SELECT storage_root_id FROM media_files WHERE id = ?)
              AND m.fingerprint = ? AND m.status = 'missing' AND m.asset_id IS NOT NULL
              AND m.id != ?
            ORDER BY m.id LIMIT 1
            """,
            (item.file_id, item.fingerprint, item.file_id),
        ).fetchone()
        if moved is not None:
            asset_id = int(moved["asset_id"])
            _attach(conn, item, asset_id, moved["file_role"], now)
            conn.execute(
                "UPDATE media_assets SET cover_file_id = ? WHERE id = ? AND cover_file_id = ?",
                (item.file_id, asset_id, moved["id"]),
            )
            conn.execute("DELETE FROM media_files WHERE id = ?", (moved["id"],))
            logger.info(
                "file moved", extra={"file_id": item.file_id, "previous_file_id": moved["id"]}
            )
            _attach_orphan_sidecars(conn, item, asset_id, now)
            return

        if item.format.media_type == "photo":
            sibling = conn.execute(
                """
                SELECT f.asset_id, a.cover_file_id,
                       p.id AS primary_id, p.extension AS primary_extension,
                       c.extension AS cover_extension
                FROM media_files f
                JOIN media_assets a ON a.id = f.asset_id AND a.media_type = 'photo'
                LEFT JOIN media_files p ON p.asset_id = a.id AND p.file_role = 'primary'
                LEFT JOIN media_files c ON c.id = a.cover_file_id
                WHERE f.storage_root_id = (SELECT storage_root_id FROM media_files WHERE id = ?)
                  AND f.group_key = ? AND f.file_role != 'sidecar' AND f.id != ?
                ORDER BY f.id LIMIT 1
                """,
                (item.file_id, item.group_key, item.file_id),
            ).fetchone()
            if sibling is not None:
                asset_id = int(sibling["asset_id"])
                primary_format = format_for(sibling["primary_extension"] or "")
                if item.format.is_raw and not (primary_format and primary_format.is_raw):
                    # The RAW is the original: it becomes primary, the JPEG a companion.
                    conn.execute(
                        "UPDATE media_files SET file_role = 'companion', updated_at = ? "
                        "WHERE asset_id = ? AND file_role = 'primary'",
                        (now, asset_id),
                    )
                    role = "primary"
                else:
                    role = "companion"
                _attach(conn, item, asset_id, role, now)
                cover_format = format_for(sibling["cover_extension"] or "")
                if not item.format.is_raw and (cover_format is None or cover_format.is_raw):
                    # Prefer the camera-rendered JPEG/HEIC as the visible cover.
                    conn.execute(
                        "UPDATE media_assets SET cover_file_id = ?, updated_at = ? WHERE id = ?",
                        (item.file_id, now, asset_id),
                    )
                _attach_orphan_sidecars(conn, item, asset_id, now)
                return

        cursor = conn.execute(
            """
            INSERT INTO media_assets (uuid, media_type, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), item.format.media_type, now, now),
        )
        asset_id = int(cursor.lastrowid or 0)
        if not _attach(conn, item, asset_id, "primary", now):
            # The file row disappeared (its root was removed meanwhile).
            conn.execute("DELETE FROM media_assets WHERE id = ?", (asset_id,))
            return
        conn.execute(
            "UPDATE media_assets SET cover_file_id = ? WHERE id = ?", (item.file_id, asset_id)
        )
        _attach_orphan_sidecars(conn, item, asset_id, now)


def _attach(conn: sqlite3.Connection, item: WorkItem, asset_id: int, role: str, now: str) -> bool:
    attached = conn.execute(
        "UPDATE media_files SET asset_id = ?, file_role = ?, updated_at = ? WHERE id = ?",
        (asset_id, role, now, item.file_id),
    ).rowcount
    if attached:
        item.asset_id = asset_id
    return bool(attached)


def _attach_orphan_sidecars(
    conn: sqlite3.Connection, item: WorkItem, asset_id: int, now: str
) -> None:
    conn.execute(
        """
        UPDATE media_files SET asset_id = ?, updated_at = ?
        WHERE storage_root_id = (SELECT storage_root_id FROM media_files WHERE id = ?)
          AND group_key = ? AND file_role = 'sidecar' AND asset_id IS NULL
        """,
        (asset_id, now, item.file_id, item.group_key),
    )


def _extract_metadata(items: list[WorkItem], tools: Tools) -> None:
    records: dict[str, object] = {}
    if tools.exiftool is not None and items:
        records = dict(tools.exiftool.read(item.path for item in items))

    for item in items:
        probed = item.probed
        record = records.get(str(item.path))
        if isinstance(record, dict):
            metadata = parse_exiftool(record)
        else:
            if isinstance(record, Exception):
                item.warnings.append(f"exiftool: {record}")
            metadata = Metadata()
        if probed is not None:
            metadata = merge_video(metadata, probed)
        item.metadata = metadata


def _render(item: WorkItem, ctx: TaskContext, tools: Tools) -> None:
    if item.error or ctx.should_stop() or item.fingerprint is None:
        return
    target = thumbnails.rendition_paths(ctx.settings.cache_dir, item.fingerprint)
    try:
        thumbnails.render(item.path, item.format, target, ffmpeg=tools.ffmpeg)
    except FileNotFoundError:
        item.vanished = True
    except thumbnails.RenderError as exc:
        item.error = str(exc)
    except Exception as exc:  # decoder bugs must not stop the batch
        logger.exception("unexpected render failure", extra={"path": str(item.path)})
        item.error = f"{type(exc).__name__}: {exc}"


def _store_qualities(conn: sqlite3.Connection, items: list[WorkItem], now: str) -> None:
    """Quality of the photos whose file is their asset's cover (others are measured by
    the quality task once the cover is known)."""
    for item in items:
        if not item.measured or item.fingerprint is None or item.asset_id is None:
            continue
        cover = conn.execute(
            "SELECT cover_file_id FROM media_assets WHERE id = ?", (item.asset_id,)
        ).fetchone()
        if cover is not None and cover[0] == item.file_id:
            store_quality(conn, item.asset_id, item.fingerprint, item.quality, now)


def _store_results(conn: sqlite3.Connection, items: list[WorkItem], tools: Tools) -> None:
    now = utc_now()
    extractor_version = (
        "; ".join(
            part
            for part in (
                f"exiftool {tools.exiftool_version}" if tools.exiftool else "",
                "ffprobe" if tools.ffprobe else "",
            )
            if part
        )
        or "none"
    )

    with transaction(conn):
        for item in items:
            _store_item(conn, item, extractor_version, now)
        _store_qualities(conn, items, now)
        # After storing: pairing needs the metadata of both halves, wherever they were read.
        for item in items:
            if item.metadata is not None and not (item.error or item.vanished):
                pair_live_photo(conn, item.file_id, now)
        # Asset ids may have been assigned in this batch (also to sidecars' siblings).
        touched = (
            {
                int(row[0])
                for row in conn.execute(
                    f"SELECT DISTINCT asset_id FROM media_files WHERE asset_id IS NOT NULL "
                    f"AND id IN ({','.join('?' * len(items))})",
                    [item.file_id for item in items],
                )
            }
            if items
            else set()
        )
        _apply_imports(conn, touched, now)
        reindex_assets(conn, touched)


def _store_item(conn: sqlite3.Connection, item: WorkItem, version: str, now: str) -> None:
    if item.vanished:
        # Gone since the scan: missing, and not charged an attempt.
        conn.execute(
            """
            UPDATE media_files
            SET status = 'missing', ingest_attempts = MAX(ingest_attempts - 1, 0),
                updated_at = ?
            WHERE id = ?
            """,
            (now, item.file_id),
        )
        return
    if item.error:
        conn.execute(
            """
            UPDATE media_files
            SET ingest_error = ?,
                ingest_state = CASE WHEN ingest_attempts >= ? THEN 'error'
                                    ELSE 'pending' END,
                updated_at = ?
            WHERE id = ?
            """,
            (item.error, MAX_FILE_ATTEMPTS, now, item.file_id),
        )
        logger.warning(
            "file ingest failed",
            extra={
                "file_id": item.file_id,
                "path": item.relative_path,
                "error": item.error,
            },
        )
        return

    conn.execute(
        """
        UPDATE media_files
        SET fingerprint = ?, ingest_state = 'done', ingest_error = ?, updated_at = ?
        WHERE id = ?
        """,
        (item.fingerprint, "; ".join(item.warnings) or None, now, item.file_id),
    )
    if item.metadata is not None:
        _store_metadata(conn, item, item.metadata, version, now)


def _store_metadata(
    conn: sqlite3.Connection, item: WorkItem, meta: Metadata, version: str, now: str
) -> None:
    conn.execute(
        """
        INSERT INTO media_metadata
            (file_id, width, height, orientation, duration_ms, capture_time, camera_make,
             camera_model, lens_model, focal_length_mm, aperture, exposure_time_s, iso,
             video_codec, frame_rate, keywords, xmp_rating, content_identifier, raw_json,
             extractor, extractor_version, extracted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'exiftool+ffprobe', ?, ?)
        ON CONFLICT (file_id) DO UPDATE SET
            width = excluded.width, height = excluded.height,
            orientation = excluded.orientation, duration_ms = excluded.duration_ms,
            capture_time = excluded.capture_time, camera_make = excluded.camera_make,
            camera_model = excluded.camera_model, lens_model = excluded.lens_model,
            focal_length_mm = excluded.focal_length_mm, aperture = excluded.aperture,
            exposure_time_s = excluded.exposure_time_s, iso = excluded.iso,
            video_codec = excluded.video_codec, frame_rate = excluded.frame_rate,
            keywords = excluded.keywords, xmp_rating = excluded.xmp_rating,
            content_identifier = excluded.content_identifier,
            raw_json = excluded.raw_json, extractor = excluded.extractor,
            extractor_version = excluded.extractor_version, extracted_at = excluded.extracted_at
        """,
        (
            item.file_id, meta.width, meta.height, meta.orientation, meta.duration_ms,
            meta.capture_time, meta.camera_make, meta.camera_model, meta.lens_model,
            meta.focal_length_mm, meta.aperture, meta.exposure_time_s, meta.iso,
            meta.video_codec, meta.frame_rate,
            json.dumps(meta.keywords, ensure_ascii=False) if meta.keywords else None,
            meta.xmp_rating, meta.content_identifier, meta.raw_json(), version, now,
        ),
    )  # fmt: skip

    if item.asset_id is None or item.format.kind == "sidecar":
        return
    # Asset capture time: the primary file's EXIF date, else any file's, else file mtime;
    # a correction made in LUMEN (``time_shift_s``) applies to the file's date again.
    conn.execute(
        """
        UPDATE media_assets
        SET capture_time = COALESCE(
                (SELECT strftime('%Y-%m-%dT%H:%M:%S', m.capture_time,
                                 media_assets.time_shift_s || ' seconds')
                 FROM media_files f
                 JOIN media_metadata m ON m.file_id = f.id
                 WHERE f.asset_id = media_assets.id AND m.capture_time IS NOT NULL
                 ORDER BY f.file_role = 'primary' DESC, f.id LIMIT 1),
                capture_time,
                ?),
            updated_at = ?
        WHERE id = ?
        """,
        (mtime_wall_clock(item.mtime_ns), now, item.asset_id),
    )
    if meta.latitude is not None and meta.longitude is not None:
        conn.execute(
            """
            INSERT INTO media_locations (asset_id, latitude, longitude, altitude_m, source,
                                         updated_at)
            VALUES (?, ?, ?, ?, 'exif', ?)
            ON CONFLICT (asset_id) DO UPDATE SET
                latitude = excluded.latitude, longitude = excluded.longitude,
                altitude_m = excluded.altitude_m, updated_at = excluded.updated_at
            WHERE media_locations.source = 'exif'
            """,
            (item.asset_id, meta.latitude, meta.longitude, meta.altitude_m, now),
        )


def _apply_imports(conn: sqlite3.Connection, asset_ids: set[int], now: str) -> None:
    """Import ratings and keywords found in any of the assets' files (read-only sources).

    A rating set in LUMEN (``rating_source = 'user'``) is never overwritten.
    """
    if not asset_ids:
        return
    marks = ",".join("?" * len(asset_ids))
    ids = sorted(asset_ids)
    conn.execute(
        f"""
        UPDATE media_assets
        SET rating = imported.rating, rating_source = 'import', updated_at = ?
        FROM (
            SELECT f.asset_id, MAX(m.xmp_rating) AS rating
            FROM media_files f JOIN media_metadata m ON m.file_id = f.id
            WHERE f.asset_id IN ({marks}) AND m.xmp_rating > 0
            GROUP BY f.asset_id
        ) AS imported
        WHERE media_assets.id = imported.asset_id
          AND (media_assets.rating_source IS NULL OR media_assets.rating_source = 'import')
        """,
        [now, *ids],
    )
    rows = conn.execute(
        f"""
        SELECT f.asset_id, m.keywords FROM media_files f
        JOIN media_metadata m ON m.file_id = f.id
        WHERE f.asset_id IN ({marks}) AND m.keywords IS NOT NULL
        """,
        ids,
    ).fetchall()
    tag_ids: dict[str, int] = {}
    for row in rows:
        for keyword in json.loads(row["keywords"]):
            if not isinstance(keyword, str) or not normalize_tag_name(keyword):
                continue
            if keyword not in tag_ids:
                tag_ids[keyword] = get_or_create_tag(conn, keyword)
            tag_assets(conn, [int(row["asset_id"])], tag_ids[keyword], "import")
