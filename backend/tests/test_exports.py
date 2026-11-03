"""Exporting developed photos (new JPEG files) and applying settings to many photos."""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lumen.core.config import Settings
from lumen.db.connection import Database
from lumen.develop.exporter import ExportOptions, decode_edge, export_photo, reserve_path
from lumen.develop.recipe import Crop, EditRecipe
from lumen.library.exports import EXPORT_TASK, export_assets
from lumen.media.formats import format_for
from lumen.media.metadata import ExifToolSession
from lumen.services import develop
from lumen.tasks import queue
from lumen.tasks.runner import TaskContext
from tests.media_factory import make_jpeg
from tests.test_develop import NOW, add_photo

JPEG = format_for("jpg")
assert JPEG is not None
needs_exiftool = pytest.mark.skipif(not shutil.which("exiftool"), reason="exiftool is required")


def read_tags(path: Path) -> dict[str, object]:
    exiftool = shutil.which("exiftool")
    assert exiftool
    import exiftool as pyexiftool

    with pyexiftool.ExifToolHelper(executable=exiftool, common_args=["-G", "-n"]) as helper:
        [record] = helper.get_metadata([str(path)])
    return dict(record)


# --- Exporter -------------------------------------------------------------------------------


def test_reserved_names_never_replace_existing_files(tmp_path: Path) -> None:
    (tmp_path / "IMG_0001.jpg").write_bytes(b"mine")
    first = reserve_path(tmp_path, "IMG_0001")
    second = reserve_path(tmp_path, "IMG_0001")
    assert (first.name, second.name) == ("IMG_0001 (2).jpg", "IMG_0001 (3).jpg")
    assert (tmp_path / "IMG_0001.jpg").read_bytes() == b"mine"


def test_decode_edge_keeps_enough_pixels_after_cropping() -> None:
    assert decode_edge(EditRecipe(), None) is None
    assert decode_edge(EditRecipe(), 2048) == 2048
    half = EditRecipe(crop=Crop(x=0, y=0, width=0.5, height=0.8))
    assert decode_edge(half, 2048) == 4096
    assert decode_edge(EditRecipe(straighten=3), 2048) is None


def test_export_photo_resizes_and_cleans_up(tmp_path: Path) -> None:
    source = make_jpeg(tmp_path / "in" / "IMG_0001.JPG", size=(1200, 800))
    out = tmp_path / "out"
    out.mkdir()
    recipe = EditRecipe(rotate=1, exposure=-1)
    path = export_photo(source, JPEG, recipe, out, ExportOptions(long_edge=600), None)
    assert path.name == "IMG_0001.jpg"
    with Image.open(path) as image:
        assert image.size == (400, 600)  # turned a quarter, then fitted
    full = export_photo(source, JPEG, EditRecipe(), out, ExportOptions(), None)
    with Image.open(full) as image:
        assert image.size == (1200, 800)
    assert sorted(p.name for p in out.iterdir()) == ["IMG_0001 (2).jpg", "IMG_0001.jpg"]

    broken = tmp_path / "in" / "broken.jpg"
    broken.write_bytes(b"not a jpeg")
    with pytest.raises(Exception):  # noqa: B017 - any decode error
        export_photo(broken, JPEG, EditRecipe(), out, ExportOptions(), None)
    assert len(list(out.iterdir())) == 2  # no placeholder or temporary file left behind


@needs_exiftool
def test_export_metadata_and_location(tmp_path: Path) -> None:
    source = make_jpeg(tmp_path / "IMG_0002.JPG", size=(900, 600), orientation=6, gps=(48.85, 2.35))
    out = tmp_path / "out"
    out.mkdir()
    exiftool = shutil.which("exiftool")
    assert exiftool
    with ExifToolSession(exiftool) as session:
        private = export_photo(source, JPEG, EditRecipe(), out, ExportOptions(), session)
        located = export_photo(
            source, JPEG, EditRecipe(), out, ExportOptions(include_location=True), session
        )
        bare = export_photo(
            source, JPEG, EditRecipe(), out, ExportOptions(include_metadata=False), session
        )

    tags = read_tags(private)
    assert tags["EXIF:Make"] == "Canon"
    assert tags["EXIF:Orientation"] == 1  # the pixels are already upright
    assert (tags["File:ImageWidth"], tags["File:ImageHeight"]) == (600, 900)
    assert (tags["EXIF:ExifImageWidth"], tags["EXIF:ExifImageHeight"]) == (600, 900)
    assert not any("GPS" in key for key in tags)
    assert "EXIF:GPSLatitude" in read_tags(located)
    assert "EXIF:Make" not in read_tags(bare)


# --- Export task and API --------------------------------------------------------------------


@pytest.fixture
def library(conn: sqlite3.Connection, tmp_path: Path) -> tuple[Path, int, int, int]:
    """A storage root with two photos and a video; returns (root, photo, photo, video)."""
    root = tmp_path / "Photos"
    root.mkdir()
    conn.execute(
        "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, updated_at) "
        "VALUES (1, ?, ?, 'Photos', ?, ?)",
        (str(root), str(root).lower(), NOW, NOW),
    )
    first = add_photo(conn, root, "IMG_0001.JPG")
    second = add_photo(conn, root, "IMG_0002.JPG")
    video = add_photo(conn, root, "clip.jpg", media_type="video")
    return root, first, second, video


def run_task(conn: sqlite3.Connection, settings: Settings, payload: dict[str, object]) -> object:
    task_id = queue.enqueue(conn, EXPORT_TASK, payload=payload, unique=False)
    task = queue.claim_next(conn)
    assert task is not None and task["id"] == task_id
    ctx = TaskContext(
        conn=conn, settings=settings, task_id=task_id, kind=EXPORT_TASK, storage_root_id=None,
        payload=payload, stop_event=threading.Event(), enqueue=lambda *a, **k: 0,
    )  # fmt: skip
    return export_assets(ctx)


def test_export_task_exports_photos_with_their_edits(
    conn: sqlite3.Connection,
    settings: Settings,
    library: tuple[Path, int, int, int],
    tmp_path: Path,
) -> None:
    root, first, second, video = library
    develop.save_edit(conn, first, EditRecipe(crop=Crop(x=0, y=0, width=0.5, height=0.5)))
    (root / "IMG_0002.JPG").unlink()  # its original went missing
    conn.execute("UPDATE media_files SET status = 'missing' WHERE asset_id = ?", (second,))
    out = tmp_path / "Export"
    out.mkdir()

    result = run_task(
        conn, settings, {"asset_ids": [first, second, video], "destination": str(out)}
    )
    # The "video" (any file ffmpeg can copy) is exported too; the missing photo is skipped.
    assert result == {"destination": str(out), "exported": 2, "skipped": 1, "failed": []}
    with Image.open(out / "IMG_0001.jpg") as image:
        assert image.size == (400, 300)  # the edit's crop
    assert (root / "IMG_0001.JPG").exists()  # the original is untouched


def test_export_task_reports_failures_and_resumes(
    conn: sqlite3.Connection,
    settings: Settings,
    library: tuple[Path, int, int, int],
    tmp_path: Path,
) -> None:
    root, first, second, _ = library
    (root / "IMG_0002.JPG").write_bytes(b"corrupt")
    out = tmp_path / "Export"
    out.mkdir()
    result = run_task(conn, settings, {"asset_ids": [first, second], "destination": str(out)})
    assert isinstance(result, dict)
    assert result["exported"] == 1
    assert [f["file_name"] for f in result["failed"]] == ["IMG_0002.JPG"]

    # A task interrupted after its first photo continues with the second.
    payload: dict[str, object] = {"asset_ids": [first, first], "destination": str(out)}
    task_id = queue.enqueue(conn, EXPORT_TASK, payload=payload, unique=False)
    conn.execute("UPDATE tasks SET progress_current = 1 WHERE id = ?", (task_id,))
    queue.claim_next(conn)
    ctx = TaskContext(
        conn=conn, settings=settings, task_id=task_id, kind=EXPORT_TASK, storage_root_id=None,
        payload=payload, stop_event=threading.Event(), enqueue=lambda *a, **k: 0,
    )  # fmt: skip
    export_assets(ctx)
    assert sorted(p.name for p in out.iterdir()) == ["IMG_0001 (2).jpg", "IMG_0001.jpg"]


def test_export_api(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    out = tmp_path / "Export"
    out.mkdir()
    bad = client.post("/api/v1/exports", json={"asset_ids": [1], "destination": "relative"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_path"
    missing = client.post(
        "/api/v1/exports", json={"asset_ids": [1], "destination": str(tmp_path / "nope")}
    )
    assert missing.status_code == 422

    started = client.post(
        "/api/v1/exports",
        json={"asset_ids": [1, 2], "destination": str(out), "long_edge": 2048, "quality": 85},
    )
    assert started.status_code == 202
    status = started.json()
    assert status["task"]["kind"] == EXPORT_TASK and status["result"] is None
    # Two exports are two tasks (they are not merged like rescans).
    again = client.post("/api/v1/exports", json={"asset_ids": [3], "destination": str(out)})
    assert again.json()["task"]["id"] != status["task"]["id"]

    task_id = status["task"]["id"]
    with Database(settings.database_path).session() as conn:
        payload = json.loads(queue.get(conn, task_id)["payload"])
        assert payload["long_edge"] == 2048 and payload["include_location"] is False
        conn.execute("UPDATE tasks SET status = 'running' WHERE id = ?", (task_id,))
        result = {"destination": str(out), "exported": 2, "skipped": 0, "failed": []}
        queue.mark_succeeded(conn, task_id, result)
    done = client.get(f"/api/v1/exports/{task_id}").json()
    assert done["task"]["status"] == "succeeded" and done["result"] == result
    assert client.get(f"/api/v1/tasks/{task_id}").json()["result"] == result

    with Database(settings.database_path).session() as conn:
        other = queue.enqueue(conn, "scan_storage_root")
    assert client.get(f"/api/v1/exports/{other}").status_code == 404


# --- Settings for many photos ---------------------------------------------------------------


def test_apply_settings_to_many(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = tmp_path / "Photos"
    root.mkdir()
    with Database(settings.database_path).session() as conn:
        conn.execute(
            "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, "
            "updated_at) VALUES (1, ?, ?, 'Photos', ?, ?)",
            (str(root), str(root).lower(), NOW, NOW),
        )
        first = add_photo(conn, root, "IMG_0001.JPG")
        second = add_photo(conn, root, "IMG_0002.JPG")
        video = add_photo(conn, root, "clip.jpg", media_type="video")
    client.put(f"/api/v1/assets/{first}/edit", json={"exposure": 1, "rotate": 1})

    body = {
        "asset_ids": [first, second, video, first],
        "recipe": {"saturation": -100, "contrast": 20, "exposure": 3, "rotate": 2},
        "fields": ["saturation", "contrast"],
    }
    response = client.post("/api/v1/edits/batch", json=body)
    assert response.json() == {"updated": 2, "skipped": 1}
    one = client.get(f"/api/v1/assets/{first}/edit").json()
    # Only the chosen fields change; the rest of each photo's edit stays.
    assert (one["recipe"]["saturation"], one["recipe"]["contrast"]) == (-100, 20)
    assert (one["recipe"]["exposure"], one["recipe"]["rotate"]) == (1, 1)
    assert [s["changes"] for s in one["steps"]][-1] == ["contrast", "saturation"]
    two = client.get(f"/api/v1/assets/{second}/edit").json()
    assert two["recipe"]["exposure"] == 0 and two["is_edited"]

    assert client.post("/api/v1/edits/batch", json=body).json() == {"updated": 0, "skipped": 1}
    bad = client.post("/api/v1/edits/batch", json={**body, "fields": ["version"]})
    assert bad.status_code == 422
