"""Cache folder setting and moving the cache (ADR-031)."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import string
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lumen.core.config import Settings
from lumen.core.errors import ConflictError, InvalidPathError
from lumen.services import cache
from lumen.tasks import queue
from lumen.tasks.runner import TaskCancelled, TaskContext


def _fill(folder: Path) -> dict[str, bytes]:
    """A small cache: two thumbnails, two previews, one full-size rendition."""
    files = {
        "ab/ab12_t1.jpg": b"t" * 10,
        "ab/ab12_p1.jpg": b"p" * 100,
        "cd/cd34_t1.jpg": b"t" * 12,
        "cd/cd34_p1.jpg": b"p" * 120,
        "cd/cd34-e5_f1.jpg": b"f" * 1000,
    }
    for relative, content in files.items():
        path = folder / "renditions" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return files


def _stored(conn: sqlite3.Connection) -> Any:
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'cache_folder'").fetchone()
    return json.loads(row["value"]) if row else None


def _run_move(conn: sqlite3.Connection, settings: Settings, folder: Path) -> dict[str, object]:
    task_id = cache.start_move(conn, settings, str(folder))
    task = queue.claim_next(conn)
    assert task is not None and task["id"] == task_id
    ctx = TaskContext(
        conn=conn, settings=settings, task_id=task_id, kind=cache.MOVE_CACHE_TASK,
        storage_root_id=None, payload=json.loads(task["payload"]),
        stop_event=threading.Event(), enqueue=lambda *a, **k: 0,
    )  # fmt: skip
    result = cache.move_cache(ctx)
    queue.mark_succeeded(conn, task_id)
    return result


def _missing_drive() -> str:
    used = {name[0] for name in os.listdrives()} if hasattr(os, "listdrives") else set()
    for letter in reversed(string.ascii_uppercase):
        if letter not in used and not Path(f"{letter}:\\").exists():
            return f"{letter}:\\LUMEN cache"
    pytest.skip("every drive letter is in use")


@pytest.fixture(autouse=True)
def _fresh_usage() -> None:
    cache._forget_usage()


def test_cache_dir_defaults_to_the_data_folder(settings: Settings, tmp_path: Path) -> None:
    assert settings.cache_dir == settings.data_dir / "cache" == settings.default_cache_dir
    settings.cache_folder = tmp_path / "elsewhere"
    assert settings.cache_dir == tmp_path / "elsewhere"


def test_status_counts_files_by_kind(conn: sqlite3.Connection, settings: Settings) -> None:
    _fill(settings.cache_dir)
    (settings.cache_dir / "renditions" / "ab" / "stray.tmp").write_bytes(b"x")
    status = cache.status(conn, settings)
    assert (status.thumbs.count, status.thumbs.bytes) == (2, 22)
    assert (status.previews.count, status.previews.bytes) == (2, 220)
    assert (status.full.count, status.full.bytes) == (1, 1000)
    assert status.other.count == 1
    assert status.total_bytes == 1243
    assert status.folder == status.default_folder == str(settings.default_cache_dir)
    assert status.configured_folder is None and status.folder_available
    assert status.free_bytes and status.free_bytes > 0


def test_move_copies_switches_and_removes_old_files(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache, "_same_drive", lambda a, b: False)  # copy, as across drives
    monkeypatch.setattr(cache, "CHUNK", 2)
    files = _fill(settings.cache_dir)
    target = tmp_path / "D" / "LUMEN cache"

    result = _run_move(conn, settings, target)

    assert result["copied_bytes"] == 1242 and result["removed"] == 5
    for relative, content in files.items():
        assert (target / "renditions" / relative).read_bytes() == content
    assert not (settings.default_cache_dir / "renditions").exists()
    assert settings.cache_dir == target
    assert _stored(conn) == str(target)
    status = cache.status(conn, settings)
    assert status.folder == status.configured_folder == str(target)
    assert status.total_bytes == 1242

    # And back to the default folder: the setting is cleared.
    _run_move(conn, settings, settings.default_cache_dir)
    assert settings.cache_dir == settings.default_cache_dir
    assert _stored(conn) is None
    assert (settings.default_cache_dir / "renditions" / "cd" / "cd34_p1.jpg").exists()
    assert not (target / "renditions").exists()


def test_move_on_the_same_drive_renames_the_folder(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fill(settings.cache_dir)
    monkeypatch.setattr(cache, "_copy_one", lambda *a: pytest.fail("should rename, not copy"))
    target = tmp_path / "moved"
    _run_move(conn, settings, target)
    assert (target / "renditions" / "ab" / "ab12_p1.jpg").exists()
    assert settings.cache_dir == target


def test_cancelled_move_removes_the_copies(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache, "_same_drive", lambda a, b: False)
    monkeypatch.setattr(cache, "CHUNK", 2)
    monkeypatch.setattr(cache, "COPY_WORKERS", 1)
    _fill(settings.cache_dir)
    target = tmp_path / "D"
    copy_one = cache._copy_one
    cancelled = threading.Event()

    def copy_then_cancel(source: Path, dest: Path, relative: str) -> int:
        cancelled.set()  # the user cancels while the first files are copied
        return copy_one(source, dest, relative)

    report = queue.report_progress
    monkeypatch.setattr(cache, "_copy_one", copy_then_cancel)
    monkeypatch.setattr(
        queue, "report_progress", lambda *a: report(*a) and not cancelled.is_set()
    )
    monkeypatch.setattr("lumen.tasks.runner.PROGRESS_INTERVAL_S", 0)
    with pytest.raises(TaskCancelled):
        _run_move(conn, settings, target)
    assert not (target / "renditions").exists()
    assert settings.cache_dir == settings.default_cache_dir and _stored(conn) is None
    assert len(list((settings.default_cache_dir / "renditions").rglob("*.jpg"))) == 5


def test_resumed_move_only_deletes_after_the_switch(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The app was closed after switching folders: the old files are deleted on restart."""
    monkeypatch.setattr(cache, "_same_drive", lambda a, b: False)
    files = _fill(settings.cache_dir)
    target = tmp_path / "D"
    shutil.copytree(settings.cache_dir / "renditions", target / "renditions")
    (settings.cache_dir / "renditions" / "ef").mkdir()
    (settings.cache_dir / "renditions" / "ef" / "ef56_t1.jpg").write_bytes(b"late")  # at the switch
    task_id = queue.enqueue(
        conn, cache.MOVE_CACHE_TASK,
        payload={"source": str(settings.cache_dir), "target": str(target)},
    )  # fmt: skip
    cache._store_folder(conn, target)
    settings.cache_folder = target
    queue.claim_next(conn)
    ctx = TaskContext(
        conn=conn, settings=settings, task_id=task_id, kind=cache.MOVE_CACHE_TASK,
        storage_root_id=None, payload=json.loads(queue.get(conn, task_id)["payload"]),
        stop_event=threading.Event(), enqueue=lambda *a, **k: 0,
    )  # fmt: skip
    result = cache.move_cache(ctx)
    assert result["removed"] == len(files) + 1
    assert (target / "renditions" / "ef" / "ef56_t1.jpg").read_bytes() == b"late"
    assert not (settings.default_cache_dir / "renditions").exists()


def test_start_move_checks_the_target(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.ensure_directories()
    with pytest.raises(ConflictError):
        cache.start_move(conn, settings, str(settings.cache_dir))
    with pytest.raises(InvalidPathError):
        cache.start_move(conn, settings, str(settings.cache_dir / "renditions" / "sub"))
    with pytest.raises(InvalidPathError):
        cache.start_move(conn, settings, "relative\\folder")
    with pytest.raises(InvalidPathError):
        cache.start_move(conn, settings, _missing_drive())

    _fill(settings.cache_dir)
    monkeypatch.setattr(cache, "_same_drive", lambda a, b: False)
    monkeypatch.setattr(
        cache.shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(10**12, 10**12, 2**30)
    )
    with pytest.raises(cache.CacheMoveError) as error:
        cache.start_move(conn, settings, str(tmp_path / "small"))
    assert error.value.details["free_bytes"] == 2**30

    monkeypatch.undo()
    cache.start_move(conn, settings, str(tmp_path / "ok"))
    with pytest.raises(ConflictError):  # one move at a time
        cache.start_move(conn, settings, str(tmp_path / "other"))


def test_a_drive_root_gets_its_own_folder() -> None:
    assert cache.target_for("D:\\") == Path("D:\\LUMEN Studio\\cache")
    assert cache.target_for(" D:\\Cache ") == Path("D:\\Cache")


def test_missing_drive_falls_back_to_the_default(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    folder = Path(_missing_drive())
    cache._store_folder(conn, folder)
    cache.apply_configured(conn, settings)
    assert settings.cache_dir == settings.default_cache_dir
    status = cache.status(conn, settings)
    assert status.configured_folder == str(folder) and not status.folder_available


def test_startup_applies_the_chosen_folder(settings: Settings, tmp_path: Path) -> None:
    from lumen.app import create_app
    from lumen.db.connection import Database
    from lumen.db.migrator import migrate

    settings.ensure_directories()
    db = Database(settings.database_path)
    migrate(db, backup_dir=settings.backup_dir)
    with db.session() as conn:
        cache._store_folder(conn, tmp_path / "D cache")
    with TestClient(create_app(settings, "t"), headers={"Authorization": "Bearer t"}) as client:
        body = client.get("/api/v1/cache").json()
        assert body["folder"] == str(tmp_path / "D cache") and body["folder_available"]
        assert (tmp_path / "D cache").is_dir()


def test_move_api(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    response = client.post("/api/v1/cache/move", json={"folder": str(tmp_path / "new")})
    assert response.status_code == 202
    assert response.json()["kind"] == "move_cache"
    assert response.json()["status"] == "pending"
    again = client.post("/api/v1/cache/move", json={"folder": str(tmp_path / "other")})
    assert again.status_code == 409
    bad = client.post("/api/v1/cache/move", json={"folder": "relative"})
    assert bad.status_code == 422
