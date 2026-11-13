"""Videos the web view cannot play (AVI, MTS...) are imported and played from a copy."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen.app import create_app
from lumen.core.config import Settings
from lumen.media.formats import format_for, needs_playback_copy
from tests.conftest import TOKEN
from tests.media_factory import make_video
from tests.test_pipeline import wait_idle

needs_tools = pytest.mark.skipif(
    not (shutil.which("exiftool") and shutil.which("ffmpeg")), reason="exiftool/ffmpeg required"
)


def test_formats() -> None:
    for ext in ("avi", "AVI", ".wmv", "mpg", "mpeg", "3gp", "mkv", "webm", "mts", "m2ts"):
        assert format_for(ext) is not None and format_for(ext).kind == "video"  # type: ignore[union-attr]
    assert needs_playback_copy("avi") and needs_playback_copy("MTS")
    assert not needs_playback_copy("mp4") and not needs_playback_copy("mov")
    assert not needs_playback_copy("jpg") and not needs_playback_copy("txt")


@needs_tools
def test_avi_is_imported_and_played_from_a_copy(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", log_to_file=False), TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        _play_avi(client, tmp_path)


def _play_avi(client: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "Videos"
    make_video(folder / "old_dv.avi", seconds=2, audio=True)
    make_video(folder / "phone.mp4", seconds=1)
    client.post("/api/v1/storage-roots", json={"path": str(folder)})
    db = client.app.state.db  # type: ignore[attr-defined]
    wait_idle(db)
    items = {i["file_name"]: i for i in client.get("/api/v1/assets").json()["items"]}
    assert set(items) == {"old_dv.avi", "phone.mp4"}
    avi = items["old_dv.avi"]
    assert avi["media_type"] == "video" and avi["duration_ms"] and avi["duration_ms"] >= 1500
    assert client.get(f"/api/v1/assets/{avi['id']}/thumbnail").status_code == 200

    detail = client.get(f"/api/v1/assets/{avi['id']}").json()
    assert detail["needs_playback_copy"] is True
    mp4 = items["phone.mp4"]
    assert client.get(f"/api/v1/assets/{mp4['id']}").json()["needs_playback_copy"] is False
    assert client.get(f"/api/v1/assets/{mp4['id']}/playback/state").json() == {
        "needed": False, "ready": True, "task_id": None,
    }  # fmt: skip

    url = f"/api/v1/assets/{avi['id']}/playback"
    assert client.get(f"{url}/state").json() == {"needed": True, "ready": False, "task_id": None}
    assert client.get(url).status_code == 404
    started = client.get(f"{url}/state", params={"start": True}).json()
    assert started["task_id"] is not None
    # Asked again while it runs: the same task.
    again = client.get(f"{url}/state", params={"start": True}).json()
    assert again["task_id"] in (started["task_id"], None)
    wait_idle(db)
    task = client.get(f"/api/v1/tasks/{started['task_id']}").json()
    assert task["status"] == "succeeded", task
    assert client.get(f"{url}/state").json()["ready"] is True

    # As the <video> element asks: the token in the address, no header.
    played = client.get(
        url,
        params={"token": TOKEN},
        headers={"Range": "bytes=0-99", "Authorization": ""},
    )
    assert played.status_code == 206 and played.headers["content-type"] == "video/mp4"
    assert played.content[4:8] == b"ftyp"
    # The original is untouched.
    assert (folder / "old_dv.avi").read_bytes()[:4] == b"RIFF"
