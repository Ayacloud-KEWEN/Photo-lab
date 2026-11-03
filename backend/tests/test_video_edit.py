"""Video edits (trim, rotation, sound): the recipe, ffmpeg commands, API and exports."""

from __future__ import annotations

import io
import json
import shutil
import sqlite3
import subprocess
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lumen.core.config import Settings
from lumen.db.connection import Database
from lumen.develop.recipe import VideoRecipe, parse_recipe
from lumen.develop.video import VideoOptions, build_command
from lumen.library.exports import EXPORT_TASK, export_assets
from lumen.services.develop import save_video_edit
from lumen.tasks import queue
from lumen.tasks.runner import TaskContext
from tests.media_factory import make_video
from tests.test_develop import NOW, add_photo

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg is required"
)


def probe(path: Path) -> dict[str, object]:
    ffprobe = shutil.which("ffprobe")
    assert ffprobe
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, check=True, text=True, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    data: dict[str, object] = json.loads(completed.stdout)
    return data


# --- Recipe and commands --------------------------------------------------------------------


def test_video_recipe() -> None:
    assert VideoRecipe().content_hash() == ""
    assert VideoRecipe(mute=True).content_hash() != ""
    with pytest.raises(ValueError):
        VideoRecipe(trim_start_ms=2000, trim_end_ms=2050)  # shorter than 0.1 s
    stored = VideoRecipe(trim_start_ms=500, rotate=3).canonical_json()
    assert parse_recipe(stored) == VideoRecipe(trim_start_ms=500, rotate=3)
    assert parse_recipe('{"exposure": 1}').model_dump()["exposure"] == 1  # photo recipes


def test_ffmpeg_commands() -> None:
    source, target = Path("in.mov"), Path("out.mov")
    recipe = VideoRecipe(trim_start_ms=1500, trim_end_ms=4000, rotate=1, mute=True)
    copy = build_command("ffmpeg", source, target, recipe, VideoOptions(), stored_rotation=-90)
    assert copy[:2] == ["ffmpeg", "-nostdin"]  # never reads the backend's stdin
    # The stored rotation (counter-clockwise) turned a quarter further clockwise.
    assert copy[copy.index("-display_rotation:v:0") + 1] == "-180"
    assert copy[copy.index("-ss") + 1] == "1.500" and copy[copy.index("-t") + 1] == "2.500"
    assert "0:a:0?" not in copy and copy[copy.index("-c") + 1] == "copy"
    assert "location=" in copy and "com.apple.quicktime.location.ISO6709=" in copy

    encode = build_command(
        "ffmpeg", source, Path("out.mp4"), VideoRecipe(rotate=3),
        VideoOptions(mode="h264", include_location=True),
    )  # fmt: skip
    assert "-display_rotation:v:0" not in encode and "-ss" not in encode
    assert encode[encode.index("-vf") + 1] == "transpose=cclock,format=yuv420p"
    assert "0:a:0?" in encode and "location=" not in encode
    bare = build_command(
        "ffmpeg", source, target, VideoRecipe(), VideoOptions(include_metadata=False)
    )
    assert bare[bare.index("-map_metadata") + 1] == "-1"


# --- API and export -------------------------------------------------------------------------


def add_video(conn: sqlite3.Connection, root: Path, name: str, seconds: int = 4) -> int:
    make_video(root / name, seconds=seconds, audio=True)
    asset_id = conn.execute(
        "INSERT INTO media_assets (uuid, media_type, capture_time, created_at, updated_at) "
        "VALUES (?, 'video', '2025-01-01T10:00:00', ?, ?)",
        (str(uuid.uuid4()), NOW, NOW),
    ).lastrowid
    file_id = conn.execute(
        """
        INSERT INTO media_files (storage_root_id, relative_path, relative_path_key, file_name,
            extension, asset_id, size_bytes, modified_at, ingest_state, fingerprint,
            mime_type, created_at, updated_at)
        VALUES (1, ?, ?, ?, 'mp4', ?, 1, ?, 'done', ?, 'video/mp4', ?, ?)
        """,
        (name, name.lower(), name, asset_id, NOW, f"xxh128:{uuid.uuid4().hex}", NOW, NOW),
    ).lastrowid
    conn.execute("UPDATE media_assets SET cover_file_id = ? WHERE id = ?", (file_id, asset_id))
    conn.execute(
        "INSERT INTO media_metadata (file_id, duration_ms, extractor, extractor_version, "
        "extracted_at) VALUES (?, ?, 'test', '1', ?)",
        (file_id, seconds * 1000, NOW),
    )
    assert asset_id is not None
    return asset_id


@pytest.fixture
def media(client: TestClient, settings: Settings, tmp_path: Path) -> tuple[TestClient, int, int]:
    """The API with a 4 s video (with sound) and a photo; returns (client, video, photo)."""
    root = tmp_path / "Videos"
    root.mkdir()
    with Database(settings.database_path).session() as conn:
        conn.execute(
            "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, "
            "updated_at) VALUES (1, ?, ?, 'Videos', ?, ?)",
            (str(root), str(root).lower(), NOW, NOW),
        )
        video = add_video(conn, root, "clip.mp4")
        photo = add_photo(conn, root, "IMG_0001.JPG")
    return client, video, photo


@needs_ffmpeg
def test_video_edit_api(media: tuple[TestClient, int, int], tmp_path: Path) -> None:
    client, video, photo = media
    state = client.get(f"/api/v1/assets/{video}/video-edit").json()
    assert state["duration_ms"] == 4000 and not state["is_edited"]
    assert state["recipe"] == VideoRecipe().model_dump()
    poster = client.get(f"/api/v1/assets/{video}/thumbnail", params={"variant": "preview"})
    assert Image.open(io.BytesIO(poster.content)).size == (320, 240)

    saved = client.put(
        f"/api/v1/assets/{video}/video-edit",
        json={"trim_start_ms": 1000, "trim_end_ms": 9000, "rotate": 1, "mute": True},
    ).json()
    assert saved["is_edited"] and saved["rendition_version"] != state["rendition_version"]
    assert saved["recipe"]["trim_end_ms"] is None  # past the end: "to the end"
    assert client.get(f"/api/v1/assets/{video}").json()["is_edited"] is True
    turned = client.get(f"/api/v1/assets/{video}/thumbnail", params={"variant": "preview"})
    assert Image.open(io.BytesIO(turned.content)).size == (240, 320)

    late = client.put(f"/api/v1/assets/{video}/video-edit", json={"trim_start_ms": 5000})
    assert late.status_code == 400
    assert client.get(f"/api/v1/assets/{photo}/video-edit").status_code == 409
    assert client.get(f"/api/v1/assets/{video}/edit").status_code == 409  # photo editing

    out = tmp_path / "Frames"
    out.mkdir()
    frame = client.post(
        f"/api/v1/assets/{video}/frame-export", json={"time_ms": 2000, "destination": str(out)}
    )
    assert frame.status_code == 200
    path = Path(frame.json()["path"])
    assert path.name == "clip_00-02.jpg" and Image.open(path).size == (240, 320)
    bad = client.post(
        f"/api/v1/assets/{video}/frame-export", json={"time_ms": 0, "destination": "nope"}
    )
    assert bad.status_code == 422


@needs_ffmpeg
@pytest.mark.parametrize("mode", ["copy", "h264"])
def test_export_task_cuts_videos(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path, mode: str
) -> None:
    root = tmp_path / "Videos"
    root.mkdir()
    conn.execute(
        "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, updated_at) "
        "VALUES (1, ?, ?, 'Videos', ?, ?)",
        (str(root), str(root).lower(), NOW, NOW),
    )
    video = add_video(conn, root, "clip.mp4")
    save_video_edit(
        conn, video, VideoRecipe(trim_start_ms=1000, trim_end_ms=3000, rotate=1, mute=True)
    )
    out = tmp_path / "Export"
    out.mkdir()
    payload: dict[str, object] = {
        "asset_ids": [video], "destination": str(out), "video_mode": mode,
    }  # fmt: skip
    task_id = queue.enqueue(conn, EXPORT_TASK, payload=payload, unique=False)
    queue.claim_next(conn)
    ctx = TaskContext(
        conn=conn, settings=settings, task_id=task_id, kind=EXPORT_TASK, storage_root_id=None,
        payload=payload, stop_event=threading.Event(), enqueue=lambda *a, **k: 0,
    )  # fmt: skip
    assert export_assets(ctx)["exported"] == 1

    [exported] = list(out.iterdir())
    assert exported.name == "clip.mp4"
    info = probe(exported)
    streams = info["streams"]
    assert isinstance(streams, list) and isinstance(info["format"], dict)
    assert [s["codec_type"] for s in streams] == ["video"]  # muted
    assert abs(float(info["format"]["duration"]) - 2.0) < 0.5
    stream = streams[0]
    if mode == "h264":
        assert (stream["codec_name"], stream["width"], stream["height"]) == ("h264", 240, 320)
    else:  # copied: turned by metadata
        rotation = [d.get("rotation") for d in stream.get("side_data_list", [])]
        assert -90 in rotation
    assert (root / "clip.mp4").exists()  # the original stays
