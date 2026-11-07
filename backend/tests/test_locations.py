"""Locations and capture times corrected in LUMEN (ADR-035)."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lumen.app import create_app
from lumen.core.config import Settings
from tests.conftest import TOKEN
from tests.media_factory import make_jpeg
from tests.test_pipeline import wait_idle

pytestmark = pytest.mark.skipif(
    not (shutil.which("exiftool") and shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="exiftool and ffmpeg are required",
)

KOTOR = (42.4247, 18.7712)
SARAJEVO = (43.8563, 18.4131)


@pytest.fixture
def library(tmp_path: Path) -> Iterator[tuple[TestClient, Any, Path, dict[str, int]]]:
    """A phone photo with GPS, and camera photos without: 30 min and 9 h later."""
    root = tmp_path / "Photos"
    make_jpeg(root / "IMG_1.JPG", taken="2025:10:20 12:00:00", gps=KOTOR, model="iPhone 16 Pro")
    make_jpeg(root / "DSC_1.JPG", taken="2025:10:20 12:30:00", model="D90", color=(9, 9, 200))
    make_jpeg(root / "DSC_2.JPG", taken="2025:10:20 21:00:00", model="D90", color=(9, 200, 9))
    app = create_app(Settings(data_dir=tmp_path / "data", log_to_file=False), TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        made = client.post("/api/v1/storage-roots", json={"path": str(root)}).json()
        wait_idle(app.state.db)
        items = client.get("/api/v1/assets", params={"limit": 100}).json()["items"]
        yield client, (app, made["id"]), root, {i["file_name"]: i["id"] for i in items}


def _rescan(client: TestClient, app: Any, root_id: int, path: Path) -> None:
    """Make the file look changed, so its metadata is read again."""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    client.post(f"/api/v1/storage-roots/{root_id}/scan")
    wait_idle(app.state.db)


def test_set_and_restore_locations(
    library: tuple[TestClient, Any, Path, dict[str, int]],
) -> None:
    client, (app, root_id), root, ids = library
    phone, camera = ids["IMG_1.JPG"], ids["DSC_1.JPG"]

    changed = client.post(
        "/api/v1/assets/location",
        json={"asset_ids": [phone, camera], "latitude": SARAJEVO[0], "longitude": SARAJEVO[1]},
    )
    assert changed.json() == {"changed": 2}
    detail = client.get(f"/api/v1/assets/{camera}").json()
    assert detail["location"]["source"] == "manual"
    assert detail["place"]["city"]["name"] == "Sarajevo"  # named at once

    # Reading the file again keeps the user's location.
    _rescan(client, app, root_id, root / "IMG_1.JPG")
    assert client.get(f"/api/v1/assets/{phone}").json()["location"]["latitude"] == SARAJEVO[0]

    restored = client.post("/api/v1/assets/location/restore", json={"asset_ids": [phone, camera]})
    assert restored.json() == {"changed": 2}
    back = client.get(f"/api/v1/assets/{phone}").json()
    assert back["location"]["source"] == "exif"
    assert abs(back["location"]["latitude"] - KOTOR[0]) < 1e-4
    assert back["place"]["city"]["name"] == "Kotor"
    gone = client.get(f"/api/v1/assets/{camera}").json()
    assert gone["location"] is None and gone["place"] is None  # its file has no GPS


def test_borrow_the_location_of_a_photo_taken_close_in_time(
    library: tuple[TestClient, Any, Path, dict[str, int]],
) -> None:
    client, _, _, ids = library
    cameras = [ids["DSC_1.JPG"], ids["DSC_2.JPG"]]
    preview = client.post(
        "/api/v1/assets/location/nearby", json={"asset_ids": cameras, "max_hours": 2}
    ).json()
    assert (preview["found"], preview["missing"]) == (1, 1)
    [example] = preview["examples"]
    assert example["asset_id"] == ids["DSC_1.JPG"] and example["from_asset_id"] == ids["IMG_1.JPG"]
    assert example["gap_s"] == 1800
    assert client.get(f"/api/v1/assets/{cameras[0]}").json()["location"] is None  # a preview

    client.post(
        "/api/v1/assets/location/nearby",
        json={"asset_ids": cameras, "max_hours": 12, "apply": True},
    )
    for camera in cameras:
        detail = client.get(f"/api/v1/assets/{camera}").json()
        assert detail["location"]["source"] == "manual"
        assert detail["place"]["city"]["name"] == "Kotor"


def test_shift_capture_times(library: tuple[TestClient, Any, Path, dict[str, int]]) -> None:
    client, (app, root_id), root, ids = library
    camera = ids["DSC_1.JPG"]
    too_far = client.post(
        "/api/v1/assets/time-shift", json={"asset_ids": [camera], "seconds": 500 * 86400}
    )
    assert too_far.status_code == 422
    shifted = client.post(
        "/api/v1/assets/time-shift", json={"asset_ids": [camera], "seconds": -7 * 3600}
    )
    assert shifted.json() == {"changed": 1}
    detail = client.get(f"/api/v1/assets/{camera}").json()
    assert (detail["capture_time"], detail["time_shift_s"]) == ("2025-10-20T05:30:00", -25200)

    # Reading the file again applies the shift again.
    _rescan(client, app, root_id, root / "DSC_1.JPG")
    assert client.get(f"/api/v1/assets/{camera}").json()["capture_time"] == "2025-10-20T05:30:00"

    client.post("/api/v1/assets/time-shift/restore", json={"asset_ids": [camera]})
    detail = client.get(f"/api/v1/assets/{camera}").json()
    assert (detail["capture_time"], detail["time_shift_s"]) == ("2025-10-20T12:30:00", 0)


def test_exports_carry_the_corrections(
    library: tuple[TestClient, Any, Path, dict[str, int]], tmp_path: Path
) -> None:
    client, (app, _), _, ids = library
    camera = ids["DSC_1.JPG"]
    client.post(
        "/api/v1/assets/location",
        json={"asset_ids": [camera], "latitude": -SARAJEVO[0], "longitude": -SARAJEVO[1]},
    )
    client.post("/api/v1/assets/time-shift", json={"asset_ids": [camera], "seconds": 3600})
    out = tmp_path / "out"
    out.mkdir()
    client.post(
        "/api/v1/exports",
        json={"asset_ids": [camera], "destination": str(out), "include_location": True},
    )
    wait_idle(app.state.db)
    [exported] = list(out.glob("*.jpg"))
    tags = subprocess.run(
        ["exiftool", "-n", "-s3", "-GPSLatitude", "-GPSLongitude", "-DateTimeOriginal",
         str(exported)],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    assert abs(float(tags[0]) + SARAJEVO[0]) < 1e-4  # south
    assert abs(float(tags[1]) + SARAJEVO[1]) < 1e-4  # west
    assert " ".join(tags[2:]) == "2025:10:20 13:30:00"


def test_search_places_offline(client: TestClient) -> None:
    [first, *_] = client.get("/api/v1/places/search", params={"q": "sarajevo"}).json()
    assert first["city"]["zh"] == "塞拉耶佛"
    assert first["country"]["name"] == "Bosnia and Herzegovina"
    assert abs(first["latitude"] - 43.85) < 0.1
    assert client.get("/api/v1/places/search", params={"q": "zzqqxx"}).json() == []
