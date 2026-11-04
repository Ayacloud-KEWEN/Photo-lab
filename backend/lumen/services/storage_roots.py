"""Storage root registration.

Only reads the file system (existence and readability checks). Never creates,
moves, renames or deletes anything inside a registered directory.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

from lumen.core.errors import ConflictError, InvalidPathError, NotFoundError
from lumen.core.volumes import drive_letter, get_volume_info, logical_drives
from lumen.db.connection import transaction, utc_now
from lumen.library.common import SCAN_TASK
from lumen.schemas.storage_roots import StorageRoot, StorageRootCreate, StorageRootStats
from lumen.tasks import queue

logger = logging.getLogger(__name__)

SCAN_TASK_KIND = SCAN_TASK


def normalize_directory(raw: str) -> Path:
    """Validate that ``raw`` is an existing, readable, absolute directory path."""
    if "\x00" in raw:
        raise InvalidPathError("Path contains invalid characters", details={"path": raw})
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise InvalidPathError("Path must be absolute", details={"path": raw})

    # abspath/normpath (not resolve) keeps the drive letter the user chose,
    # instead of expanding mapped network drives to UNC paths.
    path = Path(os.path.normpath(os.path.abspath(candidate)))
    if not path.exists():
        raise InvalidPathError("Directory does not exist", details={"path": str(path)})
    if not path.is_dir():
        raise InvalidPathError("Path is not a directory", details={"path": str(path)})
    try:
        with os.scandir(path) as entries:
            next(entries, None)
    except OSError as exc:
        raise InvalidPathError(
            "Directory is not readable", details={"path": str(path), "reason": str(exc)}
        ) from exc
    return path


def path_key(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _with_sep(key: str) -> str:
    return key if key.endswith(os.sep) else key + os.sep


def _default_display_name(path: Path, volume_label: str | None) -> str:
    if path.name:
        return path.name
    # Drive root such as "D:\": prefer the volume label.
    drive = path.drive or str(path)
    return f"{volume_label} ({drive})" if volume_label else drive


_STATS_SQL = """
    SELECT storage_root_id,
           COUNT(*) FILTER (WHERE status = 'present' AND file_role != 'sidecar') AS files,
           COUNT(DISTINCT asset_id) FILTER (WHERE status = 'present') AS assets,
           COUNT(*) FILTER (WHERE status = 'present' AND ingest_state = 'pending') AS pending,
           COUNT(*) FILTER (WHERE status = 'present' AND ingest_state = 'error') AS errors,
           COUNT(*) FILTER (WHERE status = 'missing') AS missing
    FROM media_files
    {where}
    GROUP BY storage_root_id
"""


def _stats(conn: sqlite3.Connection, root_id: int | None = None) -> dict[int, StorageRootStats]:
    where, params = ("WHERE storage_root_id = ?", (root_id,)) if root_id else ("", ())
    return {
        int(row["storage_root_id"]): StorageRootStats(
            file_count=row["files"],
            asset_count=row["assets"],
            pending_count=row["pending"],
            error_count=row["errors"],
            missing_count=row["missing"],
        )
        for row in conn.execute(_STATS_SQL.format(where=where), params)
    }


def _available(row: sqlite3.Row) -> bool:
    """Whether the root can be read now. For a drive letter this uses the list of drives
    (no disk access, so a sleeping external disk is not woken by the UI's polling); the
    drive watcher marks such a root offline / back online (``library/drives.py``)."""
    letter, drives = drive_letter(row["path"]), logical_drives()
    if letter is not None and drives is not None:
        return letter in drives and row["status"] != "offline"
    return os.path.isdir(row["path"])


def _to_model(row: sqlite3.Row, stats: StorageRootStats | None = None) -> StorageRoot:
    return StorageRoot(
        stats=stats or StorageRootStats(),
        id=row["id"],
        path=row["path"],
        display_name=row["display_name"],
        status=row["status"],
        is_available=_available(row),
        volume_serial=row["volume_serial"],
        volume_label=row["volume_label"],
        last_scanned_at=row["last_scanned_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def list_storage_roots(conn: sqlite3.Connection) -> list[StorageRoot]:
    rows = conn.execute("SELECT * FROM storage_roots ORDER BY created_at, id").fetchall()
    stats = _stats(conn)
    return [_to_model(row, stats.get(int(row["id"]))) for row in rows]


def get_storage_root(conn: sqlite3.Connection, root_id: int) -> StorageRoot:
    row = conn.execute("SELECT * FROM storage_roots WHERE id = ?", (root_id,)).fetchone()
    if row is None:
        raise NotFoundError("Storage root not found", details={"id": root_id})
    return _to_model(row, _stats(conn, root_id).get(root_id))


def request_scan(conn: sqlite3.Connection, root_id: int) -> int:
    """Queue a (re)scan of a root; returns the task id (an active one is reused)."""
    get_storage_root(conn, root_id)
    return queue.enqueue(conn, SCAN_TASK, storage_root_id=root_id, payload={"reason": "user"})


def create_storage_root(conn: sqlite3.Connection, data: StorageRootCreate) -> StorageRoot:
    path = normalize_directory(data.path)
    key = path_key(path)
    volume = get_volume_info(path)
    display_name = data.display_name or _default_display_name(path, volume.label)
    now = utc_now()

    with transaction(conn):
        for existing in conn.execute("SELECT id, path, path_key FROM storage_roots"):
            existing_key = str(existing["path_key"])
            details = {
                "path": str(path),
                "existing_id": existing["id"],
                "existing_path": existing["path"],
            }
            if existing_key == key:
                raise ConflictError("Directory is already registered", details=details)
            if key.startswith(_with_sep(existing_key)):
                raise ConflictError(
                    "Directory is inside an already registered directory", details=details
                )
            if existing_key.startswith(_with_sep(key)):
                raise ConflictError(
                    "Directory contains an already registered directory", details=details
                )

        try:
            cursor = conn.execute(
                """
                INSERT INTO storage_roots
                    (path, path_key, display_name, volume_serial, volume_label,
                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending_scan', ?, ?)
                """,
                (str(path), key, display_name, volume.serial, volume.label, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                "Directory is already registered", details={"path": str(path)}
            ) from exc
        root_id = int(cursor.lastrowid or 0)

        # Queue the initial scan; the Phase 2 media engine consumes these tasks.
        conn.execute(
            """
            INSERT INTO tasks (kind, status, storage_root_id, payload, created_at, updated_at)
            VALUES (?, 'pending', ?, ?, ?, ?)
            """,
            (SCAN_TASK_KIND, root_id, json.dumps({"reason": "registered"}), now, now),
        )

    logger.info("storage root registered", extra={"storage_root_id": root_id, "path": str(path)})
    return get_storage_root(conn, root_id)


def delete_storage_root(conn: sqlite3.Connection, root_id: int) -> None:
    """Unregister a root. Removes its database records only; files on disk are untouched."""
    with transaction(conn):
        row = conn.execute("SELECT path FROM storage_roots WHERE id = ?", (root_id,)).fetchone()
        if row is None:
            raise NotFoundError("Storage root not found", details={"id": root_id})
        # media_files and tasks of this root are removed by ON DELETE CASCADE.
        conn.execute("DELETE FROM storage_roots WHERE id = ?", (root_id,))
        orphaned = conn.execute(
            """
            DELETE FROM media_assets
            WHERE NOT EXISTS (SELECT 1 FROM media_files f WHERE f.asset_id = media_assets.id)
            """
        ).rowcount

    logger.info(
        "storage root unregistered",
        extra={"storage_root_id": root_id, "path": row["path"], "orphaned_assets": orphaned},
    )
