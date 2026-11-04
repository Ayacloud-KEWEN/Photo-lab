"""Culling: quality scores, similar groups, pick/reject flags (ADR-025)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from lumen.core.config import Settings
from lumen.library.quality import QUALITY_TASK, measure, needs_scoring, score_assets
from lumen.media import thumbnails
from lumen.tasks import queue
from lumen.tasks.runner import TaskContext
from tests.test_develop import NOW, add_photo

MODEL = "siglip2-so400m-patch14-384"


def scene(seed: int = 0) -> np.ndarray:
    """A detailed 8-bit grayscale "photo": shapes and text-like edges on a gradient."""
    rng = np.random.default_rng(seed)
    image = np.tile(np.linspace(60, 190, 2000, dtype=np.float32), (1500, 1))
    for _ in range(60):
        x, y = (int(v) for v in rng.integers(0, 1900, 2))
        cv2.rectangle(image, (x, y), (x + 90, y + 60), float(rng.integers(0, 255)), 2)
    return image.astype(np.uint8)


def test_measure_tells_sharp_from_blurry_and_flat() -> None:
    sharp = measure(scene())
    blurry = measure(cv2.GaussianBlur(scene(), (0, 0), 3))
    assert sharp.flags == () and sharp.sharpness > 0.5
    assert blurry.flags == ("blurry",) and blurry.sharpness < sharp.sharpness
    assert blurry.score < sharp.score
    # A plain sky has too few edges to judge: neutral, never called blurry.
    flat = measure(np.full((1500, 2000), 150, np.uint8))
    assert flat.flags == () and flat.sharpness == pytest.approx(0.6)
    # Small pictures are soft because of their size: never called blurry.
    small = cv2.resize(cv2.GaussianBlur(scene(), (0, 0), 3), (1000, 750))
    assert "blurry" not in measure(small).flags


def test_measure_flags_exposure_but_not_for_screenshots() -> None:
    white = np.full((1500, 2000), 255, np.uint8)
    white[600:800, 200:1800] = 0  # a little detail
    assert "overexposed" in measure(white).flags
    assert "overexposed" not in measure(white, judge_exposure=False).flags
    dark = (scene() // 12).astype(np.uint8)
    dark[:1000] = 0
    assert "underexposed" in measure(dark).flags


def write_preview(settings: Settings, conn: sqlite3.Connection, asset_id: int, image: np.ndarray):
    fingerprint = conn.execute(
        "SELECT c.fingerprint FROM media_assets a JOIN media_files c ON c.id = a.cover_file_id "
        "WHERE a.id = ?",
        (asset_id,),
    ).fetchone()[0]
    preview = thumbnails.rendition_paths(settings.cache_dir, fingerprint).preview
    preview.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(preview), image)


def embed(conn: sqlite3.Connection, asset_id: int, vector: np.ndarray, taken: str) -> None:
    unit = (vector / np.linalg.norm(vector)).astype(np.float16)
    conn.execute(
        "INSERT INTO embeddings (asset_id, model_id, fingerprint, dim, vector, created_at) "
        "VALUES (?, ?, 'x', ?, ?, ?)",
        (asset_id, MODEL, unit.size, unit.tobytes(), NOW),
    )
    conn.execute("UPDATE media_assets SET capture_time = ? WHERE id = ?", (taken, asset_id))


@pytest.fixture
def photos(conn: sqlite3.Connection, settings: Settings, tmp_path: Path) -> list[int]:
    """Five photos: 0-2 a burst (0 blurry), 3 the same scene an hour later, 4 another scene."""
    root = tmp_path / "Photos"
    root.mkdir()
    conn.execute(
        "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, updated_at) "
        "VALUES (1, ?, ?, 'Photos', ?, ?)",
        (str(root), str(root).lower(), NOW, NOW),
    )
    ids = [add_photo(conn, root, f"IMG_000{i}.JPG") for i in range(5)]
    rng = np.random.default_rng(1)
    base, other = rng.normal(size=64), rng.normal(size=64)
    times = ["2025-05-01T10:00:00", "2025-05-01T10:00:02", "2025-05-01T10:03:00",
             "2025-05-01T11:30:00", "2025-05-01T10:01:00"]  # fmt: skip
    for index, asset_id in enumerate(ids):
        vector = other if index == 4 else base + rng.normal(scale=0.05, size=64)
        embed(conn, asset_id, vector, times[index])
        image = cv2.GaussianBlur(scene(index), (0, 0), 3) if index == 0 else scene(index)
        write_preview(settings, conn, asset_id, image)
    return ids


def run_scoring(conn: sqlite3.Connection, settings: Settings) -> object:
    task_id = queue.enqueue(conn, QUALITY_TASK, unique=False)
    assert queue.claim_next(conn) is not None
    ctx = TaskContext(
        conn=conn, settings=settings, task_id=task_id, kind=QUALITY_TASK, storage_root_id=None,
        payload={}, stop_event=threading.Event(), enqueue=lambda *a, **k: 0,
    )  # fmt: skip
    return score_assets(ctx)


def test_similar_groups_recommend_a_photo_and_follow_the_flags(
    client: TestClient, conn: sqlite3.Connection, settings: Settings, photos: list[int]
) -> None:
    assert needs_scoring(conn)
    assert run_scoring(conn, settings) == {"scored": 5}
    assert not needs_scoring(conn)
    assert client.get(f"/api/v1/assets/{photos[0]}").json()["quality"]["flags"] == ["blurry"]

    similar = client.get("/api/v1/cull/similar").json()
    assert similar["available"] is True
    [group] = similar["groups"]  # the photo an hour later and the other scene are apart
    assert [item["asset"]["id"] for item in group["items"]] == photos[:3]
    assert group["recommended_id"] != photos[0]  # not the blurry one
    # The user's own signals come first.
    client.patch(f"/api/v1/assets/{photos[0]}", json={"is_favorite": True})
    [group] = client.get("/api/v1/cull/similar").json()["groups"]
    assert group["recommended_id"] == photos[0]
    wide = client.get("/api/v1/cull/similar", params={"window_minutes": 120}).json()
    assert [len(g["items"]) for g in wide["groups"]] == [4]

    suspects = client.get("/api/v1/cull/suspects").json()
    assert [item["asset"]["id"] for item in suspects["items"]] == [photos[0]]
    # A white document is "overexposed" by nature: not a suspect once labelled as one.
    conn.execute("UPDATE media_quality SET flags = 'overexposed' WHERE asset_id = ?", (photos[4],))
    assert len(client.get("/api/v1/cull/suspects").json()["items"]) == 2
    client.post("/api/v1/assets/batch", json={"asset_ids": [photos[4]], "add_tags": ["文档"]})
    assert len(client.get("/api/v1/cull/suspects").json()["items"]) == 1

    # Keep the recommended photo, reject the others: the group is done.
    client.post(
        "/api/v1/assets/batch", json={"asset_ids": photos[1:3], "cull_flag": "reject"}
    )
    client.patch(f"/api/v1/assets/{photos[0]}", json={"cull_flag": "pick"})
    assert client.get("/api/v1/cull/similar").json()["groups"] == []
    done = client.get("/api/v1/cull/similar", params={"pending_only": False}).json()
    assert (done["group_count"], done["pending_count"]) == (1, 0)
    assert done["groups"][0]["recommended_id"] == photos[0]
    assert client.get("/api/v1/cull/suspects").json()["items"] == []  # it was picked


def test_rejected_photos_are_hidden_unless_asked_for(
    client: TestClient, conn: sqlite3.Connection, photos: list[int]
) -> None:
    def ids(**params: object) -> list[int]:
        items = client.get("/api/v1/assets", params={"limit": 50, **params}).json()["items"]
        return sorted(item["id"] for item in items)

    client.post("/api/v1/assets/batch", json={"asset_ids": photos[:2], "cull_flag": "reject"})
    assert ids() == photos[2:]
    assert ids(rejected="show") == photos
    assert ids(rejected="only") == photos[:2]
    assert client.get("/api/v1/assets/facets").json()["total"] == 3  # counts match the library
    summary = client.get("/api/v1/assets", params={"rejected": "only"}).json()["items"][0]
    assert summary["cull_flag"] == "reject"

    files = client.get("/api/v1/cull/rejected-files").json()
    assert files["asset_count"] == 2
    assert sorted(Path(p).name for p in files["paths"]) == ["IMG_0000.JPG", "IMG_0001.JPG"]
    assert client.post("/api/v1/files/999/reveal").status_code == 404
    client.patch(f"/api/v1/assets/{photos[0]}", json={"cull_flag": "none"})
    assert ids() == [photos[0], *photos[2:]]


def test_similar_groups_need_the_local_ai(client: TestClient) -> None:
    assert client.get("/api/v1/cull/similar").json() == {
        "available": False, "groups": [], "group_count": 0, "pending_count": 0,
    }  # fmt: skip


def test_ai_warm_up_is_a_no_op_without_the_local_ai(client: TestClient) -> None:
    assert client.post("/api/v1/ai/warm-up").status_code == 204


def test_open_map_and_reveal_file(
    client: TestClient, conn: sqlite3.Connection, photos: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from lumen.api.v1 import assets as assets_api
    from lumen.api.v1 import cull as cull_api

    opened: list[str] = []
    monkeypatch.setattr(assets_api, "open_in_browser", opened.append)
    assert client.post(f"/api/v1/assets/{photos[0]}/open-map").status_code == 404  # no GPS
    conn.execute(
        "INSERT INTO media_locations (asset_id, latitude, longitude, source, updated_at) "
        "VALUES (?, 48.8584, 2.2945, 'exif', ?)",
        (photos[0], NOW),
    )
    assert client.post(f"/api/v1/assets/{photos[0]}/open-map").status_code == 204
    assert opened == ["https://www.google.com/maps/search/?api=1&query=48.858400,2.294500"]

    revealed: list[Path] = []
    monkeypatch.setattr(cull_api, "reveal_in_explorer", revealed.append)
    file_id = client.get(f"/api/v1/assets/{photos[0]}").json()["files"][0]["id"]
    assert client.post(f"/api/v1/files/{file_id}/reveal").status_code == 204
    assert [p.name for p in revealed] == ["IMG_0000.JPG"]
