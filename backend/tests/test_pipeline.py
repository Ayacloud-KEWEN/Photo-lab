"""End-to-end: register a folder, scan, ingest, rescan after changes (real ExifTool/FFmpeg)."""

from __future__ import annotations

import shutil
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lumen.app import create_app
from lumen.core.config import Settings
from lumen.db.connection import Database
from lumen.library import ingest
from lumen.library.handlers import HANDLERS
from lumen.media import thumbnails
from lumen.schemas.storage_roots import StorageRootCreate
from lumen.services import storage_roots
from lumen.tasks.runner import TaskRunner
from tests.conftest import TOKEN
from tests.media_factory import make_heic, make_jpeg, make_sample_library, make_video

pytestmark = pytest.mark.skipif(
    not (shutil.which("exiftool") and shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="exiftool and ffmpeg are required",
)


def wait_idle(db: Database, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    with db.session() as conn:
        while time.monotonic() < deadline:
            active = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('pending', 'running')"
            ).fetchone()[0]
            if active == 0:
                return
            time.sleep(0.05)
    raise AssertionError("tasks did not finish in time")


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "Photos"
    make_sample_library(root)
    # A RAW+JPEG pair. The "RAW" is not decodable, so it ends in an ingest error,
    # but it must still be grouped with its JPEG.
    make_jpeg(root / "2024" / "05" / "IMG_0003.JPG", taken="2024:05:03 07:00:00")
    (root / "2024" / "05" / "IMG_0003.CR2").write_bytes(b"II*\x00 fake raw")
    return root


@pytest.fixture
def runner(db: Database, settings: Settings) -> Iterator[TaskRunner]:
    task_runner = TaskRunner(db, settings, HANDLERS)
    task_runner.start()
    yield task_runner
    task_runner.stop()


def register(conn: sqlite3.Connection, runner: TaskRunner, path: Path) -> int:
    root_id = storage_roots.create_storage_root(conn, StorageRootCreate(path=str(path))).id
    runner.wake()
    return root_id


def file_row(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM media_files WHERE file_name = ?", (name,)).fetchone()
    assert row is not None, name
    return row


def metadata(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT m.* FROM media_metadata m JOIN media_files f ON f.id = m.file_id "
        "WHERE f.file_name = ?",
        (name,),
    ).fetchone()
    assert row is not None, name
    return row


def test_full_ingest(
    conn: sqlite3.Connection, db: Database, settings: Settings, runner: TaskRunner, library: Path
) -> None:
    root_id = register(conn, runner, library)
    wait_idle(db)

    root = storage_roots.get_storage_root(conn, root_id)
    assert root.status == "ready" and root.last_scanned_at
    # 10 media files (incl. duplicate + fake RAW), sidecar excluded; hidden/txt ignored.
    assert root.stats.file_count == 10
    assert root.stats.error_count == 1  # the fake RAW
    assert root.stats.pending_count == 0
    tasks = conn.execute("SELECT kind, status FROM tasks ORDER BY id").fetchall()
    assert [tuple(t) for t in tasks] == [
        ("scan_storage_root", "succeeded"),
        ("ingest_storage_root", "succeeded"),
        ("geo_locate_assets", "succeeded"),  # place names for the located photo
    ]

    # RAW+JPEG pairing: one asset, RAW primary, JPEG companion and cover.
    raw, jpeg = file_row(conn, "IMG_0003.CR2"), file_row(conn, "IMG_0003.JPG")
    assert raw["asset_id"] == jpeg["asset_id"]
    assert (raw["file_role"], jpeg["file_role"]) == ("primary", "companion")
    asset = conn.execute("SELECT * FROM media_assets WHERE id = ?", (raw["asset_id"],)).fetchone()
    assert asset["cover_file_id"] == jpeg["id"]
    assert raw["ingest_state"] == "error" and raw["ingest_attempts"] == ingest.MAX_FILE_ATTEMPTS

    # Sidecar attached to its photo's asset.
    assert file_row(conn, "IMG_0002.xmp")["asset_id"] == file_row(conn, "IMG_0002.jpg")["asset_id"]

    # Photo metadata, orientation and GPS.
    portrait = metadata(conn, "IMG_0001.JPG")
    assert (portrait["width"], portrait["height"]) == (400, 600)
    assert portrait["capture_time"] == "2024-05-01T10:22:33"
    assert portrait["camera_model"] == "EOS R5"
    location = conn.execute(
        "SELECT l.* FROM media_locations l JOIN media_files f ON f.asset_id = l.asset_id "
        "WHERE f.file_name = 'IMG_0001.JPG'"
    ).fetchone()
    assert location["latitude"] == pytest.approx(31.2304, abs=1e-3)

    # Unicode path read by ExifTool; HEIC and video metadata.
    assert metadata(conn, "西湖 日落.jpg")["capture_time"] == "2023-10-01T17:45:00"
    assert metadata(conn, "IMG_5001.HEIC")["camera_model"] == "iPhone 15 Pro"
    video = metadata(conn, "clip.mp4")
    assert (video["video_codec"], video["frame_rate"]) == ("h264", 25.0)
    assert video["duration_ms"] == pytest.approx(2000, abs=100)

    # Every asset has a capture time; files without EXIF fall back to mtime.
    assert (
        conn.execute("SELECT COUNT(*) FROM media_assets WHERE capture_time IS NULL").fetchone()[0]
        == 0
    )

    # Renditions exist for processed files.
    portrait_file = file_row(conn, "IMG_0001.JPG")
    target = thumbnails.rendition_paths(settings.cache_dir, portrait_file["fingerprint"])
    with Image.open(target.thumb) as thumb:
        assert thumb.height > thumb.width

    # Identical files share a fingerprint.
    assert (
        file_row(conn, "IMG_0002.jpg")["fingerprint"]
        == file_row(conn, "IMG_0002_copy.jpg")["fingerprint"]
    )


def test_rescan_detects_moves_changes_and_missing_files(
    conn: sqlite3.Connection, db: Database, runner: TaskRunner, library: Path
) -> None:
    root_id = register(conn, runner, library)
    wait_idle(db)
    moved = file_row(conn, "IMG_0002.jpg")
    conn.execute(  # as the API does for a user rating
        "UPDATE media_assets SET rating = 5, rating_source = 'user' WHERE id = ?",
        (moved["asset_id"],),
    )
    changed = file_row(conn, "西湖 日落.jpg")
    removed = file_row(conn, "poster.png")

    # Move a file, edit another, delete a third.
    target = library / "sorted" / "IMG_0002.jpg"
    target.parent.mkdir()
    shutil.move(library / "2024" / "05" / "IMG_0002.jpg", target)
    make_jpeg(library / "旅行" / "西湖 日落.jpg", taken="2023:10:01 17:45:00", color=(1, 2, 3))
    (library / "exports" / "poster.png").unlink()

    storage_roots.request_scan(conn, root_id)
    runner.wake()
    wait_idle(db)

    relocated = conn.execute(
        "SELECT * FROM media_files WHERE relative_path_key LIKE '%sorted%'"
    ).fetchone()
    assert relocated["asset_id"] == moved["asset_id"]  # same asset, rating kept
    assert (
        conn.execute(
            "SELECT rating FROM media_assets WHERE id = ?", (moved["asset_id"],)
        ).fetchone()[0]
        == 5
    )
    assert conn.execute("SELECT 1 FROM media_files WHERE id = ?", (moved["id"],)).fetchone() is None

    edited = file_row(conn, "西湖 日落.jpg")
    assert edited["id"] == changed["id"] and edited["asset_id"] == changed["asset_id"]
    assert edited["fingerprint"] != changed["fingerprint"]
    assert edited["ingest_state"] == "done"

    gone = file_row(conn, "poster.png")
    assert gone["status"] == "missing"
    assert conn.execute(
        "SELECT 1 FROM media_assets WHERE id = ?", (removed["asset_id"],)
    ).fetchone()  # kept: the drive may come back


def test_offline_root_keeps_files(
    conn: sqlite3.Connection, db: Database, runner: TaskRunner, library: Path
) -> None:
    root_id = register(conn, runner, library)
    wait_idle(db)
    library.rename(library.with_name("Unplugged"))

    task_id = storage_roots.request_scan(conn, root_id)
    runner.wake()
    wait_idle(db)

    assert storage_roots.get_storage_root(conn, root_id).status == "offline"
    task = conn.execute("SELECT status, error FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert task["status"] == "failed" and "not reachable" in task["error"]
    assert (
        conn.execute("SELECT COUNT(*) FROM media_files WHERE status = 'missing'").fetchone()[0] == 0
    )


def test_ingest_resumes_after_interruption(
    conn: sqlite3.Connection,
    db: Database,
    settings: Settings,
    library: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingest, "BATCH_SIZE", 2)
    first = TaskRunner(db, settings, HANDLERS)
    original = ingest._process_batch

    def process_then_shut_down(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        first._stop.set()  # simulate the app closing after the first batch

    monkeypatch.setattr(ingest, "_process_batch", process_then_shut_down)
    first.start()
    register(conn, first, library)
    first._thread.join(30)  # type: ignore[union-attr]

    states = dict(
        conn.execute("SELECT ingest_state, COUNT(*) FROM media_files GROUP BY 1").fetchall()
    )
    assert states.get("done") == 2 and states.get("pending", 0) > 0
    task = conn.execute("SELECT status FROM tasks WHERE kind = 'ingest_storage_root'").fetchone()
    assert task["status"] == "pending"

    monkeypatch.setattr(ingest, "_process_batch", original)
    second = TaskRunner(db, settings, HANDLERS)
    second.start()
    try:
        wait_idle(db)
    finally:
        second.stop()
    assert (
        conn.execute("SELECT COUNT(*) FROM media_files WHERE ingest_state = 'pending'").fetchone()[
            0
        ]
        == 0
    )


def test_api_end_to_end(tmp_path: Path, library: Path) -> None:
    settings = Settings(data_dir=tmp_path / "api-data", log_to_file=False)
    app = create_app(settings, TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        root = client.post("/api/v1/storage-roots", json={"path": str(library)}).json()
        wait_idle(app.state.db)

        assert client.get("/api/v1/tasks", params={"active": True}).json() == {"items": []}
        roots = client.get("/api/v1/storage-roots").json()["items"]
        assert roots[0]["status"] == "ready"

        # Pagination: newest capture first, cursor chaining covers every asset once.
        seen: list[int] = []
        cursor = None
        while True:
            params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
            page = client.get("/api/v1/assets", params=params).json()
            seen += [item["id"] for item in page["items"]]
            cursor = page["next_cursor"]
            if not cursor:
                break
        assert len(seen) == len(set(seen)) == 9  # 10 files, RAW+JPEG share an asset
        items = client.get("/api/v1/assets", params={"limit": 100}).json()["items"]
        times = [item["capture_time"] for item in items]
        assert times == sorted(times, reverse=True)
        first = next(item for item in items if item["file_name"] == "clip.mp4")
        assert first["media_type"] == "video" and first["duration_ms"] > 0

        detail = client.get(f"/api/v1/assets/{first['id']}").json()
        assert detail["metadata"]["video_codec"] == "h264"
        assert detail["files"][0]["path"].endswith("clip.mp4")

        # Thumbnails: header or ?token=, never without.
        url = f"/api/v1/assets/{first['id']}/thumbnail"
        assert client.get(url).headers["content-type"] == "image/jpeg"
        anonymous = TestClient(app)
        assert anonymous.get(url).status_code == 401
        assert anonymous.get(url, params={"token": TOKEN, "variant": "preview"}).status_code == 200
        assert anonymous.get(url, params={"token": "wrong"}).status_code == 401

        duplicates = client.get("/api/v1/duplicates").json()
        assert len(duplicates["groups"]) == 1
        assert len(duplicates["groups"][0]["files"]) == 2
        assert duplicates["reclaimable_bytes"] > 0

        scan = client.post(f"/api/v1/storage-roots/{root['id']}/scan")
        assert scan.status_code == 202 and scan.json()["kind"] == "scan_storage_root"
        wait_idle(app.state.db)
        failed = client.post(f"/api/v1/tasks/{scan.json()['id']}/cancel")
        assert failed.status_code == 409


def test_live_photos_end_to_end(tmp_path: Path) -> None:
    phone = tmp_path / "Phone"
    make_heic(phone / "IMG_7001.HEIC")
    make_video(phone / "IMG_7001.MOV", seconds=2)  # Live Photo clip
    make_heic(phone / "IMG_7002.HEIC")
    make_video(phone / "IMG_7002.MOV", seconds=6)  # a real video sharing the name
    make_video(phone / "IMG_7003.MOV", seconds=2)  # its still arrives later

    settings = Settings(data_dir=tmp_path / "data", log_to_file=False)
    app = create_app(settings, TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        root = client.post("/api/v1/storage-roots", json={"path": str(phone)}).json()
        wait_idle(app.state.db)

        items = {i["file_name"]: i for i in client.get("/api/v1/assets").json()["items"]}
        assert set(items) == {"IMG_7001.HEIC", "IMG_7002.HEIC", "IMG_7002.MOV", "IMG_7003.MOV"}
        live = items["IMG_7001.HEIC"]
        assert live["is_live"] and live["media_type"] == "photo"
        assert live["formats"] == ["HEIC", "MOV"]
        assert not items["IMG_7002.HEIC"]["is_live"]
        assert client.get("/api/v1/assets", params={"media_type": "video"}).json()["items"]

        detail = client.get(f"/api/v1/assets/{live['id']}").json()
        clip = next(f for f in detail["files"] if f["id"] == detail["motion_file_id"])
        assert clip["role"] == "companion" and clip["relative_path"] == "IMG_7001.MOV"
        url = f"/api/v1/assets/{live['id']}/motion"
        motion = TestClient(app).get(url, params={"token": TOKEN})  # as <video src> does
        assert motion.status_code == 200 and motion.headers["content-type"] == "video/quicktime"
        not_live = items["IMG_7002.HEIC"]["id"]
        assert client.get(f"/api/v1/assets/{not_live}/motion").status_code == 404

        # The clip was imported alone and rated; its still arrives with the next scan.
        video_id = items["IMG_7003.MOV"]["id"]
        client.patch(f"/api/v1/assets/{video_id}", json={"rating": 4, "is_favorite": True})
        make_heic(phone / "IMG_7003.HEIC")
        client.post(f"/api/v1/storage-roots/{root['id']}/scan")
        wait_idle(app.state.db)

        items = {i["file_name"]: i for i in client.get("/api/v1/assets").json()["items"]}
        assert "IMG_7003.MOV" not in items
        merged = items["IMG_7003.HEIC"]
        assert merged["is_live"] and (merged["rating"], merged["is_favorite"]) == (4, True)
        assert client.get(f"/api/v1/assets/{video_id}").status_code == 404
