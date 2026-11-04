"""Watching storage roots on removable drives (ADR-028).

Every ``INTERVAL_S`` seconds (and at start-up) each root's reachability is checked:

* a root whose drive is gone is marked ``offline`` (nothing else changes: its files keep
  their state, ratings and edits, and views keep showing the cached thumbnails);
* an offline root that is back (the drive was plugged in again) is rescanned, which
  restores any file wrongly marked missing and resumes an unfinished import;
* an offline root whose drive came back under another letter is moved there, found by
  the volume serial number recorded when the root was added.

Checks use the list of drive letters (no disk access) for roots on a drive letter, so a
sleeping external disk is not woken; the folder itself is only checked when a drive
appears. Roots on network shares are checked with ``is_dir`` each time.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from lumen.core.volumes import drive_letter, find_volume, logical_drives
from lumen.db.connection import Database, transaction, utc_now
from lumen.library.common import SCAN_TASK
from lumen.services.storage_roots import path_key
from lumen.tasks import queue

logger = logging.getLogger(__name__)

INTERVAL_S = 30.0
# Every this many checks the folders themselves are looked at too (a renamed or deleted
# folder on a drive that is still there).
DEEP_EVERY = 10


class DriveWatcher:
    """Runs ``check_roots`` every ``INTERVAL_S`` seconds on a background thread."""

    def __init__(self, db: Database, on_queued: Callable[[], None] | None = None) -> None:
        self._db = db
        self._on_queued = on_queued  # wakes the task runner
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Remembered between checks: relocation is only looked for when drives change.
        self.last_drives: set[str] | None = None
        self._checks = 0

    def check(self) -> None:
        deep = self._checks % DEEP_EVERY == 0
        self._checks += 1
        with self._db.session() as conn:
            if check_roots(conn, self, deep=deep) and self._on_queued is not None:
                self._on_queued()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="drive-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)

    def _loop(self) -> None:
        while not self._stop.wait(INTERVAL_S):
            try:
                self.check()
            except Exception:
                logger.exception("drive check failed")


class _Memory(Protocol):
    last_drives: set[str] | None


class _Once:
    last_drives: set[str] | None = None


def check_roots(
    conn: sqlite3.Connection, memory: _Memory | None = None, *, deep: bool = True
) -> bool:
    """Update the roots' reachability; returns True when a scan was queued. ``deep`` also
    opens the folders of roots whose drive is present (otherwise only offline ones)."""
    memory = memory or _Once()
    drives = logical_drives()
    drives_changed = drives != memory.last_drives
    memory.last_drives = drives
    queued = False
    roots = conn.execute(
        "SELECT id, path, status, volume_serial, last_scanned_at FROM storage_roots"
    ).fetchall()
    for root in roots:
        path = Path(root["path"])
        letter = drive_letter(path)
        offline = root["status"] == "offline"
        if letter is not None and drives is not None:
            reachable = letter in drives and (not (offline or deep) or path.is_dir())
        else:
            reachable = path.is_dir()

        if not reachable and offline and drives_changed and root["volume_serial"] and drives:
            moved = _relocate(conn, root, drives)
            if moved is not None:
                path, reachable = moved, True

        if reachable and offline:
            status = "ready" if root["last_scanned_at"] else "pending_scan"
            _set_status(conn, int(root["id"]), status)
            # Restores files marked missing while the drive was away and resumes imports.
            queue.enqueue(
                conn, SCAN_TASK, storage_root_id=int(root["id"]), payload={"reason": "reconnected"}
            )
            queued = True
            logger.info("storage root back online", extra={"storage_root_id": root["id"]})
        elif not reachable and not offline:
            _set_status(conn, int(root["id"]), "offline")
            logger.info(
                "storage root offline", extra={"storage_root_id": root["id"], "path": str(path)}
            )
    return queued


def _relocate(conn: sqlite3.Connection, root: sqlite3.Row, drives: set[str]) -> Path | None:
    """Move a root to the letter its drive now has (same volume serial), if possible."""
    old = str(root["path"])
    candidates = [
        Path(f"{letter}:{old[2:]}")
        for letter in find_volume(str(root["volume_serial"]), drives)
        if letter != drive_letter(old)
    ]
    new = next(
        (c for c in candidates if c.is_dir() and _same_files(conn, int(root["id"]), c)), None
    )
    if new is None:
        return None
    key = path_key(new)
    with transaction(conn):
        taken = conn.execute(
            "SELECT 1 FROM storage_roots WHERE path_key = ? AND id != ?", (key, root["id"])
        ).fetchone()
        if taken:
            return None
        conn.execute(
            "UPDATE storage_roots SET path = ?, path_key = ?, updated_at = ? WHERE id = ?",
            (str(new), key, utc_now(), root["id"]),
        )
    logger.info(
        "storage root moved to a new drive letter",
        extra={"storage_root_id": root["id"], "from": old, "to": str(new)},
    )
    return new


def _same_files(conn: sqlite3.Connection, root_id: int, candidate: Path, sample: int = 8) -> bool:
    """A few of the root's files (spread over it) exist under ``candidate`` with their size:
    the same folder, not merely the same volume."""
    rows = conn.execute(
        "SELECT relative_path, size_bytes FROM media_files "
        "WHERE storage_root_id = ? AND status = 'present' ORDER BY id",
        (root_id,),
    ).fetchall()
    if not rows:
        return True  # nothing indexed yet: the folder existing is all there is to check
    picks = [rows[round(i * (len(rows) - 1) / max(sample - 1, 1))] for i in range(sample)]
    for relative_path, size in {tuple(row) for row in picks}:
        try:
            if (candidate / relative_path).stat().st_size != size:
                return False
        except OSError:
            return False
    return True


def _set_status(conn: sqlite3.Connection, root_id: int, status: str) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE storage_roots SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now(), root_id),
        )
