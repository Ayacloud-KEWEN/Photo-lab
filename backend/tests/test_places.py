"""Offline place names: the bundled gazetteer, the locate task and the API."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen.core.config import Settings
from lumen.geo.places import data_version, gazetteer
from lumen.geo.tasks import GEO_TASK, locate_assets, needs_locating
from lumen.library import trips
from lumen.tasks import queue
from lumen.tasks.runner import TaskContext
from tests.test_develop import NOW, add_photo

PARIS_LOUVRE = (48.8606, 2.3376)
SAINT_MALO = (48.6493, -2.0257)
ROME_COLOSSEUM = (41.8902, 12.4922)


def test_gazetteer_names_towns_in_every_language() -> None:
    louvre, malo, rome, boulogne = gazetteer().locate(
        [PARIS_LOUVRE, SAINT_MALO, ROME_COLOSSEUM, (48.8397, 2.2399)]
    )
    # Paris, not one of its arrondissements ("Paris 01 Louvre" is left out of the data).
    assert (louvre.city.name, louvre.city.zh, louvre.country_code) == ("Paris", "巴黎", "FR")
    assert louvre.region is not None and louvre.region.name == "Île-de-France"
    assert louvre.country.zh == "法国" and louvre.country.fr == "France"
    assert louvre.distance_km < 5
    assert (malo.city.name, malo.region and malo.region.fr) == ("Saint-Malo", "Bretagne")
    assert (rome.city.name, rome.country.fr) == ("Rome", "Italie")
    # A suburb keeps its own name in its centre, next to the big city.
    assert boulogne.city.name == "Boulogne-Billancourt"
    assert data_version().startswith("geonames-")


def run_locate(conn: sqlite3.Connection, settings: Settings) -> object:
    task_id = queue.enqueue(conn, GEO_TASK, unique=False)
    task = queue.claim_next(conn)
    assert task is not None and task["id"] == task_id
    ctx = TaskContext(
        conn=conn, settings=settings, task_id=task_id, kind=GEO_TASK, storage_root_id=None,
        payload={}, stop_event=threading.Event(), enqueue=lambda *a, **k: 0,
    )  # fmt: skip
    return locate_assets(ctx)


def locate(conn: sqlite3.Connection, asset_id: int, point: tuple[float, float], when: str) -> None:
    conn.execute(
        "INSERT INTO media_locations (asset_id, latitude, longitude, source, updated_at) "
        "VALUES (?, ?, ?, 'exif', ?) ON CONFLICT (asset_id) DO UPDATE SET "
        "latitude = excluded.latitude, longitude = excluded.longitude, "
        "updated_at = excluded.updated_at",
        (asset_id, *point, when),
    )


@pytest.fixture
def located(conn: sqlite3.Connection, tmp_path: Path) -> list[int]:
    root = tmp_path / "Photos"
    root.mkdir()
    conn.execute(
        "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, updated_at) "
        "VALUES (1, ?, ?, 'Photos', ?, ?)",
        (str(root), str(root).lower(), NOW, NOW),
    )
    ids = [add_photo(conn, root, f"IMG_000{i}.JPG") for i in range(4)]
    locate(conn, ids[0], PARIS_LOUVRE, NOW)
    locate(conn, ids[1], PARIS_LOUVRE, NOW)
    locate(conn, ids[2], ROME_COLOSSEUM, NOW)
    return ids  # ids[3] has no location


def test_locate_task_names_places_and_follows_changes(
    conn: sqlite3.Connection, settings: Settings, located: list[int]
) -> None:
    assert needs_locating(conn)
    assert run_locate(conn, settings) == {"located": 3}
    assert not needs_locating(conn)
    assert run_locate(conn, settings) == {"located": 0}

    def city(asset_id: int) -> str | None:
        row = conn.execute("SELECT city FROM media_places WHERE asset_id = ?", (asset_id,))
        found = row.fetchone()
        return found[0] if found else None

    assert [city(i) for i in located] == ["Paris", "Paris", "Rome", None]
    # A changed location is located again; a removed one loses its place.
    locate(conn, located[1], SAINT_MALO, "2026-02-01T00:00:00.000Z")
    conn.execute("DELETE FROM media_locations WHERE asset_id = ?", (located[2],))
    assert needs_locating(conn)
    assert run_locate(conn, settings) == {"located": 1}
    assert [city(i) for i in located] == ["Paris", "Saint-Malo", None, None]


def test_place_search_filters_and_facets(
    client: TestClient, conn: sqlite3.Connection, settings: Settings, located: list[int]
) -> None:
    run_locate(conn, settings)

    def ids(**params: object) -> list[int]:
        items = client.get("/api/v1/assets", params={"limit": 50, **params}).json()["items"]
        return sorted(item["id"] for item in items)

    assert ids(q="巴黎") == located[:2]  # Chinese
    assert ids(q="Italie") == [located[2]]  # French country name
    assert ids(q="罗马") == [located[2]]
    assert ids(country="IT") == [located[2]]
    paris = client.get(f"/api/v1/assets/{located[0]}").json()["place"]
    assert (paris["city"]["zh"], paris["country_code"]) == ("巴黎", "FR")
    assert ids(place_id=paris["place_id"]) == located[:2]
    assert client.get(f"/api/v1/assets/{located[3]}").json()["place"] is None
    assert client.get("/api/v1/assets", params={"country": "fr"}).status_code == 422

    places = client.get("/api/v1/assets/facets").json()["places"]
    assert [(c["country_code"], c["count"]) for c in places] == [("FR", 2), ("IT", 1)]
    assert places[0]["name"]["zh"] == "法国"
    assert [(c["name"]["name"], c["count"]) for c in places[0]["cities"]] == [("Paris", 2)]

    points = client.get("/api/v1/map/points").json()
    names = {p["place_id"]: p["name"]["zh"] for p in points["places"]}
    assert sorted(names[p["p"]] for p in points["points"]) == ["巴黎", "巴黎", "罗马市"]


def test_trip_suggestions_carry_place_names(
    client: TestClient,
    conn: sqlite3.Connection,
    settings: Settings,
    located: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_locate(conn, settings)
    monkeypatch.setattr(trips, "MIN_ASSETS", 1)  # two Paris photos make home, Rome is a trip
    [trip] = client.get("/api/v1/collections/suggestions").json()["items"]
    assert trip["asset_ids"] == [located[2]]
    assert [c["name"] for c in trip["cities"]] == ["Rome"]
    assert [c["zh"] for c in trip["countries"]] == ["意大利"]
