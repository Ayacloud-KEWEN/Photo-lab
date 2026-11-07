"""Copies of different quality (ADR-033): the same shot recompressed, converted or resized."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lumen.app import create_app
from lumen.core.config import Settings
from lumen.services import duplicates
from lumen.services.settings import get_settings
from tests.conftest import TOKEN
from tests.media_factory import make_jpeg
from tests.test_pipeline import wait_idle

pytestmark = pytest.mark.skipif(
    not (shutil.which("exiftool") and shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="exiftool and ffmpeg are required",
)

TAKEN = "2024:08:01 12:04:51"


def _save_copy(original: Path, path: Path, *, size: tuple[int, int] | None, quality: int) -> Path:
    """The original saved again (as a cloud service or an export would), keeping its EXIF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(original) as image:
        exif = image.info["exif"]
        picture = image.resize(size) if size else image.copy()
    picture.save(path, "JPEG", quality=quality, exif=exif)
    return path


@pytest.fixture
def library(tmp_path: Path) -> Iterator[tuple[TestClient, Any, dict[str, int]]]:
    root = tmp_path / "Photos"
    original = make_jpeg(root / "Originals" / "IMG_1000.JPG", size=(1200, 800), taken=TAKEN)
    _save_copy(original, root / "Google" / "IMG_1000.jpg", size=None, quality=40)
    _save_copy(original, root / "Small" / "IMG_1000 (1).jpg", size=(600, 400), quality=80)
    # Not copies: another camera, a crop, another shot in the same second.
    other = {"size": (1200, 800), "taken": TAKEN}
    make_jpeg(root / "Other" / "IMG_1000.JPG", color=(10, 90, 200), model="EOS R6", **other)
    make_jpeg(root / "Crop" / "IMG_1000.JPG", size=(800, 800), taken=TAKEN, color=(40, 200, 90))
    make_jpeg(root / "Originals" / "IMG_1001.JPG", color=(160, 30, 160), **other)
    app = create_app(Settings(data_dir=tmp_path / "data", log_to_file=False), TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        client.post("/api/v1/storage-roots", json={"path": str(root)})
        wait_idle(app.state.db)
        ids: dict[str, int] = {}
        for item in client.get("/api/v1/assets", params={"limit": 100}).json()["items"]:
            detail = client.get(f"/api/v1/assets/{item['id']}").json()
            folder = Path(detail["files"][0]["path"]).parent.name
            ids[f"{folder}/{item['file_name']}"] = item["id"]
        yield client, app, ids


def test_copies_of_one_shot_are_grouped_with_the_best_first(
    library: tuple[TestClient, Any, dict[str, int]],
) -> None:
    client, _, ids = library
    assert client.get("/api/v1/duplicates").json()["group_count"] == 0  # no identical files

    report = client.get("/api/v1/duplicates", params={"kind": "copies"}).json()
    assert report["group_count"] == 1
    [group] = report["groups"]
    best, google, small = (
        ids["Originals/IMG_1000.JPG"], ids["Google/IMG_1000.jpg"], ids["Small/IMG_1000 (1).jpg"]
    )  # fmt: skip
    assert group["keep_asset_id"] == best
    assert [entry["asset"]["id"] for entry in group["assets"]] == [best, google, small]
    sizes = [entry["files"][0]["size_bytes"] for entry in group["assets"]]
    assert group["redundant_bytes"] == report["redundant_bytes"] == sizes[1] + sizes[2]


def test_a_resized_copy_needs_a_similar_picture(
    library: tuple[TestClient, Any, dict[str, int]],
) -> None:
    client, app, ids = library
    best, small = ids["Originals/IMG_1000.JPG"], ids["Small/IMG_1000 (1).jpg"]
    with app.state.db.session() as conn:
        model = get_settings(conn).ai_model
        for asset_id, vector in ((best, [1.0, 0.0]), (small, [0.6, 0.8])):  # cosine 0.6
            conn.execute(
                "INSERT INTO embeddings (asset_id, model_id, fingerprint, dim, vector, "
                "created_at) VALUES (?, ?, 'f', 2, ?, '2026-11-07')",
                (asset_id, model, np.array(vector, dtype=np.float16).tobytes()),
            )
        conn.commit()
    duplicates._similarity_cache.clear()
    [group] = client.get("/api/v1/duplicates", params={"kind": "copies"}).json()["groups"]
    assert small not in [entry["asset"]["id"] for entry in group["assets"]]
    assert len(group["assets"]) == 2  # the same-size copy needs no picture check


def test_merging_copies_keeps_the_best_picture_and_the_user_data(
    library: tuple[TestClient, Any, dict[str, int]],
) -> None:
    client, app, ids = library
    best, google, small = (
        ids["Originals/IMG_1000.JPG"], ids["Google/IMG_1000.jpg"], ids["Small/IMG_1000 (1).jpg"]
    )  # fmt: skip
    client.patch(f"/api/v1/assets/{small}", json={"is_favorite": True, "rating": 5})
    album = client.post("/api/v1/collections", json={"name": "精选", "asset_ids": [google]}).json()

    # Copies are not identical files: merging them as such is refused.
    refused = client.post(
        "/api/v1/duplicates/merge", json={"groups": [{"asset_ids": [best, google]}]}
    )
    assert refused.status_code == 400
    outside = client.post(
        "/api/v1/duplicates/merge",
        json={"kind": "copies", "groups": [{"asset_ids": [best, ids["Other/IMG_1000.JPG"]]}]},
    )
    assert outside.status_code == 400

    task = client.post("/api/v1/duplicates/merge-all", params={"kind": "copies"})
    assert task.status_code == 202
    wait_idle(app.state.db)
    done = client.get(f"/api/v1/tasks/{task.json()['id']}").json()
    assert done["result"] == {"merged_groups": 1, "removed_assets": 2}

    kept = client.get(f"/api/v1/assets/{best}").json()
    assert (kept["rating"], kept["is_favorite"]) == (5, True)
    names = sorted(
        f"{Path(f['path']).parent.name}/{Path(f['path']).name}" for f in kept["files"]
    )
    assert names == ["Google/IMG_1000.jpg", "Originals/IMG_1000.JPG", "Small/IMG_1000 (1).jpg"]
    cover = next(f for f in kept["files"] if f["id"] == kept["cover_file_id"])
    assert Path(cover["path"]).parent.name == "Originals"
    detail = client.get(f"/api/v1/collections/{album['id']}").json()
    assert [item["asset"]["id"] for item in detail["items"]] == [best]
    for gone in (google, small):
        assert client.get(f"/api/v1/assets/{gone}").status_code == 404
    assert client.get("/api/v1/duplicates", params={"kind": "copies"}).json()["groups"] == []
    # The other camera, the crop and the other shot are still separate photos.
    for other in ("Other/IMG_1000.JPG", "Crop/IMG_1000.JPG", "Originals/IMG_1001.JPG"):
        assert client.get(f"/api/v1/assets/{ids[other]}").status_code == 200


def test_names_that_copies_share() -> None:
    assert duplicates._stem("IMG_1000 (1).JPG") == duplicates._stem("img_1000.heic") == "img_1000"
    assert duplicates._stem("IMG_1000-edited.jpg") == "img_1000-edited"  # an edit is not a copy
