"""Scan: synchronize ``media_files`` with what is on disk.

Fast and metadata-only: new/changed files are queued for ingestion, files no
longer present are marked ``missing`` (never deleted, so ratings and notes
survive a disconnected drive or a moved folder).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from lumen.db.connection import transaction, utc_now
from lumen.library.common import (
    INGEST_TASK,
    group_key,
    load_root,
    mtime_iso,
    path_key,
    root_status_guard,
    set_root_status,
)
from lumen.media.walker import FoundFile, walk_media
from lumen.tasks.runner import TaskContext

logger = logging.getLogger(__name__)

FLUSH_EVERY = 500


@dataclass
class ScanStats:
    seen: int = 0
    added: int = 0
    changed: int = 0
    unchanged: int = 0
    missing: int = 0


def scan_storage_root(ctx: TaskContext) -> ScanStats:
    with root_status_guard(ctx):
        return _scan(ctx)


def _scan(ctx: TaskContext) -> ScanStats:
    conn = ctx.conn
    root, root_path = load_root(ctx)
    root_id = int(root["id"])
    generation = int(root["scan_generation"]) + 1
    set_root_status(conn, root_id, "scanning")

    known: dict[str, tuple[int, int, int]] = {
        row["relative_path_key"]: (int(row["id"]), int(row["size_bytes"]), int(row["mtime_ns"]))
        for row in conn.execute(
            "SELECT id, relative_path_key, size_bytes, mtime_ns FROM media_files "
            "WHERE storage_root_id = ?",
            (root_id,),
        )
    }

    stats = ScanStats()
    pending: list[FoundFile] = []

    def flush() -> None:
        if pending:
            _apply(ctx, root_id, generation, known, pending, stats)
            pending.clear()
        ctx.progress(stats.seen)

    for found in walk_media(root_path, ctx.should_stop):
        pending.append(found)
        stats.seen += 1
        if len(pending) >= FLUSH_EVERY:
            flush()
    flush()  # also raises if cancelled/interrupted before we mark files missing

    now = utc_now()
    with transaction(conn):
        stats.missing = conn.execute(
            """
            UPDATE media_files SET status = 'missing', updated_at = ?
            WHERE storage_root_id = ? AND scan_generation < ? AND status = 'present'
            """,
            (now, root_id, generation),
        ).rowcount
        if stats.missing:
            switch_missing_covers(conn, root_id, now)
        conn.execute(
            "UPDATE storage_roots SET scan_generation = ?, updated_at = ? WHERE id = ?",
            (generation, now, root_id),
        )

    logger.info("scan finished", extra={"storage_root_id": root_id, **stats.__dict__})
    ctx.progress(stats.seen, stats.seen, force=True)
    ctx.enqueue(INGEST_TASK, storage_root_id=root_id)
    return stats


def _apply(
    ctx: TaskContext,
    root_id: int,
    generation: int,
    known: dict[str, tuple[int, int, int]],
    batch: list[FoundFile],
    stats: ScanStats,
) -> None:
    now = utc_now()
    with transaction(ctx.conn) as conn:
        for found in batch:
            key = path_key(found.relative_path)
            existing = known.get(key)
            if existing is None:
                cursor = conn.execute(
                    """
                    INSERT INTO media_files
                        (storage_root_id, relative_path, relative_path_key, group_key,
                         file_name, extension, file_role, mime_type, size_bytes, mtime_ns,
                         modified_at, status, scan_generation, ingest_state, last_seen_at,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'present', ?, 'pending', ?, ?, ?)
                    """,
                    (
                        root_id, found.relative_path, key, group_key(found.relative_path),
                        found.file_name, found.extension,
                        "sidecar" if found.format.kind == "sidecar" else "primary",
                        found.format.mime_type, found.size, found.mtime_ns,
                        mtime_iso(found.mtime_ns), generation, now, now, now,
                    ),
                )  # fmt: skip
                known[key] = (int(cursor.lastrowid or 0), found.size, found.mtime_ns)
                stats.added += 1
            elif existing[1:] != (found.size, found.mtime_ns):
                conn.execute(
                    """
                    UPDATE media_files
                    SET relative_path = ?, file_name = ?, size_bytes = ?, mtime_ns = ?,
                        modified_at = ?, fingerprint = NULL, status = 'present',
                        scan_generation = ?, ingest_state = 'pending', ingest_attempts = 0,
                        ingest_error = NULL, last_seen_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        found.relative_path, found.file_name, found.size, found.mtime_ns,
                        mtime_iso(found.mtime_ns), generation, now, now, existing[0],
                    ),
                )  # fmt: skip
                known[key] = (existing[0], found.size, found.mtime_ns)
                stats.changed += 1
            else:
                conn.execute(
                    """
                    UPDATE media_files
                    SET scan_generation = ?, last_seen_at = ?,
                        status = 'present',
                        updated_at = CASE WHEN status = 'present' THEN updated_at ELSE ? END
                    WHERE id = ?
                    """,
                    (generation, now, now, existing[0]),
                )
                stats.unchanged += 1


def switch_missing_covers(conn: sqlite3.Connection, root_id: int, now: str) -> int:
    """Photos whose cover file went missing show another present copy instead (a merged
    duplicate, or the RAW of a RAW+JPEG pair). Call inside a transaction."""
    present = """
        SELECT f.id FROM media_files f
        WHERE f.asset_id = media_assets.id AND f.status = 'present'
          AND f.file_role = 'primary' AND f.ingest_state = 'done'
        ORDER BY f.extension IN ('jpg', 'jpeg', 'heic', 'heif', 'png') DESC, f.id LIMIT 1
    """
    return conn.execute(
        f"""
        UPDATE media_assets SET cover_file_id = ({present}), updated_at = ?
        WHERE cover_file_id IN (
                SELECT id FROM media_files WHERE storage_root_id = ? AND status = 'missing')
          AND EXISTS ({present})
        """,
        (now, root_id),
    ).rowcount
