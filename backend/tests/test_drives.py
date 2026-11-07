"""External drives: offline while unplugged, nothing marked missing, back when plugged in
(also under another drive letter). ADR-028."""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

import pytest

from lumen.core.config import Settings
from lumen.core.volumes import logical_drives
from lumen.db.connection import Database
from lumen.library import drives, ingest
from lumen.library.common import SCAN_TASK
from lumen.library.drives import check_roots
from lumen.library.handlers import HANDLERS
from lumen.media import walker
from lumen.tasks.runner import TaskRunner
from tests.media_factory import make_jpeg
from tests.test_develop import NOW
from tests.test_pipeline import register, wait_idle

needs_tools = pytest.mark.skipif(
    not (shutil.which("exiftool") and shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="exiftool and ffmpeg are required",
)


def free_letter() -> str:
    present = logical_drives() or set()
    return next(letter for letter in "QRSTUVWXYZ" if letter not in present)


def rename_folder(folder: Path, target: Path, timeout: float = 10) -> None:
    """Rename ``folder`` (a drive going away or coming back). Windows refuses while any
    file in it is open: the import's ExifTool reading the files already claimed, or the
    antivirus looking at the just written ones. Those handles are brief: wait for them."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            folder.rename(target)
            return
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.02)


def add_root(conn: sqlite3.Connection, path: str, *, status: str, serial: str | None = None) -> int:
    root_id = conn.execute(
        "INSERT INTO storage_roots (path, path_key, display_name, volume_serial, status, "
        "last_scanned_at, created_at, updated_at) VALUES (?, ?, 'Photos', ?, ?, ?, ?, ?)",
        (path, path.lower(), serial, status, NOW, NOW, NOW),
    ).lastrowid
    assert root_id is not None
    return root_id


def status(conn: sqlite3.Connection, root_id: int) -> str:
    row = conn.execute("SELECT status FROM storage_roots WHERE id = ?", (root_id,)).fetchone()
    return str(row[0])


def scans(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM tasks WHERE kind = 'scan_storage_root'").fetchone()
    return int(row[0])


@pytest.mark.skipif(logical_drives() is None, reason="Windows drive letters")
def test_roots_go_offline_and_come_back(conn: sqlite3.Connection, tmp_path: Path) -> None:
    unplugged = add_root(conn, f"{free_letter()}:\\Photos", status="ready")
    here = add_root(conn, str(tmp_path), status="offline")
    assert check_roots(conn)  # a scan was queued for the root that is back
    assert status(conn, unplugged) == "offline"
    assert status(conn, here) == "ready"
    assert scans(conn) == 1
    assert not check_roots(conn)  # nothing changed: nothing queued
    assert scans(conn) == 1


def test_a_drive_is_followed_to_its_new_letter(
    conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "Photos"
    make_jpeg(folder / "2024" / "IMG_0001.JPG")
    real_letter = str(tmp_path)[0].upper()
    old_letter = free_letter()
    root_id = add_root(conn, f"{old_letter}:{str(folder)[2:]}", status="offline", serial="ABCD1234")
    size = (folder / "2024" / "IMG_0001.JPG").stat().st_size
    conn.execute(
        "INSERT INTO media_files (storage_root_id, relative_path, relative_path_key, file_name, "
        "extension, size_bytes, modified_at, created_at, updated_at) "
        "VALUES (?, '2024\\IMG_0001.JPG', '2024\\img_0001.jpg', 'IMG_0001.JPG', 'jpg', ?, ?, ?, ?)",
        (root_id, size, NOW, NOW, NOW),
    )
    monkeypatch.setattr(drives, "logical_drives", lambda: {real_letter})
    # Another volume with the same serial elsewhere is not enough: the files must match.
    monkeypatch.setattr(drives, "find_volume", lambda serial, letters: [real_letter])
    conn.execute("UPDATE media_files SET size_bytes = size_bytes + 1")
    assert not check_roots(conn)
    assert status(conn, root_id) == "offline"

    conn.execute("UPDATE media_files SET size_bytes = ?", (size,))
    monkeypatch.setattr(drives, "logical_drives", lambda: {real_letter, "Z"})  # drives changed
    assert check_roots(conn)
    row = conn.execute("SELECT path, status FROM storage_roots WHERE id = ?", (root_id,)).fetchone()
    assert (row["path"], row["status"]) == (str(folder), "ready")


@needs_tools
def test_unreadable_folders_do_not_make_photos_missing(
    conn: sqlite3.Connection, db: Database, settings: Settings, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    root = tmp_path / "Photos"
    for folder in ("2023", "2024"):
        make_jpeg(root / folder / f"IMG_{folder}.JPG")
    runner = TaskRunner(db, settings, HANDLERS)
    runner.start()
    try:
        root_id = register(conn, runner, root)
        wait_idle(db)
        # The 2024 folder cannot be read during the next scan (permissions, a hiccup...).
        original = walker.os.scandir

        def scandir(path: object) -> object:
            if str(path).endswith("2024"):
                raise PermissionError("access denied")
            return original(path)  # type: ignore[arg-type]

        monkeypatch.setattr(walker.os, "scandir", scandir)
        runner.enqueue(SCAN_TASK, storage_root_id=root_id)
        wait_idle(db)
    finally:
        runner.stop()
    states = dict(conn.execute("SELECT file_name, status FROM media_files").fetchall())
    assert states == {"IMG_2023.JPG": "present", "IMG_2024.JPG": "present"}


@needs_tools
def test_an_import_stops_when_the_drive_goes_and_resumes(
    conn: sqlite3.Connection, db: Database, settings: Settings, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    root = tmp_path / "Photos"
    for index in range(12):
        make_jpeg(root / f"IMG_{index:04d}.JPG")
    gone = tmp_path / "Unplugged"
    original = ingest._prepare
    unplugged = False

    def prepare(item: ingest.WorkItem, *args: object) -> None:
        nonlocal unplugged
        if not unplugged and item.relative_path == "IMG_0005.JPG":
            unplugged = True
            rename_folder(root, gone)  # the drive goes away while importing
        original(item, *args)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest, "_prepare", prepare)
    monkeypatch.setattr(ingest, "STORE_SIZE", 2)
    runner = TaskRunner(db, settings.model_copy(update={"ingest_workers": 1}), HANDLERS)
    runner.start()
    try:
        root_id = register(conn, runner, root)
        wait_idle(db)
        assert status(conn, root_id) == "offline"
        states = dict(
            conn.execute("SELECT status, COUNT(*) FROM media_files GROUP BY 1").fetchall()
        )
        assert states == {"present": 12}  # nothing marked missing
        pending = conn.execute(
            "SELECT COUNT(*), MAX(ingest_attempts) FROM media_files WHERE ingest_state = 'pending'"
        ).fetchone()
        assert pending[0] > 0 and pending[1] == 0  # not charged an attempt

        rename_folder(gone, root)  # plugged back in: the watcher finds it and the import resumes
        assert check_roots(conn)
        runner.wake()
        wait_idle(db)
    finally:
        runner.stop()
    assert status(conn, root_id) == "ready"
    done = conn.execute("SELECT COUNT(*) FROM media_files WHERE ingest_state = 'done'")
    assert done.fetchone()[0] == 12


@needs_tools
def test_photo_quality_is_measured_during_the_import(
    conn: sqlite3.Connection, db: Database, settings: Settings, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from lumen.library.quality import QUALITY_TASK

    root = tmp_path / "Photos"
    for index in range(3):
        make_jpeg(root / f"IMG_{index:04d}.JPG")
    monkeypatch.setitem(HANDLERS, QUALITY_TASK, lambda ctx: None)  # no separate pass
    runner = TaskRunner(db, settings, HANDLERS)
    runner.start()
    try:
        register(conn, runner, root)
        wait_idle(db)
    finally:
        runner.stop()
    rows = conn.execute(
        "SELECT COUNT(*) FROM media_quality q JOIN media_assets a ON a.id = q.asset_id "
        "JOIN media_files c ON c.id = a.cover_file_id AND c.fingerprint = q.fingerprint "
        "WHERE q.score IS NOT NULL"
    ).fetchone()[0]
    assert rows == 3
