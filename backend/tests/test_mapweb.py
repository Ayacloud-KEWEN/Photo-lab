"""Sending photos to MapWeb (ADR-034): the placement rules and a send to a fake MapWeb."""

from __future__ import annotations

import io
import json
import re
import shutil
import threading
from collections.abc import Iterator
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lumen.app import create_app
from lumen.core.config import Settings
from lumen.services import mapweb
from lumen.services.mapweb import Photo, plan_send
from tests.conftest import TOKEN
from tests.media_factory import make_jpeg
from tests.test_pipeline import wait_idle

ORIGIN = datetime(2025, 10, 20, 12, 0).timestamp()
KOTOR = (42.4247, 18.7712)


def photo(n: int, minutes: float, place: tuple[float, float] | None = KOTOR) -> Photo:
    lat, lng = place if place else (None, None)
    return Photo(n, f"k{n}", f"IMG_{n}.JPG", lat, lng, ORIGIN + minutes * 60)


def pin(n: int, minutes: float, place: tuple[float, float], photos: int = 0) -> dict[str, Any]:
    visited = datetime.fromtimestamp(ORIGIN + minutes * 60).astimezone().isoformat()
    return {"id": n, "lat": place[0], "lng": place[1], "visited_at": visited,
            "title": f"pin {n}", "photos": [{}] * photos}  # fmt: skip


def east(km: float) -> tuple[float, float]:
    return KOTOR[0], KOTOR[1] + km / 82.0  # about 82 km per degree of longitude here


# --- MapWeb's rules -------------------------------------------------------------------------


def test_photos_join_a_close_footprint_or_make_new_ones() -> None:
    photos = [
        photo(1, 0),  # at the footprint, an hour before it: attached
        photo(2, 10, east(0.2)),  # 200 m from photo 1's group? no: from the footprint, 10 min
        photo(3, 300, east(5)),  # far away: a new footprint
        photo(4, 330, east(5.2)),  # 200 m and 30 min from photo 3: the same new footprint
        photo(5, 500, east(5.2)),  # same place but 2 h 50 min later: a new one
        photo(6, 340, None),  # no location: the closest in time within an hour (photo 3's)
        photo(7, 2000, None),  # no location, nothing near in time: skipped
        photo(8, 20),  # sent before
    ]
    photos.sort(key=lambda p: p.time or 0)
    plan = plan_send(photos, [pin(10, 60, KOTOR)], sent={"k8"})

    [attached] = plan.attach
    assert attached.pin["id"] == 10 and [p.asset_id for p in attached.photos] == [1, 2]
    assert [[p.asset_id for p in g.photos] for g in plan.groups] == [[3, 4, 6], [5]]
    assert [p.asset_id for p in plan.duplicates] == [8]
    assert [p.asset_id for p in plan.unplaced] == [7]


def test_a_full_footprint_takes_no_more_photos() -> None:
    plan = plan_send([photo(1, 0)], [pin(10, 0, KOTOR, photos=mapweb.MAX_PHOTOS)], sent=set())
    assert plan.attach == [] and len(plan.groups) == 1


def test_capture_times_use_the_photo_offset_when_it_has_one() -> None:
    utc = mapweb._utc_seconds("2025-10-20T12:00:00", "+02:00")
    assert utc == datetime.fromisoformat("2025-10-20T10:00:00+00:00").timestamp()
    local = mapweb._utc_seconds("2025-10-20T12:00:00", None)
    assert local == datetime(2025, 10, 20, 12, 0).astimezone().timestamp()


# --- A fake MapWeb --------------------------------------------------------------------------


class FakeMapWeb:
    def __init__(self) -> None:
        self.points: list[dict[str, Any]] = [
            {"id": 1, "lat": 42.4247, "lng": 18.7712, "title": "Kotor 老城",
             "visited_at": "2025-10-20T10:30:00.000Z", "photos": [],
             "thumb_url": "/thumbs/2025/10/1-a.jpg", "emoji": "🏰", "plan_id": 1},
        ]  # fmt: skip
        self.uploads: list[dict[str, Any]] = []
        self.replaced: list[int] = []
        # What this Periplus says it supports (an older one: none).
        self.features: list[str] | None = ["photo-lookup", "photo-replace", "link-point"]

    @staticmethod
    def _fields(body: bytes, content_type: str) -> dict[str, bytes]:
        boundary = content_type.split("boundary=")[1].encode()
        fields: dict[str, bytes] = {}
        for part in body.split(b"--" + boundary)[1:-1]:
            head, _, content = part.partition(b"\r\n\r\n")
            name = re.search(rb'name="([^"]+)"', head)
            assert name is not None
            fields[name.group(1).decode()] = content[:-2]  # the closing \r\n
        return fields

    def handle(self, method: str, path: str, body: bytes, content_type: str) -> tuple[int, Any]:
        if method == "GET" and path == "/api/health":
            return 200, {"ok": True, **({"features": self.features} if self.features else {})}
        if method == "POST" and path == "/api/points/photo-lookup" and self.features:
            keys = set(json.loads(body)["keys"])
            return 200, [
                {"key": u["source_key"], "point_id": u["point_id"], "photo_id": u["id"]}
                for u in self.uploads
                if u["source_key"] in keys
            ]
        replace = re.fullmatch(r"/api/points/(\d+)/photos/(\d+)", path)
        if method == "PUT" and replace and self.features:
            upload = next((u for u in self.uploads if u["id"] == int(replace.group(2))), None)
            if upload is None or upload["point_id"] != int(replace.group(1)):
                return 404, {"error": "photo not found"}
            self.replaced.append(upload["id"])
            Image.open(io.BytesIO(self._fields(body, content_type)["image"])).verify()
            return 200, {"id": upload["point_id"]}
        if method == "GET" and path == "/api/points":
            return 200, self.points
        if method == "GET" and path == "/api/tracks":
            return 200, [{
                "id": 5, "name": "城墙徒步", "sport": "hiking",
                "started_at": "2025-10-20T09:00:00Z", "ended_at": "2025-10-20T10:00:00Z",
                "distance_m": 4200, "ascent_m": 260,
                "geometry": {"type": "LineString", "coordinates": [[18.77, 42.42], [18.78, 42.43]]},
            }]  # fmt: skip
        if method == "GET" and path == "/api/plans":
            return 200, [{"id": 1, "title": "巴尔干", "start_date": "2025-10-20",
                          "end_date": "2025-10-21"}]  # fmt: skip
        if method == "GET" and path == "/api/plans/1":
            return 200, {"id": 1, "title": "巴尔干", "days": [
                {"day_date": "2025-10-20", "title": "科托尔", "stops": [
                    {"name": "Kotor", "lat": 42.4247, "lng": 18.7712},
                    {"name": "没坐标的", "lat": None, "lng": None},
                ]},
                {"day_date": "2025-10-21", "title": "布德瓦", "stops": [
                    {"name": "Budva", "lat": 42.29, "lng": 18.84},
                ]},
            ]}  # fmt: skip
        if method == "GET" and path.startswith("/thumbs/"):
            return 200, "IMAGE"
        if method == "POST" and path == "/api/points/photo-keys":
            keys = set(json.loads(body)["keys"])
            return 200, [u["source_key"] for u in self.uploads if u["source_key"] in keys]
        if method == "POST" and path == "/api/points/batch":
            created = []
            for item in json.loads(body):
                point = {**item, "id": len(self.points) + 1, "photos": []}
                self.points.append(point)
                created.append(point)
            return 201, created
        match = re.fullmatch(r"/api/points/(\d+)/photos", path)
        if method == "POST" and match:
            fields = self._fields(body, content_type)
            point = next(p for p in self.points if p["id"] == int(match.group(1)))
            point["photos"].append({})
            self.uploads.append({
                "id": len(self.uploads) + 100,
                "point_id": point["id"], "source_key": fields["source_key"].decode(),
                "size": Image.open(io.BytesIO(fields["image"])).size,
            })  # fmt: skip
            return 200, point
        return 404, {"error": "not found"}


@pytest.fixture
def fake_mapweb() -> Iterator[tuple[str, FakeMapWeb]]:
    fake = FakeMapWeb()

    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            status, answer = fake.handle(
                self.command, self.path, body, self.headers.get("Content-Type") or ""
            )
            image = answer == "IMAGE"
            data = b"\xff\xd8\xff\xe0fake-jpeg" if image else json.dumps(answer).encode()
            self.send_response(status)
            self.send_header("Content-Type", "image/jpeg" if image else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = _answer

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", fake
    server.shutdown()


pytestmark_tools = pytest.mark.skipif(
    not (shutil.which("exiftool") and shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="exiftool and ffmpeg are required",
)


@pytest.fixture
def library(tmp_path: Path) -> Iterator[tuple[TestClient, Any, dict[str, int]]]:
    """Kotor: two photos by the existing footprint, two a few km away, one without GPS."""
    root = tmp_path / "Photos"
    make_jpeg(root / "IMG_1.JPG", size=(3000, 2000), taken="2025:10:20 12:40:00", gps=KOTOR)
    make_jpeg(root / "IMG_2.JPG", taken="2025:10:20 12:50:00", gps=KOTOR, color=(9, 9, 200))
    make_jpeg(root / "IMG_3.JPG", taken="2025:10:20 16:00:00", gps=east(4), color=(9, 200, 9))
    make_jpeg(root / "IMG_4.JPG", taken="2025:10:20 16:20:00", gps=east(4.1), color=(200, 9, 9))
    make_jpeg(root / "IMG_5.JPG", taken="2025:10:20 16:30:00", color=(99, 99, 9))
    app = create_app(Settings(data_dir=tmp_path / "data", log_to_file=False), TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        client.post("/api/v1/storage-roots", json={"path": str(root)})
        wait_idle(app.state.db)
        items = client.get("/api/v1/assets", params={"limit": 100}).json()["items"]
        yield client, app, {item["file_name"]: item["id"] for item in items}


@pytestmark_tools
def test_send_to_mapweb(
    library: tuple[TestClient, Any, dict[str, int]], fake_mapweb: tuple[str, FakeMapWeb]
) -> None:
    client, app, ids = library
    url, fake = fake_mapweb
    every = list(ids.values())

    # Nothing goes anywhere before the address is set.
    refused = client.post("/api/v1/mapweb/plan", json={"asset_ids": every})
    assert refused.json()["error"]["code"] == "mapweb_not_configured"
    status = client.post("/api/v1/mapweb/test", json={"url": f"{url}/"}).json()
    assert status == {
        "url": url, "point_count": 1, "features": ["photo-lookup", "photo-replace", "link-point"],
    }  # fmt: skip
    gone = client.post("/api/v1/mapweb/test", json={"url": "http://127.0.0.1:9"})
    assert gone.status_code == 502 and gone.json()["error"]["code"] == "mapweb_failed"
    client.patch("/api/v1/settings", json={"mapweb_url": url})

    plan = client.post("/api/v1/mapweb/plan", json={"asset_ids": every, "language": "zh-CN"})
    body = plan.json()
    assert body["photo_count"] == 5 and body["video_count"] == 0
    assert body["attach"] == [
        {"point_id": 1, "title": "Kotor 老城", "visited_at": "2025-10-20T10:30:00.000Z",
         "count": 2},
    ]  # fmt: skip
    [group] = body["groups"]
    assert group["count"] == 3  # IMG_3, IMG_4 and the one without GPS 10 min later
    assert group["title"].endswith(" · 2025-10-20 16:00")  # named after the town
    assert body["duplicate_count"] == body["unplaced_count"] == 0

    task = client.post(
        "/api/v1/mapweb/send",
        json={"asset_ids": every, "language": "zh-CN", "description": "巴尔干半岛旅行"},
    )
    assert task.status_code == 202 and task.json()["kind"] == "mapweb_send"
    wait_idle(app.state.db)
    done = client.get(f"/api/v1/tasks/{task.json()['id']}").json()
    assert done["status"] == "succeeded", done
    assert done["result"] == {
        "uploaded": 5, "created_points": 1, "attached_points": 1, "skipped": 0, "failed": [],
    }  # fmt: skip
    new_point = fake.points[1]
    assert new_point["description"] == "巴尔干半岛旅行" and new_point["emoji"] == "📷"
    taken = datetime(2025, 10, 20, 16, 0).astimezone()  # no EXIF offset: this computer's zone
    assert datetime.fromisoformat(new_point["visited_at"]) == taken
    by_point = sorted((u["point_id"], u["size"]) for u in fake.uploads)
    assert [p for p, _ in by_point] == [1, 1, 2, 2, 2]
    assert max(max(size) for _, size in by_point) == 2048  # the 3000 px photo was resized
    assert all(u["source_key"].startswith("lumen:") for u in fake.uploads)

    # Sending again finds everything already there.
    again = client.post("/api/v1/mapweb/plan", json={"asset_ids": every}).json()
    assert again["duplicate_count"] == 5 and again["groups"] == [] and again["attach"] == []


@pytestmark_tools
def test_photos_on_the_map_stay_in_step(
    library: tuple[TestClient, Any, dict[str, int]],
    fake_mapweb: tuple[str, FakeMapWeb],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lumen.api.v1 import mapweb as mapweb_api

    client, app, ids = library
    url, fake = fake_mapweb
    client.patch("/api/v1/settings", json={"mapweb_url": url})
    db = app.state.db
    every = list(ids.values())
    client.post("/api/v1/mapweb/send", json={"asset_ids": every})
    wait_idle(db)

    # Each photo sent is known to be on the map, on its footprint and as its photo there.
    assert client.get("/api/v1/mapweb/sync").json() == {
        "on_map": 5, "outdated": 0, "features": fake.features,
    }  # fmt: skip
    items = client.get("/api/v1/assets", params={"limit": 100}).json()["items"]
    assert {item["on_map"] for item in items} == {"yes"}
    first = ids["IMG_1.JPG"]
    assert client.get(f"/api/v1/assets/{first}").json()["map_point_id"] == 1
    opened: list[str] = []
    monkeypatch.setattr(mapweb_api, "open_in_browser", lambda u, **_: opened.append(u))
    assert client.post(f"/api/v1/mapweb/open/{first}").status_code == 204
    assert opened == [f"{url}/?point=1"]

    # Edited after sending: outdated, then replaced on the map in place.
    client.put(f"/api/v1/assets/{first}/edit", json={"exposure": 1})
    assert client.get("/api/v1/mapweb/sync").json()["outdated"] == 1
    outdated = client.get("/api/v1/assets", params={"on_map": "outdated"}).json()["items"]
    assert [item["id"] for item in outdated] == [first]
    assert client.get("/api/v1/assets", params={"on_map": "no"}).json()["items"] == []
    task = client.post("/api/v1/mapweb/update", json={}).json()
    wait_idle(db)
    assert client.get(f"/api/v1/tasks/{task['id']}").json()["result"] == {
        "replaced": 1, "failed": [],
    }  # fmt: skip
    sent_first = next(u["id"] for u in fake.uploads if u["source_key"].endswith(
        client.get(f"/api/v1/assets/{first}").json()["uuid"]
    ))  # fmt: skip
    assert fake.replaced == [sent_first]  # that photo, in place
    assert client.get("/api/v1/mapweb/sync").json()["outdated"] == 0

    # Taken off the map in MapWeb: forgotten after checking.
    fake.uploads = [u for u in fake.uploads if u["source_key"] != fake.uploads[0]["source_key"]]
    client.post("/api/v1/mapweb/sync")
    wait_idle(db)
    assert client.get("/api/v1/mapweb/sync").json()["on_map"] == 4
    assert len(client.get("/api/v1/assets", params={"on_map": "no"}).json()["items"]) == 1

    # An older MapWeb: sending only.
    fake.features = None
    assert client.get("/api/v1/mapweb/sync").json()["features"] == []
    task = client.post("/api/v1/mapweb/update", json={}).json()
    wait_idle(db)
    assert client.get(f"/api/v1/tasks/{task['id']}").json()["status"] == "failed"


@pytestmark_tools
def test_automatic_sending(
    library: tuple[TestClient, Any, dict[str, int]],
    fake_mapweb: tuple[str, FakeMapWeb],
    tmp_path: Path,
) -> None:
    client, app, ids = library
    url, fake = fake_mapweb
    db = app.state.db
    client.patch("/api/v1/settings", json={"mapweb_url": url})
    # Photos already in the library are never sent automatically, even when rated.
    on = client.patch("/api/v1/settings", json={"mapweb_auto_send": True}).json()
    assert on["mapweb_auto_since"] and on["mapweb_auto_min_rating"] == 4
    client.post("/api/v1/assets/batch", json={"asset_ids": list(ids.values()), "rating": 5})
    wait_idle(db)
    assert fake.uploads == []

    # A photo imported since: sent once rated 4 stars.
    make_jpeg(tmp_path / "Photos" / "IMG_6.JPG", taken="2025:10:20 12:45:00", gps=KOTOR)
    root = client.get("/api/v1/storage-roots").json()["items"][0]["id"]
    client.post(f"/api/v1/storage-roots/{root}/scan")
    wait_idle(db)
    new = next(
        i["id"] for i in client.get("/api/v1/assets", params={"limit": 100}).json()["items"]
        if i["file_name"] == "IMG_6.JPG"
    )  # fmt: skip
    assert fake.uploads == []  # not rated yet
    client.patch(f"/api/v1/assets/{new}", json={"rating": 4})
    wait_idle(db)
    assert [u["point_id"] for u in fake.uploads] == [1]  # by the Kotor footprint
    assert client.get(f"/api/v1/assets/{new}").json()["map_point_id"] == 1

    # Taken off the map: not sent again.
    fake.uploads = []
    client.post("/api/v1/mapweb/sync")
    client.patch(f"/api/v1/assets/{new}", json={"rating": 5})
    wait_idle(db)
    assert fake.uploads == []


@pytestmark_tools
def test_mapweb_layers_on_the_map(
    library: tuple[TestClient, Any, dict[str, int]], fake_mapweb: tuple[str, FakeMapWeb]
) -> None:
    client, app, ids = library
    url, fake = fake_mapweb
    client.patch("/api/v1/settings", json={"mapweb_url": url})
    base = "/api/v1/mapweb/layers"

    [footprint] = client.get(f"{base}/footprints").json()
    assert (footprint["id"], footprint["emoji"], footprint["thumb"]) == (
        1, "🏰", "/thumbs/2025/10/1-a.jpg",
    )  # fmt: skip
    # The photos MapWeb's import would put on it: the two by it (not the ones 4 km away,
    # nor the one without a location 6 hours later).
    here = client.get(f"{base}/footprints/1/photos").json()
    assert sorted(i["file_name"] for i in here["items"]) == ["IMG_1.JPG", "IMG_2.JPG"]
    assert here["here"] == [] and here["elsewhere"] == []

    [track] = client.get(f"{base}/tracks").json()
    assert track["sport"] == "hiking" and track["geometry"]["type"] == "LineString"
    assert client.get(f"{base}/plans").json()[0]["title"] == "巴尔干"
    plan = client.get(f"{base}/plans/1").json()
    first, second = plan["days"]
    assert [s["name"] for s in first["stops"]] == ["Kotor"]  # the stop without a place: skipped
    assert sorted(first["stops"][0]["asset_ids"]) == sorted([ids["IMG_1.JPG"], ids["IMG_2.JPG"]])
    assert second["stops"][0]["asset_ids"] == []  # nothing taken there that day

    # The thumbnail through LUMEN, as <img> asks for it (token in the address).
    thumb = client.get(
        f"{base}/thumb", params={"path": "/thumbs/2025/10/1-a.jpg", "token": TOKEN},
        headers={"Authorization": ""},
    )  # fmt: skip
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    for bad in ("/api/points", "/thumbs/../../.env", "/uploads/2025/a.jpg"):
        assert client.get(f"{base}/thumb", params={"path": bad}).status_code == 400

    # Photos sent to the footprint the user picked, whatever the placing rules say.
    far = ids["IMG_3.JPG"]
    client.post("/api/v1/mapweb/send", json={"asset_ids": [far], "point_id": 1})
    wait_idle(app.state.db)
    assert [u["point_id"] for u in fake.uploads] == [1]
    assert client.get(f"/api/v1/assets/{far}").json()["map_point_id"] == 1

    # Unreachable: the layers say so; LUMEN's own map is not concerned.
    client.patch("/api/v1/settings", json={"mapweb_url": "http://127.0.0.1:9"})
    from lumen.services.mapweb_layers import forget

    forget()
    assert client.get(f"{base}/footprints").json()["error"]["code"] == "mapweb_failed"
