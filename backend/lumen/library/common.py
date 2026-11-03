from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from lumen.db.connection import utc_now
from lumen.tasks.runner import PermanentTaskError, TaskCancelled, TaskContext, TaskInterrupted

SCAN_TASK = "scan_storage_root"
INGEST_TASK = "ingest_storage_root"


def path_key(relative_path: str) -> str:
    return os.path.normcase(os.path.normpath(relative_path))


def group_key(relative_path: str) -> str:
    """Files sharing a group key (same folder, same name stem) belong to one asset."""
    return path_key(os.path.splitext(relative_path)[0])


def mtime_iso(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1e9).astimezone().isoformat(timespec="milliseconds")


def mtime_wall_clock(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1e9).strftime("%Y-%m-%dT%H:%M:%S")


def load_root(ctx: TaskContext) -> tuple[sqlite3.Row, Path]:
    row = ctx.conn.execute(
        "SELECT * FROM storage_roots WHERE id = ?", (ctx.storage_root_id,)
    ).fetchone()
    if row is None:
        raise TaskCancelled()  # root was unregistered
    path = Path(row["path"])
    if not path.is_dir():
        set_root_status(ctx.conn, int(row["id"]), "offline")
        raise PermanentTaskError(f"Storage root is not reachable: {path}")
    return row, path


def set_root_status(
    conn: sqlite3.Connection, root_id: int, status: str, *, scanned: bool = False
) -> None:
    now = utc_now()
    if scanned:
        conn.execute(
            "UPDATE storage_roots SET status = ?, last_scanned_at = ?, updated_at = ? WHERE id = ?",
            (status, now, now, root_id),
        )
    else:
        conn.execute(
            "UPDATE storage_roots SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, root_id),
        )


@contextmanager
def root_status_guard(ctx: TaskContext) -> Iterator[None]:
    """Keep the root's status meaningful when a scan/ingest task stops early."""
    try:
        yield
    except (TaskCancelled, TaskInterrupted):
        row = ctx.conn.execute(
            "SELECT last_scanned_at FROM storage_roots WHERE id = ?", (ctx.storage_root_id,)
        ).fetchone()
        if row is not None and ctx.storage_root_id is not None:
            status = "ready" if row["last_scanned_at"] else "pending_scan"
            set_root_status(ctx.conn, ctx.storage_root_id, status)
        raise
    except PermanentTaskError:
        raise  # status already set (offline)
    except Exception:
        if ctx.storage_root_id is not None:
            set_root_status(ctx.conn, ctx.storage_root_id, "error")
        raise
