"""Import from iPhone with a fake phone (the real one goes through Windows Portable Devices)."""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen.core.config import Settings
from lumen.library import phone_import
from lumen.library.common import SCAN_TASK
from lumen.media.phone import PhoneDevice, PhoneError, PhoneFile
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskContext, TaskInterrupted

SERIAL = "F2LXK0001"
DEVICE = "0123456789abcdef"


def photo(
    name: str, data: bytes, when: datetime | None = datetime(2026, 11, 3, 9, 30)
) -> PhoneFile:
    return PhoneFile(
        object_id=f"o-{name}", key=f"k-{name}", name=name, size=len(data), created=when,
        folder="100APPLE",
    )  # fmt: skip


class FakePhone:
    def __init__(self, files: dict[str, bytes], *, status: str = "ready") -> None:
        self.data = files
        self.files_ = [photo(name, data) for name, data in files.items()]
        self.status = status
        self.fail_after: int | None = None  # unplugged after reading this many files
        self.reads = 0
        self.open_streams = 0
        self.streams_open_at_close: list[int] = []

    def devices(self) -> list[PhoneDevice]:
        return [PhoneDevice(DEVICE, "Kevin's iPhone", SERIAL, self.status)]  # type: ignore[arg-type]

    @contextlib.contextmanager
    def open(self, device_id: str) -> Iterator[FakePhone]:
        if device_id != DEVICE:
            raise PhoneError("The phone is not connected")
        try:
            yield self
        finally:
            self.streams_open_at_close.append(self.open_streams)

    def files(self) -> Iterator[PhoneFile]:
        yield from self.files_

    def read(self, file: PhoneFile) -> Iterator[bytes]:
        if self.fail_after is not None and self.reads >= self.fail_after:
            raise PhoneError("Reading the phone failed")
        self.reads += 1
        self.open_streams += 1
        try:
            data = self.data[file.name]
            yield data[: len(data) // 2]
            yield data[len(data) // 2 :]
        finally:
            self.open_streams -= 1


@pytest.fixture
def phone(monkeypatch: pytest.MonkeyPatch) -> FakePhone:
    fake = FakePhone(
        {
            "IMG_0001.HEIC": b"heic-one" * 100,
            "IMG_0001.MOV": b"mov-one" * 300,
            "IMG_E0001.HEIC": b"edited" * 100,
            "IMG_0002.JPG": b"jpeg-two" * 50,
        }
    )
    monkeypatch.setattr(phone_import, "SOURCE", fake)
    return fake


def run(
    conn: sqlite3.Connection, settings: Settings, dest: Path, stop: threading.Event | None = None,
    **extra: object,
) -> object:  # fmt: skip
    payload = {"device_id": DEVICE, "serial": SERIAL, "dest": str(dest), **extra}
    task_id = queue.enqueue(conn, phone_import.PHONE_IMPORT_TASK, payload=payload, unique=False)
    task = queue.claim_next(conn)
    assert task is not None and task["id"] == task_id
    ctx = TaskContext(
        conn=conn, settings=settings, task_id=task_id, kind=phone_import.PHONE_IMPORT_TASK,
        storage_root_id=None, payload=payload, stop_event=stop or threading.Event(),
        enqueue=lambda *a, **k: 0,
    )  # fmt: skip
    return phone_import.import_from_phone(ctx)


def files_in(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def test_copies_new_photos_by_month_and_only_once(
    conn: sqlite3.Connection, settings: Settings, phone: FakePhone, tmp_path: Path
) -> None:
    dest = tmp_path / "照片" / "iPhone"
    result = run(conn, settings, dest)
    assert files_in(dest) == [
        "2026/2026-11/IMG_0001.HEIC",
        "2026/2026-11/IMG_0001.MOV",  # the Live Photo stays a pair
        "2026/2026-11/IMG_0002.JPG",
    ]  # the version edited on the phone is left out
    assert (dest / "2026/2026-11/IMG_0001.MOV").read_bytes() == phone.data["IMG_0001.MOV"]
    assert result == {
        "copied": 3, "bytes": 800 + 2100 + 400, "already": 0, "folder": str(dest),
        "storage_root_id": 1,
    }  # fmt: skip
    root = conn.execute("SELECT path, status FROM storage_roots").fetchone()
    assert (root["path"], root["status"]) == (str(dest), "pending_scan")  # added and scanned

    phone.files_.append(photo("IMG_0003.HEIC", b"new"))
    phone.data["IMG_0003.HEIC"] = b"new"
    again = run(conn, settings, dest)
    assert isinstance(again, dict) and (again["copied"], again["already"]) == (1, 3)
    assert phone.reads == 4  # nothing copied twice


def test_edited_versions_on_request(
    conn: sqlite3.Connection, settings: Settings, phone: FakePhone, tmp_path: Path
) -> None:
    run(conn, settings, tmp_path / "out", include_edited=True)
    assert "2026/2026-11/IMG_E0001.HEIC" in files_in(tmp_path / "out")


def test_photos_already_in_the_library_are_not_copied(
    conn: sqlite3.Connection, settings: Settings, phone: FakePhone, tmp_path: Path
) -> None:
    conn.execute(
        "INSERT INTO storage_roots (path, path_key, display_name, status, created_at, updated_at)"
        " VALUES ('D:\\old', 'd:\\old', 'old', 'ready', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO media_files (storage_root_id, relative_path, relative_path_key, file_name,"
        " extension, size_bytes, modified_at, created_at, updated_at)"
        " VALUES (1, 'img_0002.jpg', 'img_0002.jpg', 'img_0002.jpg', 'jpg', 400, 'n', 'n', 'n')"
    )
    result = run(conn, settings, tmp_path / "out")
    assert isinstance(result, dict) and (result["copied"], result["already"]) == (2, 1)
    assert "2026/2026-11/IMG_0002.JPG" not in files_in(tmp_path / "out")


def test_a_name_taken_by_another_file_renames_the_whole_live_photo(
    conn: sqlite3.Connection, settings: Settings, phone: FakePhone, tmp_path: Path
) -> None:
    month = tmp_path / "out" / "2026" / "2026-11"
    month.mkdir(parents=True)
    (month / "IMG_0001.MOV").write_bytes(b"some other video")
    run(conn, settings, tmp_path / "out")
    assert (month / "IMG_0001.MOV").read_bytes() == b"some other video"  # never overwritten
    assert (month / "IMG_0001_2.HEIC").exists() and (month / "IMG_0001_2.MOV").exists()


def test_unplugged_midway_resumes_where_it_stopped(
    conn: sqlite3.Connection, settings: Settings, phone: FakePhone, tmp_path: Path
) -> None:
    phone.fail_after = 1
    with pytest.raises(PermanentTaskError):
        run(conn, settings, tmp_path / "out")
    assert not [p for p in (tmp_path / "out").rglob("*.part")]  # no half files left
    copied_first = files_in(tmp_path / "out")
    assert len(copied_first) == 1

    phone.fail_after = None
    result = run(conn, settings, tmp_path / "out")
    assert isinstance(result, dict) and result["copied"] == 2
    assert len(files_in(tmp_path / "out")) == 3


def test_stopped_midway_the_file_stream_is_released_before_the_phone_is_closed(
    conn: sqlite3.Connection, settings: Settings, phone: FakePhone, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """Releasing a WPD stream after the phone was closed crashed the backend (access
    violation): the stream must be released as soon as the import stops."""
    stop = threading.Event()
    original = phone.read

    def read(file: PhoneFile) -> Iterator[bytes]:
        for chunk in original(file):
            stop.set()  # stopped (app closing, cancelled) in the middle of a file
            yield chunk

    monkeypatch.setattr(phone, "read", read)
    with pytest.raises(TaskInterrupted):
        run(conn, settings, tmp_path / "out", stop=stop)
    assert phone.streams_open_at_close == [0]
    assert not list((tmp_path / "out").rglob("*.part"))


def test_scans_the_library_folder_that_holds_the_destination(
    conn: sqlite3.Connection, settings: Settings, phone: FakePhone, tmp_path: Path
) -> None:
    library = tmp_path / "照片"
    library.mkdir()
    conn.execute(
        "INSERT INTO storage_roots (path, path_key, display_name, status, created_at, updated_at)"
        " VALUES (?, ?, '照片', 'ready', 'now', 'now')",
        (str(library), str(library).lower()),
    )
    from lumen.services.storage_roots import path_key

    conn.execute("UPDATE storage_roots SET path_key = ?", (path_key(library),))
    run(conn, settings, library / "iPhone")
    assert conn.execute("SELECT COUNT(*) FROM storage_roots").fetchone()[0] == 1
    scans = conn.execute("SELECT COUNT(*) FROM tasks WHERE kind = ?", (SCAN_TASK,)).fetchone()
    assert scans[0] == 1


def test_api_lists_counts_and_starts(client: TestClient, phone: FakePhone, tmp_path: Path) -> None:
    listed = client.get("/api/v1/phones").json()
    assert listed["items"] == [{"id": DEVICE, "name": "Kevin's iPhone", "status": "ready"}]
    assert listed["include_edited"] is False and listed["available"] is True

    summary = client.get(f"/api/v1/phones/{DEVICE}/summary").json()
    assert summary == {"total": 3, "new_count": 3, "new_bytes": 3300, "already": 0}

    folder = str(tmp_path / "iPhone")
    task = client.post(f"/api/v1/phones/{DEVICE}/import", json={"folder": folder})
    assert task.status_code == 202 and task.json()["kind"] == "phone_import"
    assert client.get("/api/v1/phones").json()["folder"] == folder  # remembered

    assert client.get("/api/v1/phones/fedcba9876543210/summary").status_code == 404
    phone.status = "locked"
    assert client.post(f"/api/v1/phones/{DEVICE}/import", json={}).status_code == 409
