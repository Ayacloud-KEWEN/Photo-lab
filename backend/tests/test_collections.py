"""Portfolios (albums and trips) and trip suggestions."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen.core.config import Settings
from lumen.db.connection import Database
from lumen.library import trips
from lumen.library.live import pair_live_photo
from lumen.library.route import RoutePoint, find_stops, route_km
from lumen.library.trips import Shot, distance_km, find_trips, spread
from tests.test_develop import NOW, add_photo
from tests.test_live import SAME_ID, add, asset_of

PARIS = (48.8566, 2.3522)
ZERMATT = (46.0207, 7.7491)


def shots(start: datetime, count: int, place: tuple[float, float] | None, hours: float = 6):
    return [
        Shot(
            int(start.timestamp()) + i, start + timedelta(hours=i * hours), *(place or (None, None))
        )
        for i in range(count)
    ]


# --- Trip finding ---------------------------------------------------------------------------


def test_trips_are_runs_of_photos_far_from_home() -> None:
    day = datetime(2025, 1, 1, 9)
    library = (
        shots(day, 20, PARIS)
        + shots(day + timedelta(days=10), 4, ZERMATT)
        + shots(day + timedelta(days=11), 2, None)  # no location, in the middle of the trip
        + shots(day + timedelta(days=11, hours=13), 3, ZERMATT)
        + shots(day + timedelta(days=12, hours=6), 2, None)  # unknown at the end: left out
        + shots(day + timedelta(days=13), 3, PARIS)
        + shots(day + timedelta(days=30), 3, ZERMATT)  # too few photos
    )
    [trip] = find_trips(sorted(library, key=lambda s: s.taken))
    assert len(trip.shots) == 9
    assert trip.start == day + timedelta(days=10)
    assert all(s.latitude is not None for s in trip.shots[-3:])
    assert abs(trip.latitude - ZERMATT[0]) < 0.01
    assert 450 < trip.distance_km < 550


def test_long_gaps_split_trips_and_unlocated_libraries_have_none() -> None:
    day = datetime(2025, 1, 1, 9)
    library = shots(day, 10, PARIS) + shots(day + timedelta(days=5), 5, ZERMATT)
    library += shots(day + timedelta(days=9), 5, ZERMATT)  # three days later
    assert len(find_trips(sorted(library, key=lambda s: s.taken))) == 2
    assert find_trips(shots(day, 10, None)) == []


def test_helpers() -> None:
    assert distance_km(*PARIS, *PARIS) == 0
    assert 500 < distance_km(*PARIS, *ZERMATT) < 530  # about 514 km
    assert spread(list(range(10)), 4) == [0, 3, 6, 9]
    assert spread([1, 2], 4) == [1, 2]


def test_stops_group_photos_taken_close_together() -> None:
    day = datetime(2025, 1, 1, 9)
    near_paris = (PARIS[0] + 0.004, PARIS[1])  # ~450 m away
    points = [
        RoutePoint(1, day, *PARIS),
        RoutePoint(2, day + timedelta(hours=1), *near_paris),
        RoutePoint(3, day + timedelta(days=1), *ZERMATT),
        RoutePoint(4, day + timedelta(days=2), *PARIS),  # back again: a new stop
    ]
    stops = find_stops(points)
    assert [[p.asset_id for p in stop.points] for stop in stops] == [[1, 2], [3], [4]]
    assert abs(stops[0].latitude - (PARIS[0] + 0.002)) < 1e-9
    assert (stops[0].start, stops[0].end) == (day, day + timedelta(hours=1))
    assert 1000 < route_km(stops) < 1060
    assert find_stops([]) == [] and route_km([]) == 0

    # Photos of one town are one stop, however far apart within it.
    paris, versailles = 2988507, 2969679
    walk = [
        RoutePoint(1, day, *PARIS, paris),
        RoutePoint(2, day + timedelta(hours=1), PARIS[0] + 0.05, PARIS[1], paris),  # 5.5 km
        RoutePoint(3, day + timedelta(hours=2), PARIS[0] - 0.05, PARIS[1], versailles),
        RoutePoint(4, day + timedelta(hours=3), PARIS[0] + 0.1, PARIS[1]),  # unnamed
    ]
    assert [[p.asset_id for p in stop.points] for stop in find_stops(walk)] == [[1, 2], [3], [4]]


# --- API ------------------------------------------------------------------------------------


@pytest.fixture
def library(client: TestClient, settings: Settings, tmp_path: Path) -> tuple[TestClient, list[int]]:
    """The API with five photos taken a day apart; the last three far from home."""
    root = tmp_path / "Photos"
    root.mkdir()
    ids = []
    with Database(settings.database_path).session() as conn:
        conn.execute(
            "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, "
            "updated_at) VALUES (1, ?, ?, 'Photos', ?, ?)",
            (str(root), str(root).lower(), NOW, NOW),
        )
        for index in range(5):
            asset_id = add_photo(conn, root, f"IMG_000{index}.JPG")
            conn.execute(
                "UPDATE media_assets SET capture_time = ? WHERE id = ?",
                (f"2025-03-0{index + 1}T10:00:00", asset_id),
            )
            ids.append(asset_id)
    return client, ids


def test_collection_lifecycle(library: tuple[TestClient, list[int]]) -> None:
    client, ids = library
    created = client.post(
        "/api/v1/collections",
        json={"name": "  Alps  ", "kind": "trip", "place": "Zermatt", "start_date": "2025-03-03",
              "end_date": "2025-03-05", "asset_ids": [ids[2], ids[3], ids[2], 999]},
    )  # fmt: skip
    assert created.status_code == 201
    detail = created.json()
    collection = detail["id"]
    assert detail["name"] == "Alps" and detail["place"] == "Zermatt"
    assert [item["asset"]["id"] for item in detail["items"]] == [ids[2], ids[3]]
    assert detail["cover"]["id"] == ids[2]  # the first item until one is chosen
    assert detail["cover_asset_id"] is None

    added = client.post(
        f"/api/v1/collections/{collection}/items", json={"asset_ids": [ids[4], ids[2]]}
    )
    assert added.json() == {"changed": 1}
    order = [ids[4], ids[2], ids[3]]
    reordered = client.put(f"/api/v1/collections/{collection}/order", json={"asset_ids": order})
    assert reordered.status_code == 200
    bad_order = client.put(f"/api/v1/collections/{collection}/order", json={"asset_ids": order[:2]})
    assert bad_order.status_code == 400

    caption = client.patch(
        f"/api/v1/collections/{collection}/items/{ids[2]}", json={"caption": " 雪 "}
    )
    assert caption.status_code == 204
    covered = client.patch(f"/api/v1/collections/{collection}", json={"cover_asset_id": ids[3]})
    assert covered.json()["cover"]["id"] == covered.json()["cover_asset_id"] == ids[3]
    outside = client.patch(f"/api/v1/collections/{collection}", json={"cover_asset_id": ids[0]})
    assert outside.status_code == 400
    backwards = client.patch(
        f"/api/v1/collections/{collection}",
        json={"start_date": "2025-03-09", "end_date": "2025-03-01"},
    )
    assert backwards.status_code == 422

    detail = client.get(f"/api/v1/collections/{collection}").json()
    assert [item["asset"]["id"] for item in detail["items"]] == order
    assert [item["caption"] for item in detail["items"]] == [None, "雪", None]
    assert (detail["first_capture"], detail["last_capture"]) == (
        "2025-03-03T10:00:00", "2025-03-05T10:00:00",
    )  # fmt: skip

    removed = client.post(
        f"/api/v1/collections/{collection}/items/remove", json={"asset_ids": [ids[3]]}
    )
    assert removed.json() == {"changed": 1}
    after = client.get(f"/api/v1/collections/{collection}").json()
    assert after["cover"]["id"] == ids[4]  # the chosen cover left: back to the first item

    client.post("/api/v1/collections", json={"name": "Best of"})
    listed = client.get("/api/v1/collections").json()["items"]
    assert [(c["name"], c["item_count"]) for c in listed] == [("Alps", 2), ("Best of", 0)]

    assert client.delete(f"/api/v1/collections/{collection}").status_code == 204
    assert client.get(f"/api/v1/collections/{collection}").status_code == 404
    assert client.get(f"/api/v1/assets/{ids[4]}").status_code == 200  # photos stay


def test_trip_suggestions_skip_trips_already_made(
    library: tuple[TestClient, list[int]], settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, ids = library
    with Database(settings.database_path).session() as conn:
        for index, asset_id in enumerate(ids):
            place = PARIS if index < 3 else ZERMATT
            conn.execute(
                "INSERT INTO media_locations (asset_id, latitude, longitude, source, updated_at) "
                "VALUES (?, ?, ?, 'exif', ?)",
                (asset_id, *place, NOW),
            )
    # Three Paris photos make it home; two Alps photos are a trip (with a lower minimum).
    monkeypatch.setattr(trips, "MIN_ASSETS", 2)
    [suggestion] = client.get("/api/v1/collections/suggestions").json()["items"]
    assert suggestion["asset_ids"] == ids[3:]
    assert (suggestion["start_date"], suggestion["end_date"]) == ("2025-03-04", "2025-03-05")
    assert len(suggestion["samples"]) == 2

    client.post(
        "/api/v1/collections",
        json={"name": "Alps", "kind": "trip", "start_date": "2025-03-04", "end_date": "2025-03-04"},
    )
    assert client.get("/api/v1/collections/suggestions").json()["items"] == []


def test_live_photo_pairing_keeps_portfolio_membership(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, updated_at) "
        "VALUES (1, 'D:\\\\Phone', 'd:\\\\phone', 'Phone', ?, ?)",
        (NOW, NOW),
    )
    clip = add(conn, "IMG_0007.MOV", content_id=SAME_ID, duration_ms=2000)
    video_asset = asset_of(conn, clip)
    conn.execute(
        "INSERT INTO collections (id, uuid, name, created_at, updated_at) "
        "VALUES (1, 'u', 'Trip', ?, ?)",
        (NOW, NOW),
    )
    conn.execute(
        "INSERT INTO collection_items (collection_id, asset_id, position, caption, added_at) "
        "VALUES (1, ?, 3, 'boat', ?)",
        (video_asset, NOW),
    )
    still = add(conn, "IMG_0007.HEIC", content_id=SAME_ID)
    assert pair_live_photo(conn, still, NOW)
    rows = conn.execute("SELECT asset_id, position, caption FROM collection_items").fetchall()
    assert [tuple(r) for r in rows] == [(asset_of(conn, still), 3, "boat")]


def test_collection_route(library: tuple[TestClient, list[int]], settings: Settings) -> None:
    client, ids = library
    places = {ids[0]: PARIS, ids[1]: (PARIS[0] + 0.003, PARIS[1]), ids[3]: ZERMATT, ids[4]: ZERMATT}
    with Database(settings.database_path).session() as conn:
        for asset_id, place in places.items():
            conn.execute(
                "INSERT INTO media_locations (asset_id, latitude, longitude, source, updated_at) "
                "VALUES (?, ?, ?, 'exif', ?)",
                (asset_id, *place, NOW),
            )
        for asset_id in ids[:2]:
            conn.execute(
                "INSERT INTO media_places (asset_id, place_id, city, city_zh, city_fr, "
                "country_code, country, country_zh, country_fr, distance_km, data_version, "
                "located_at, updated_at) VALUES (?, 2988507, 'Paris', '巴黎', 'Paris', 'FR', "
                "'France', '法国', 'France', 1, 'v', ?, ?)",
                (asset_id, NOW, NOW),
            )
        conn.execute("UPDATE media_assets SET rating = 5 WHERE id = ?", (ids[4],))
    collection = client.post(
        "/api/v1/collections", json={"name": "Spring", "asset_ids": [ids[4], *ids[:4]]}
    ).json()["id"]

    route = client.get(f"/api/v1/collections/{collection}/route").json()
    assert [point["id"] for point in route["points"]] == [ids[0], ids[1], ids[3], ids[4]]
    assert route["unlocated"] == 1
    paris, alps = route["stops"]
    assert paris["asset_ids"] == ids[:2] and paris["day"] == 1
    assert paris["place"]["zh"] == "巴黎" and paris["cover"]["id"] == ids[0]
    assert alps["asset_ids"] == ids[3:] and alps["day"] == 4 and alps["place"] is None
    assert alps["cover"]["id"] == ids[4]  # the best rated photo
    assert route["days"] == 5
    assert 500 < route["distance_km"] < 530
    assert [place["name"]["name"] for place in route["places"]] == ["Paris"]

    empty = client.post("/api/v1/collections", json={"name": "Empty"}).json()["id"]
    assert client.get(f"/api/v1/collections/{empty}/route").json() == {
        "points": [], "places": [], "stops": [], "distance_km": 0, "days": 0, "unlocated": 0,
    }  # fmt: skip
    assert client.get("/api/v1/collections/999/route").status_code == 404
