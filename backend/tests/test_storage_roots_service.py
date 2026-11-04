from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lumen.core.errors import ConflictError, InvalidPathError, NotFoundError
from lumen.db.connection import utc_now
from lumen.library.drives import check_roots
from lumen.schemas.storage_roots import StorageRootCreate
from lumen.services import storage_roots as service


def _create(conn: sqlite3.Connection, path: Path | str, name: str | None = None) -> int:
    return service.create_storage_root(
        conn, StorageRootCreate(path=str(path), display_name=name)
    ).id


def test_register_root_and_queue_scan(conn: sqlite3.Connection, photo_dir: Path) -> None:
    root = service.create_storage_root(conn, StorageRootCreate(path=str(photo_dir)))

    assert root.path == str(photo_dir)
    assert root.display_name == "Photos"
    assert root.status == "pending_scan"
    assert root.is_available is True

    task = conn.execute("SELECT * FROM tasks WHERE storage_root_id = ?", (root.id,)).fetchone()
    assert task["kind"] == service.SCAN_TASK_KIND
    assert task["status"] == "pending"


def test_custom_display_name(conn: sqlite3.Connection, photo_dir: Path) -> None:
    root_id = _create(conn, photo_dir, "旅行 2026")
    assert service.get_storage_root(conn, root_id).display_name == "旅行 2026"


def test_path_is_normalized(conn: sqlite3.Connection, photo_dir: Path) -> None:
    messy = f"{photo_dir}{Path('/2026/..')}"
    root = service.create_storage_root(conn, StorageRootCreate(path=messy))
    assert root.path == str(photo_dir)


@pytest.mark.parametrize("bad", ["relative/path", "\x00"])
def test_rejects_invalid_paths(conn: sqlite3.Connection, bad: str) -> None:
    with pytest.raises(InvalidPathError):
        _create(conn, bad)


def test_rejects_missing_directory(conn: sqlite3.Connection, tmp_path: Path) -> None:
    with pytest.raises(InvalidPathError, match="does not exist"):
        _create(conn, tmp_path / "missing")


def test_rejects_file(conn: sqlite3.Connection, photo_dir: Path) -> None:
    with pytest.raises(InvalidPathError, match="not a directory"):
        _create(conn, photo_dir / "2026" / "IMG_0001.JPG")


def test_rejects_duplicate(conn: sqlite3.Connection, photo_dir: Path) -> None:
    _create(conn, photo_dir)
    with pytest.raises(ConflictError, match="already registered"):
        _create(conn, photo_dir)


@pytest.mark.skipif(not Path("C:/").exists(), reason="case-insensitive file system only")
def test_rejects_duplicate_with_different_case(conn: sqlite3.Connection, photo_dir: Path) -> None:
    _create(conn, photo_dir)
    with pytest.raises(ConflictError):
        _create(conn, str(photo_dir).upper())


def test_rejects_nested_roots(conn: sqlite3.Connection, photo_dir: Path) -> None:
    _create(conn, photo_dir / "2026")
    with pytest.raises(ConflictError, match="contains"):
        _create(conn, photo_dir)

    other = photo_dir.parent / "Other"
    (other / "inner").mkdir(parents=True)
    _create(conn, other)
    with pytest.raises(ConflictError, match="inside"):
        _create(conn, other / "inner")


def test_sibling_with_common_prefix_is_allowed(conn: sqlite3.Connection, tmp_path: Path) -> None:
    (tmp_path / "Photos").mkdir()
    (tmp_path / "Photos2").mkdir()
    _create(conn, tmp_path / "Photos")
    _create(conn, tmp_path / "Photos2")
    assert len(service.list_storage_roots(conn)) == 2


def test_unavailable_root_is_reported(conn: sqlite3.Connection, tmp_path: Path) -> None:
    directory = tmp_path / "External"
    directory.mkdir()
    root_id = _create(conn, directory)
    directory.rmdir()  # simulate a disconnected drive
    check_roots(conn)  # what the drive watcher does every 30 s
    assert service.get_storage_root(conn, root_id).is_available is False
    assert service.get_storage_root(conn, root_id).status == "offline"


def test_delete_removes_records_but_not_files(conn: sqlite3.Connection, photo_dir: Path) -> None:
    root_id = _create(conn, photo_dir)
    now = utc_now()
    asset_id = conn.execute(
        "INSERT INTO media_assets (uuid, media_type, created_at, updated_at) "
        "VALUES ('a-1', 'photo', ?, ?)",
        (now, now),
    ).lastrowid
    file_id = conn.execute(
        "INSERT INTO media_files (asset_id, storage_root_id, relative_path, relative_path_key, "
        "file_name, extension, size_bytes, modified_at, created_at, updated_at) "
        "VALUES (?, ?, '2026\\IMG_0001.JPG', '2026\\img_0001.jpg', 'IMG_0001.JPG', 'jpg', 14, "
        "?, ?, ?)",
        (asset_id, root_id, now, now, now),
    ).lastrowid
    conn.execute(
        "INSERT INTO media_metadata (file_id, extractor, extractor_version, extracted_at) "
        "VALUES (?, 'test', '1', ?)",
        (file_id, now),
    )

    service.delete_storage_root(conn, root_id)

    for table in ("storage_roots", "media_files", "media_metadata", "media_assets", "tasks"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    original = photo_dir / "2026" / "IMG_0001.JPG"
    assert original.read_bytes() == b"\xff\xd8\xff\xe0original"


def test_delete_keeps_assets_with_files_elsewhere(conn: sqlite3.Connection, tmp_path: Path) -> None:
    (tmp_path / "A").mkdir()
    (tmp_path / "B").mkdir()
    root_a = _create(conn, tmp_path / "A")
    root_b = _create(conn, tmp_path / "B")
    now = utc_now()
    asset_id = conn.execute(
        "INSERT INTO media_assets (uuid, media_type, created_at, updated_at) "
        "VALUES ('a-1', 'photo', ?, ?)",
        (now, now),
    ).lastrowid
    for root_id in (root_a, root_b):  # the same photo copied to two drives
        conn.execute(
            "INSERT INTO media_files (asset_id, storage_root_id, relative_path, "
            "relative_path_key, file_name, extension, size_bytes, modified_at, created_at, "
            "updated_at) VALUES (?, ?, 'x.jpg', 'x.jpg', 'x.jpg', 'jpg', 1, ?, ?, ?)",
            (asset_id, root_id, now, now, now),
        )

    service.delete_storage_root(conn, root_a)

    assert conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM media_files").fetchone()[0] == 1


def test_delete_unknown_root(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        service.delete_storage_root(conn, 42)
