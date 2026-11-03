"""Phase 3 API: filtering, search, timeline, map, originals, edits, tags, settings."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lumen.app import create_app
from lumen.core.config import Settings
from lumen.db.connection import Database
from lumen.db.migrator import load_migrations, migrate
from tests.conftest import TOKEN
from tests.media_factory import make_jpeg, make_sample_library
from tests.test_pipeline import wait_idle

pytestmark = pytest.mark.skipif(
    not (shutil.which("exiftool") and shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="exiftool and ffmpeg are required",
)


@pytest.fixture(scope="module")
def library_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """One ingested sample library shared by the read-only tests of this module."""
    base = tmp_path_factory.mktemp("library")
    root = base / "Photos"
    make_sample_library(root)
    make_jpeg(root / "2024" / "05" / "IMG_0003.JPG", taken="2024:05:03 07:00:00")
    (root / "2024" / "05" / "IMG_0003.CR2").write_bytes(b"II*\x00 fake raw")
    app = create_app(Settings(data_dir=base / "data", log_to_file=False), TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        client.post("/api/v1/storage-roots", json={"path": str(root)})
        wait_idle(app.state.db)
        yield client


def names(client: TestClient, **params: Any) -> list[str]:
    page = client.get("/api/v1/assets", params={"limit": 500, **params})
    assert page.status_code == 200, page.text
    return [item["file_name"] for item in page.json()["items"]]


def asset_id(client: TestClient, file_name: str) -> int:
    items = client.get("/api/v1/assets", params={"limit": 500}).json()["items"]
    return next(item["id"] for item in items if item["file_name"] == file_name)


# ------------------------------------------------------------------ read-only


def test_xmp_rating_and_keywords_are_imported(library_client: TestClient) -> None:
    detail = library_client.get(f"/api/v1/assets/{asset_id(library_client, 'IMG_0002.jpg')}")
    body = detail.json()
    assert (body["rating"], body["rating_source"]) == (4, "import")
    assert {(t["name"], t["source"]) for t in body["tags"]} == {
        ("旅行", "import"),
        ("Landscape", "import"),
    }
    facets = library_client.get("/api/v1/assets/facets").json()
    assert {t["name"]: t["asset_count"] for t in facets["tags"]} == {"Landscape": 1, "旅行": 1}


def test_search(library_client: TestClient) -> None:
    assert names(library_client, q="西湖") == ["西湖 日落.jpg"]  # 2 chars, Chinese
    assert names(library_client, q="旅行") == ["IMG_0002.jpg", "西湖 日落.jpg"]  # tag + folder
    assert names(library_client, q="landscape") == ["IMG_0002.jpg"]  # tag, case-insensitive
    assert names(library_client, q="iphone 15") == ["IMG_5001.HEIC"]  # every term must match
    assert names(library_client, q="100%_") == []  # LIKE wildcards are literal
    assert len(names(library_client, q="EOS R5")) == 5


def test_filters(library_client: TestClient) -> None:
    assert sorted(names(library_client, media_type="video")) == ["clip.mp4", "clip2.mov"]
    assert names(library_client, min_rating=4) == ["IMG_0002.jpg"]
    assert names(library_client, camera="iPhone 15 Pro") == ["IMG_5001.HEIC"]
    assert names(library_client, format="CR2") == ["IMG_0003.JPG"]  # RAW+JPEG asset
    assert names(library_client, has_location=True) == ["IMG_0001.JPG"]
    assert names(library_client, date_from="2024-05-01", date_to="2024-05-03") == [
        "IMG_0002_copy.jpg",
        "IMG_0002.jpg",
        "IMG_0001.JPG",
    ]
    tag = next(t for t in library_client.get("/api/v1/tags").json() if t["name"] == "Landscape")
    assert names(library_client, tag_id=tag["id"]) == ["IMG_0002.jpg"]
    assert library_client.get("/api/v1/assets", params={"date_from": "May 1"}).status_code == 422


def test_sorting_and_cursors(library_client: TestClient) -> None:
    newest_first = names(library_client)
    assert names(library_client, sort="capture_asc") == list(reversed(newest_first))
    added = names(library_client, sort="added_desc")
    assert sorted(added) == sorted(newest_first)

    page = library_client.get("/api/v1/assets", params={"limit": 2}).json()
    mismatch = library_client.get(
        "/api/v1/assets", params={"cursor": page["next_cursor"], "sort": "added_desc"}
    )
    assert mismatch.status_code == 400

    ids = library_client.get("/api/v1/assets/ids").json()["ids"]
    full = library_client.get("/api/v1/assets", params={"limit": 500}).json()["items"]
    assert ids == [item["id"] for item in full]


def test_facets(library_client: TestClient) -> None:
    facets = library_client.get("/api/v1/assets/facets").json()
    assert (facets["total"], facets["photos"], facets["videos"]) == (9, 7, 2)
    assert facets["with_location"] == 1
    assert {"value": "EOS R5", "count": 5} in facets["cameras"]
    assert {"value": "CR2", "count": 1} in facets["formats"]


def test_timeline(library_client: TestClient) -> None:
    months = library_client.get("/api/v1/timeline").json()
    assert months["granularity"] == "month"
    periods = [b["period"] for b in months["buckets"]]
    assert periods == sorted(periods, reverse=True)
    assert sum(b["count"] for b in months["buckets"]) == 9
    days = library_client.get(
        "/api/v1/timeline",
        params={"granularity": "day", "date_from": "2024-05", "date_to": "2024-06"},
    ).json()
    assert days["buckets"] == [
        {"period": "2024-05-03", "count": 1},
        {"period": "2024-05-02", "count": 2},
        {"period": "2024-05-01", "count": 1},
    ]


def test_map_points(library_client: TestClient) -> None:
    points = library_client.get("/api/v1/map/points").json()["points"]
    assert len(points) == 1
    assert points[0]["lat"] == pytest.approx(31.2304, abs=1e-3)
    assert points[0]["v"]


def test_original_supports_ranges_and_query_token(library_client: TestClient) -> None:
    video = asset_id(library_client, "clip.mp4")
    url = f"/api/v1/assets/{video}/original"
    full = library_client.get(url)
    assert full.status_code == 200
    assert full.headers["content-type"] == "video/mp4"
    assert full.headers["accept-ranges"] == "bytes"

    partial = library_client.get(url, headers={"Range": "bytes=0-99"})
    assert partial.status_code == 206
    assert len(partial.content) == 100

    anonymous = TestClient(library_client.app)
    assert anonymous.get(url).status_code == 401
    assert anonymous.get(url, params={"token": TOKEN}).status_code == 200


# ------------------------------------------------------------------ edits


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    root = tmp_path / "Photos"
    make_sample_library(root)
    app = create_app(Settings(data_dir=tmp_path / "data", log_to_file=False), TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as test_client:
        test_client.post("/api/v1/storage-roots", json={"path": str(root)})
        wait_idle(app.state.db)
        yield test_client


def test_edit_asset(client: TestClient) -> None:
    target = asset_id(client, "IMG_0002.jpg")
    updated = client.patch(
        f"/api/v1/assets/{target}", json={"rating": 2, "is_favorite": True, "notes": "蓝色的海"}
    ).json()
    assert (updated["rating"], updated["rating_source"], updated["is_favorite"]) == (
        2,
        "user",
        True,
    )
    assert names(client, q="蓝色") == ["IMG_0002.jpg"]  # notes are searchable
    assert names(client, favorite=True) == ["IMG_0002.jpg"]

    cleared = client.patch(f"/api/v1/assets/{target}", json={"notes": ""}).json()
    assert cleared["notes"] is None
    assert names(client, q="蓝色") == []
    assert client.patch(f"/api/v1/assets/{target}", json={"rating": 9}).status_code == 422
    assert client.patch("/api/v1/assets/99999", json={"rating": 1}).status_code == 404


def test_user_rating_survives_reimport(client: TestClient) -> None:
    target = asset_id(client, "IMG_0002.jpg")
    client.patch(f"/api/v1/assets/{target}", json={"rating": 1})

    # Force metadata to be read again (as after an upgrade), then process.
    db: Database = client.app.state.db  # type: ignore[attr-defined]
    with db.session() as conn:
        conn.execute("UPDATE media_files SET ingest_state = 'pending'")
    root_id = client.get("/api/v1/storage-roots").json()["items"][0]["id"]
    client.post(f"/api/v1/storage-roots/{root_id}/scan")
    wait_idle(db)

    detail = client.get(f"/api/v1/assets/{target}").json()
    assert (detail["rating"], detail["rating_source"]) == (1, "user")


def test_batch_update_and_tags(client: TestClient) -> None:
    ids = client.get("/api/v1/assets/ids", params={"media_type": "photo"}).json()["ids"]
    result = client.post(
        "/api/v1/assets/batch",
        json={
            "asset_ids": [*ids, 999_999],
            "is_favorite": True,
            "add_tags": ["  Best  of ", "家人"],
        },
    )
    assert result.json() == {"updated": len(ids)}
    tags = {t["name"]: t for t in client.get("/api/v1/tags").json()}
    assert tags["Best of"]["asset_count"] == len(ids)  # whitespace normalized
    assert len(names(client, q="家人")) == len(ids)
    assert len(names(client, favorite=True)) == len(ids)

    # Tag names are unique regardless of case.
    assert client.post("/api/v1/tags", json={"name": "best OF"}).status_code == 409
    created = client.post("/api/v1/tags", json={"name": "Street"})
    assert created.status_code == 201 and created.json()["asset_count"] == 0

    best = tags["Best of"]["id"]
    renamed = client.patch(f"/api/v1/tags/{best}", json={"name": "精选"}).json()
    assert renamed["name"] == "精选"
    assert len(names(client, q="精选")) == len(ids)
    assert client.patch(f"/api/v1/tags/{best}", json={"name": "street"}).status_code == 409

    client.post("/api/v1/assets/batch", json={"asset_ids": ids[:2], "remove_tag_ids": [best]})
    assert len(names(client, tag_id=best)) == len(ids) - 2

    assert client.delete(f"/api/v1/tags/{best}").status_code == 204
    assert names(client, q="精选") == []
    assert client.delete(f"/api/v1/tags/{best}").status_code == 404


def test_settings(client: TestClient) -> None:
    assert client.get("/api/v1/settings").json() == {"map_online_tiles": False}
    assert client.patch("/api/v1/settings", json={"map_online_tiles": True}).json() == {
        "map_online_tiles": True
    }
    assert client.patch("/api/v1/settings", json={"map_online_tiles": None}).json() == {
        "map_online_tiles": True
    }
    assert client.patch("/api/v1/settings", json={"unknown": 1}).status_code == 422


# ------------------------------------------------------------------ upgrade


def test_migration_0003_requeues_existing_library(tmp_path: Path) -> None:
    db = Database(tmp_path / "lumen.db")
    migrate(db, migrations=load_migrations()[:2])
    with db.session() as conn:
        now = "2026-01-01T00:00:00.000Z"
        conn.execute(
            "INSERT INTO storage_roots (path, path_key, display_name, created_at, updated_at) "
            "VALUES ('C:\\x', 'c:\\x', 'x', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO media_assets (uuid, media_type, notes, created_at, updated_at) "
            "VALUES ('u', 'photo', '海边', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO media_files (asset_id, storage_root_id, relative_path, relative_path_key, "
            "file_name, extension, size_bytes, modified_at, ingest_state, created_at, updated_at) "
            "VALUES (1, 1, 'a.jpg', 'a.jpg', 'a.jpg', 'jpg', 1, ?, 'done', ?, ?)",
            (now, now, now),
        )

    migrate(db)

    with db.session() as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT ingest_state FROM media_files").fetchone()[0] == "pending"
        task = conn.execute("SELECT kind, status, storage_root_id FROM tasks").fetchone()
        assert tuple(task) == ("ingest_storage_root", "pending", 1)
        # Existing assets were indexed for search by the migration.
        rows = conn.execute("SELECT rowid FROM asset_search WHERE body LIKE '%海边%'").fetchall()
        assert [row[0] for row in rows] == [1]
