"""Duplicate files: report, merge into one photo, and keep showing it when a copy goes."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lumen.app import create_app
from lumen.core.config import Settings
from tests.conftest import TOKEN
from tests.media_factory import make_sample_library
from tests.test_pipeline import wait_idle

pytestmark = pytest.mark.skipif(
    not (shutil.which("exiftool") and shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="exiftool and ffmpeg are required",
)


@pytest.fixture
def library(tmp_path: Path) -> Iterator[tuple[TestClient, Any, Path, dict[str, int]]]:
    """The ingested sample library: IMG_0002.jpg (with an XMP rating) and a copy of it."""
    root = tmp_path / "Photos"
    make_sample_library(root)
    app = create_app(Settings(data_dir=tmp_path / "data", log_to_file=False), TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        made = client.post("/api/v1/storage-roots", json={"path": str(root)}).json()
        wait_idle(app.state.db)
        items = client.get("/api/v1/assets", params={"limit": 100}).json()["items"]
        ids = {item["file_name"]: item["id"] for item in items}
        yield client, (app, made["id"]), root, ids


def test_merge_folds_copies_into_one_photo_and_keeps_user_data(
    library: tuple[TestClient, Any, Path, dict[str, int]],
) -> None:
    client, (app, root_id), root, ids = library
    original, copy = ids["IMG_0002.jpg"], ids["IMG_0002_copy.jpg"]

    report = client.get("/api/v1/duplicates").json()
    assert report["group_count"] == 1
    [group] = report["groups"]
    # The copy with the user's data (the imported rating and keywords) is kept.
    assert group["keep_asset_id"] == original
    assert [a["asset"]["id"] for a in group["assets"]] == [original, copy]
    assert group["assets"][0]["tag_count"] == 2
    copy_size = (root / "backup" / "IMG_0002_copy.jpg").stat().st_size
    assert group["redundant_bytes"] == report["redundant_bytes"] == copy_size

    # What the user sets on the other copy is carried over.
    client.patch(f"/api/v1/assets/{copy}", json={"is_favorite": True, "notes": "备份里的"})
    client.post("/api/v1/assets/batch", json={"asset_ids": [copy], "add_tags": ["海边"]})
    album = client.post("/api/v1/collections", json={"name": "精选", "asset_ids": [copy]}).json()

    bad = client.post(
        "/api/v1/duplicates/merge", json={"groups": [{"asset_ids": [original, ids["clip.mp4"]]}]}
    )
    assert bad.status_code == 400
    merged = client.post(
        "/api/v1/duplicates/merge", json={"groups": [{"asset_ids": [copy, original]}]}
    )
    assert merged.json() == {"merged_groups": 1, "removed_assets": 1}
    assert client.get("/api/v1/duplicates").json()["groups"] == []
    assert client.get(f"/api/v1/assets/{copy}").status_code == 404

    kept = client.get(f"/api/v1/assets/{original}").json()
    assert (kept["rating"], kept["is_favorite"], kept["notes"]) == (4, True, "备份里的")
    assert {t["name"] for t in kept["tags"]} >= {"旅行", "Landscape", "海边"}
    paths = sorted(Path(f["path"]).name for f in kept["files"] if f["role"] == "primary")
    assert paths == ["IMG_0002.jpg", "IMG_0002_copy.jpg"]
    detail = client.get(f"/api/v1/collections/{album['id']}").json()
    assert [item["asset"]["id"] for item in detail["items"]] == [original]
    assert len(client.get("/api/v1/assets", params={"q": "海边"}).json()["items"]) == 1

    # The user deletes the first copy on disk: the photo stays, shown from the other copy.
    (root / "2024" / "05" / "IMG_0002.jpg").unlink()
    client.post(f"/api/v1/storage-roots/{root_id}/scan")
    wait_idle(app.state.db)
    after = client.get(f"/api/v1/assets/{original}").json()
    cover = next(f for f in after["files"] if f["id"] == after["cover_file_id"])
    assert (Path(cover["path"]).name, cover["status"]) == ("IMG_0002_copy.jpg", "present")
    assert original in [i["id"] for i in client.get("/api/v1/assets").json()["items"]]
    thumb = client.get(f"/api/v1/assets/{original}/thumbnail")
    assert thumb.status_code == 200


def test_merge_all_runs_as_a_background_task(
    library: tuple[TestClient, Any, Path, dict[str, int]],
) -> None:
    client, (app, _), _, ids = library
    original, copy = ids["IMG_0002.jpg"], ids["IMG_0002_copy.jpg"]
    task = client.post("/api/v1/duplicates/merge-all")
    assert task.status_code == 202 and task.json()["kind"] == "merge_duplicates"
    wait_idle(app.state.db)
    done = client.get(f"/api/v1/tasks/{task.json()['id']}").json()
    assert done["status"] == "succeeded"
    assert done["result"] == {"merged_groups": 1, "removed_assets": 1}
    assert client.get("/api/v1/duplicates").json()["group_count"] == 0
    assert client.get(f"/api/v1/assets/{copy}").status_code == 404
    assert client.get(f"/api/v1/assets/{original}").json()["rating"] == 4
