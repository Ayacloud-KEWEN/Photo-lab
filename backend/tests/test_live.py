"""Live Photo pairing rules (lumen.library.live), on hand-built rows."""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from lumen.library.common import group_key, path_key
from lumen.library.live import is_live_match, pair_live_photo

NOW = "2026-01-01T00:00:00.000Z"
SAME_ID = "01D781D5-2B6F-41E1-A6C5-BCBC91DD19CA"


@pytest.fixture
def root(conn: sqlite3.Connection) -> int:
    conn.execute(
        "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, updated_at) "
        "VALUES (1, 'D:\\Phone', 'd:\\phone', 'Phone', ?, ?)",
        (NOW, NOW),
    )
    return 1


def add(
    conn: sqlite3.Connection,
    relative_path: str,
    *,
    content_id: str | None = None,
    duration_ms: int | None = None,
    state: str = "done",
) -> int:
    """A file in its own asset (as ingestion leaves it before pairing); returns the file id."""
    extension = relative_path.rsplit(".", 1)[1].lower()
    media_type = "video" if extension == "mov" else "photo"
    asset_id = conn.execute(
        "INSERT INTO media_assets (uuid, media_type, capture_time, created_at, updated_at) "
        "VALUES (?, ?, '2025-01-01T10:00:00', ?, ?)",
        (str(uuid.uuid4()), media_type, NOW, NOW),
    ).lastrowid
    file_id = conn.execute(
        """
        INSERT INTO media_files (storage_root_id, relative_path, relative_path_key, group_key,
            file_name, extension, asset_id, size_bytes, modified_at, ingest_state,
            created_at, updated_at)
        VALUES (1, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """,
        (
            relative_path, path_key(relative_path), group_key(relative_path),
            relative_path.rsplit("\\", 1)[-1], extension, asset_id, NOW, state, NOW, NOW,
        ),
    ).lastrowid  # fmt: skip
    conn.execute("UPDATE media_assets SET cover_file_id = ? WHERE id = ?", (file_id, asset_id))
    conn.execute(
        "INSERT INTO media_metadata (file_id, duration_ms, content_identifier, extractor, "
        "extractor_version, extracted_at) VALUES (?, ?, ?, 'test', '1', ?)",
        (file_id, duration_ms, content_id, NOW),
    )
    assert file_id is not None
    return file_id


def asset_of(conn: sqlite3.Connection, file_id: int) -> int:
    return int(
        conn.execute("SELECT asset_id FROM media_files WHERE id = ?", (file_id,)).fetchone()[0]
    )


def role_of(conn: sqlite3.Connection, file_id: int) -> str:
    return str(
        conn.execute("SELECT file_role FROM media_files WHERE id = ?", (file_id,)).fetchone()[0]
    )


def test_match_rules() -> None:
    assert is_live_match("A", "A", same_name=False, clip_ms=None)
    assert not is_live_match("A", "B", same_name=True, clip_ms=2000)  # ids decide when present
    assert is_live_match(None, "A", same_name=True, clip_ms=2900)
    assert not is_live_match(None, None, same_name=True, clip_ms=10_000)  # a real video
    assert not is_live_match(None, None, same_name=False, clip_ms=2000)


@pytest.mark.usefixtures("root")
def test_same_name_pair_from_either_side(conn: sqlite3.Connection) -> None:
    still = add(conn, "2025\\IMG_0001.HEIC", content_id=SAME_ID)
    clip = add(conn, "2025\\IMG_0001.MOV", content_id=SAME_ID, duration_ms=1800)
    photo_asset, video_asset = asset_of(conn, still), asset_of(conn, clip)

    assert pair_live_photo(conn, still, NOW)  # the still finds its clip
    assert asset_of(conn, clip) == photo_asset and role_of(conn, clip) == "companion"
    assert (
        conn.execute("SELECT 1 FROM media_assets WHERE id = ?", (video_asset,)).fetchone() is None
    )
    cover = conn.execute("SELECT cover_file_id FROM media_assets WHERE id = ?", (photo_asset,))
    assert cover.fetchone()[0] == still
    assert not pair_live_photo(conn, clip, NOW)  # already paired: nothing to do

    other_still = add(conn, "2025\\IMG_0002.JPG")
    other_clip = add(conn, "2025\\IMG_0002.MOV", duration_ms=2500)  # no ids: name + duration
    assert pair_live_photo(conn, other_clip, NOW)  # the clip finds its still
    assert asset_of(conn, other_clip) == asset_of(conn, other_still)


@pytest.mark.usefixtures("root")
def test_not_paired(conn: sqlite3.Connection) -> None:
    long_still = add(conn, "IMG_0003.HEIC")
    add(conn, "IMG_0003.MOV", duration_ms=10_000)  # a video that happens to share the name
    wrong_still = add(conn, "IMG_0004.HEIC", content_id="AAAA")
    add(conn, "IMG_0004.MOV", content_id="BBBB", duration_ms=2000)
    elsewhere = add(conn, "a\\IMG_0005.HEIC", content_id=SAME_ID)
    add(conn, "b\\CLIP_0005.MOV", content_id=SAME_ID, duration_ms=2000)  # other folder
    pending_still = add(conn, "IMG_0006.HEIC", content_id="CCCC")
    add(conn, "IMG_0006.MOV", content_id="CCCC", duration_ms=2000, state="pending")

    for still in (long_still, wrong_still, elsewhere, pending_still):
        assert not pair_live_photo(conn, still, NOW)
    assert (
        conn.execute("SELECT COUNT(*) FROM media_files WHERE file_role = 'companion'").fetchone()[0]
        == 0
    )


@pytest.mark.usefixtures("root")
def test_renamed_exports_pair_by_id_and_edited_version(conn: sqlite3.Connection) -> None:
    # Photos export: four names share one id; originals and edited ("E") versions pair up.
    original = add(conn, "SWDK1197.JPG", content_id=SAME_ID)
    edited = add(conn, "SWDKE1197.JPG", content_id=SAME_ID)
    original_clip = add(conn, "GYFF2926.MOV", content_id=SAME_ID, duration_ms=1933)

    # The edited still comes first, before its own clip is imported: it must wait.
    assert not pair_live_photo(conn, edited, NOW)
    edited_clip = add(conn, "GYFFE2926.MOV", content_id=SAME_ID, duration_ms=1933)
    assert pair_live_photo(conn, edited, NOW)
    assert pair_live_photo(conn, original_clip, NOW)

    assert asset_of(conn, edited_clip) == asset_of(conn, edited)
    assert asset_of(conn, original_clip) == asset_of(conn, original)


@pytest.mark.usefixtures("root")
def test_user_data_of_the_clip_is_merged(conn: sqlite3.Connection) -> None:
    still = add(conn, "IMG_0007.HEIC", content_id=SAME_ID)
    clip = add(conn, "IMG_0007.MOV", content_id=SAME_ID, duration_ms=2000)
    photo_asset, video_asset = asset_of(conn, still), asset_of(conn, clip)
    conn.execute(
        "UPDATE media_assets SET rating = 2, rating_source = 'import', notes = 'still' "
        "WHERE id = ?",
        (photo_asset,),
    )
    conn.execute(
        "UPDATE media_assets SET rating = 4, rating_source = 'user', is_favorite = 1, "
        "notes = 'clip' WHERE id = ?",
        (video_asset,),
    )
    conn.execute(
        "INSERT INTO tags (id, name, name_key, created_at) VALUES (1, '海边', '海边', ?)", (NOW,)
    )
    conn.execute(
        "INSERT INTO tags (id, name, name_key, created_at) VALUES (2, '视频', '视频', ?)", (NOW,)
    )
    conn.executemany(
        "INSERT INTO media_tags (asset_id, tag_id, source, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [(video_asset, 1, "user", None, NOW), (video_asset, 2, "ai", 0.9, NOW)],
    )
    conn.execute(
        "INSERT INTO media_locations (asset_id, latitude, longitude, source, updated_at) "
        "VALUES (?, 30.0, 120.0, 'exif', ?)",
        (video_asset, NOW),
    )

    assert pair_live_photo(conn, clip, NOW)

    merged = conn.execute("SELECT * FROM media_assets WHERE id = ?", (photo_asset,)).fetchone()
    assert (merged["rating"], merged["rating_source"], merged["is_favorite"]) == (4, "user", 1)
    assert merged["notes"] == "still\n\nclip"
    tags = conn.execute(
        "SELECT tag_id, source FROM media_tags WHERE asset_id = ?", (photo_asset,)
    ).fetchall()
    assert [tuple(t) for t in tags] == [(1, "user")]  # AI labels describe the old cover
    location = conn.execute(
        "SELECT latitude FROM media_locations WHERE asset_id = ?", (photo_asset,)
    ).fetchone()
    assert location[0] == 30.0


def test_pairing_does_not_scan_the_whole_root(conn: sqlite3.Connection, root: int) -> None:
    """Regression: an OR across two tables made every pairing scan all files of the root."""
    for index in range(2000):
        add(conn, f"DCIM/other/IMG_{index:04d}.JPG", content_id=f"id-{index}")
    still = add(conn, "DCIM/live/IMG_9000.HEIC", content_id=SAME_ID)
    clip = add(conn, "DCIM/live/IMG_9000.MOV", content_id=SAME_ID, duration_ms=2000)
    steps = 0

    def count() -> int:
        nonlocal steps
        steps += 1
        return 0

    conn.set_progress_handler(count, 100)  # called every 100 virtual machine steps
    assert pair_live_photo(conn, clip, NOW)
    conn.set_progress_handler(None, 0)
    assert asset_of(conn, clip) == asset_of(conn, still)
    assert steps < 50  # a scan of the 2000 other files takes thousands
