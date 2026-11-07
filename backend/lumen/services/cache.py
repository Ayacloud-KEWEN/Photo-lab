"""Where thumbnails and previews are kept, and moving them to another folder (ADR-031).

The cache is regenerable but expensive to rebuild (every original is read again), so a
new location is filled by copying: the old folder stays in use while the files are
copied, the app then switches to the new folder (no restart) and only after that are
the old files deleted. The folder is a user setting (``app_settings.cache_folder``);
the default is ``<data folder>/cache``.
"""

from __future__ import annotations

import contextlib
import errno
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from lumen.core.config import APP_DIR_NAME, Settings
from lumen.core.errors import ConflictError, InvalidPathError, LumenError
from lumen.db.connection import transaction, utc_now
from lumen.schemas.cache import CacheStatus, CacheUsage
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskCancelled, TaskContext

logger = logging.getLogger(__name__)

CACHE_KEY = "cache_folder"
MOVE_CACHE_TASK = "move_cache"
SPACE_MARGIN = 5 * 2**30  # left free on the target drive
COPY_WORKERS = 4
CHUNK = 256  # files copied between progress reports
USAGE_TTL_S = 300.0
_SUBDIR = "renditions"
_KIND = re.compile(r"_(t|p|f)\d+\.jpg$")
_KINDS = {"t": "thumbs", "p": "previews", "f": "full"}
_DISK_FULL = {errno.ENOSPC, 112}  # 112: ERROR_DISK_FULL (winerror)


class CacheMoveError(LumenError):
    code = "cache_move_failed"


# ---------------------------------------------------------------------------- setting


def configured_folder(conn: sqlite3.Connection) -> Path | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (CACHE_KEY,)).fetchone()
    value = json.loads(row["value"]) if row else None
    return Path(value) if value else None


def _store_folder(conn: sqlite3.Connection, folder: Path | None) -> None:
    with transaction(conn):
        if folder is None:
            conn.execute("DELETE FROM app_settings WHERE key = ?", (CACHE_KEY,))
        else:
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT (key) DO UPDATE SET value = excluded.value,
                                                updated_at = excluded.updated_at
                """,
                (CACHE_KEY, json.dumps(str(folder)), utc_now()),
            )


def _usable(folder: Path) -> bool:
    """The folder exists (created if its drive is there)."""
    if not Path(folder.anchor).exists():
        return False
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return folder.is_dir()


def apply_configured(conn: sqlite3.Connection, settings: Settings) -> None:
    """At startup: use the folder chosen in Settings, if its drive is connected."""
    folder = configured_folder(conn)
    if folder is None:
        return
    if _usable(folder):
        settings.cache_folder = folder
    else:
        # Thumbnails are rebuilt in the default folder meanwhile; Settings warns about it.
        logger.warning("cache folder unavailable, using the default", extra={"folder": str(folder)})


# ------------------------------------------------------------------------------ usage


@dataclass
class _Tally:
    count: int = 0
    bytes: int = 0


_usage_cache: dict[str, tuple[float, dict[str, _Tally]]] = {}
_usage_lock = threading.Lock()


def _entries(folder: Path) -> Iterator[os.DirEntry[str]]:
    root = folder / _SUBDIR
    if not root.is_dir():
        return
    for sub in os.scandir(root):
        if sub.is_dir(follow_symlinks=False):
            for entry in os.scandir(sub.path):
                if entry.is_file(follow_symlinks=False):
                    yield entry


def measure(folder: Path, *, fresh: bool = False) -> dict[str, _Tally]:
    """Files and bytes by kind (thumbs, previews, full, other); remembered for a while."""
    key = str(folder)
    with _usage_lock:
        cached = _usage_cache.get(key)
    if cached and not fresh and time.monotonic() - cached[0] < USAGE_TTL_S:
        return cached[1]
    tally = {kind: _Tally() for kind in ("thumbs", "previews", "full", "other")}
    for entry in _entries(folder):
        match = _KIND.search(entry.name)
        item = tally[_KINDS[match.group(1)] if match else "other"]
        item.count += 1
        # On Windows the size comes with the directory listing (no extra system call).
        item.bytes += entry.stat(follow_symlinks=False).st_size
    with _usage_lock:
        _usage_cache[key] = (time.monotonic(), tally)
    return tally


def _forget_usage() -> None:
    with _usage_lock:
        _usage_cache.clear()


def status(conn: sqlite3.Connection, settings: Settings) -> CacheStatus:
    folder = settings.cache_dir
    chosen = configured_folder(conn)
    tally = measure(folder)
    try:
        free: int | None = shutil.disk_usage(folder).free
    except OSError:
        free = None
    return CacheStatus(
        folder=str(folder),
        default_folder=str(settings.default_cache_dir),
        configured_folder=str(chosen) if chosen else None,
        folder_available=chosen is None or _same(chosen, folder),
        thumbs=CacheUsage(count=tally["thumbs"].count, bytes=tally["thumbs"].bytes),
        previews=CacheUsage(count=tally["previews"].count, bytes=tally["previews"].bytes),
        full=CacheUsage(count=tally["full"].count, bytes=tally["full"].bytes),
        other=CacheUsage(count=tally["other"].count, bytes=tally["other"].bytes),
        total_bytes=sum(item.bytes for item in tally.values()),
        free_bytes=free,
    )


# ------------------------------------------------------------------------------- move


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _inside(child: Path, parent: Path) -> bool:
    child_s = os.path.normcase(os.path.abspath(child))
    parent_s = os.path.normcase(os.path.abspath(parent)).rstrip("\\/")
    return child_s.startswith(parent_s + os.sep)


def _same_drive(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def target_for(folder: str) -> Path:
    """The folder the cache goes to: a drive root gets ``LUMEN Studio\\cache`` inside it."""
    target = Path(os.path.abspath(Path(folder.strip()).expanduser()))
    if target == Path(target.anchor):
        target = target / APP_DIR_NAME / "cache"
    return target


def start_move(conn: sqlite3.Connection, settings: Settings, folder: str) -> int:
    """Check the target folder and queue the move; returns the task id."""
    target = Path(folder.strip()).expanduser()
    if not target.is_absolute():
        raise InvalidPathError("Choose a full folder path", details={"folder": folder})
    target = target_for(folder)
    source = settings.cache_dir
    if _same(target, source):
        raise ConflictError("The cache is already in this folder", details={"folder": str(target)})
    if _inside(target, source):
        raise InvalidPathError(
            "The new folder cannot be inside the current cache folder",
            details={"folder": str(target)},
        )
    if not Path(target.anchor).exists():
        raise InvalidPathError("This drive is not connected", details={"folder": str(target)})
    active = conn.execute(
        "SELECT id FROM tasks WHERE kind = ? AND status IN ('pending', 'running')",
        (MOVE_CACHE_TASK,),
    ).fetchone()
    if active is not None:
        raise ConflictError("The cache is already being moved", details={"task_id": active["id"]})
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".lumen-write-test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise InvalidPathError(
            "This folder cannot be written to", details={"folder": str(target), "error": str(exc)}
        ) from exc

    if not _same_drive(target, source):
        needed = sum(item.bytes for item in measure(source, fresh=True).values())
        free = shutil.disk_usage(target).free
        if needed + SPACE_MARGIN > free:
            raise CacheMoveError(
                "Not enough free space on the target drive",
                details={"needed_bytes": needed + SPACE_MARGIN, "free_bytes": free},
            )
    task_id = queue.enqueue(
        conn, MOVE_CACHE_TASK, payload={"source": str(source), "target": str(target)}
    )
    logger.info("cache move queued", extra={"source": str(source), "target": str(target)})
    return task_id


def _relative_files(folder: Path) -> list[str]:
    root = folder / _SUBDIR
    return [os.path.relpath(entry.path, root) for entry in _entries(folder)]


def _copy_one(source_root: Path, target_root: Path, relative: str) -> int:
    """Copy one file unless an identical-size copy exists; returns the bytes copied."""
    src, dst = source_root / relative, target_root / relative
    try:
        size = src.stat().st_size
    except FileNotFoundError:
        return 0  # pruned meanwhile (full-size renditions have a size limit)
    try:
        if dst.stat().st_size == size:
            return 0
    except FileNotFoundError:
        pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp = dst.with_name(dst.name + ".moving")
    try:
        shutil.copy2(src, temp)
        os.replace(temp, dst)
    except FileNotFoundError:
        temp.unlink(missing_ok=True)
        return 0
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return size


def _copied(source_root: Path, target_root: Path, relative: str) -> bool:
    try:
        return (target_root / relative).stat().st_size == (source_root / relative).stat().st_size
    except FileNotFoundError:
        return False


def _remove_empty_dirs(root: Path) -> None:
    if not root.is_dir():
        return
    for sub in os.scandir(root):
        if sub.is_dir(follow_symlinks=False):
            with contextlib.suppress(OSError):  # not empty
                os.rmdir(sub.path)
    with contextlib.suppress(OSError):
        root.rmdir()


def _disk_full(exc: OSError) -> bool:
    return exc.errno in _DISK_FULL or getattr(exc, "winerror", None) in _DISK_FULL


def move_cache(ctx: TaskContext) -> dict[str, object]:
    """Copy the cache to the new folder, switch to it, then delete the old files.

    Progress counts each file twice (copied, then deleted). Interrupted (app closed) it
    resumes: copied files are skipped, and once the switch is done only the deletion is
    left. Cancelled while copying, the copies are removed and nothing changes.
    """
    source = Path(str(ctx.payload["source"]))
    target = Path(str(ctx.payload["target"]))
    source_root, target_root = source / _SUBDIR, target / _SUBDIR
    settings = ctx.settings
    copied_bytes = 0
    total = 0

    if not _same(settings.cache_dir, target):
        files = _relative_files(source)
        total = 2 * len(files)
        ctx.progress(0, total, force=True)
        try:
            if files and _same_drive(source, target) and not target_root.exists():
                os.replace(source_root, target_root)  # same drive: renaming is instant
            else:
                with ThreadPoolExecutor(COPY_WORKERS, thread_name_prefix="cache-move") as pool:
                    for start in range(0, len(files), CHUNK):
                        chunk = files[start : start + CHUNK]
                        copied_bytes += sum(
                            pool.map(lambda rel: _copy_one(source_root, target_root, rel), chunk)
                        )
                        ctx.progress(start + len(chunk), total)
                # Files rendered (e.g. shown on screen) while copying.
                for rel in _relative_files(source):
                    copied_bytes += _copy_one(source_root, target_root, rel)
        except TaskCancelled:
            _discard_copies(source_root, target_root, files)
            raise
        except OSError as exc:
            if _disk_full(exc):
                raise PermanentTaskError("The target drive is full") from exc
            raise
        stored = None if _same(target, settings.default_cache_dir) else target
        _store_folder(ctx.conn, stored)
        settings.cache_folder = target
        _forget_usage()
        logger.info("cache folder switched", extra={"source": str(source), "target": str(target)})

    # The new folder is in use: delete the old files.
    files = _relative_files(source)
    total = max(total, 2 * len(files))
    start_at = total - len(files)
    for start in range(0, len(files), CHUNK):
        for rel in files[start : start + CHUNK]:
            if not (target_root / rel).exists():
                _copy_one(source_root, target_root, rel)  # rendered just as we switched
            (source_root / rel).unlink(missing_ok=True)
        ctx.progress(start_at + min(start + CHUNK, len(files)), total)
    _remove_empty_dirs(source_root)
    _forget_usage()
    ctx.progress(total, total, force=True)
    return {"target": str(target), "copied_bytes": copied_bytes, "removed": len(files)}


def _discard_copies(source_root: Path, target_root: Path, files: list[str]) -> None:
    """Undo a cancelled copy: remove the copies (the originals stay in use)."""
    for rel in files:
        if _copied(source_root, target_root, rel):
            (target_root / rel).unlink(missing_ok=True)
    _remove_empty_dirs(target_root)
