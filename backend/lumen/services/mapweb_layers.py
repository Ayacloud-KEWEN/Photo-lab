"""What MapWeb (Periplus) holds, shown as layers on LUMEN's map: footprints, tracks and
plans, read through the backend (the web view cannot reach MapWeb itself: no CORS, and
often plain http), kept a couple of minutes.

Read only, except sending photos to a footprint the user picked. When MapWeb cannot be
reached the layers are simply unavailable; LUMEN's own map works as before.
"""

from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from lumen.core.errors import LumenError, NotFoundError
from lumen.schemas.mapweb import (
    FootprintPhotos,
    LayerFootprint,
    LayerPlan,
    LayerPlanDay,
    LayerPlanStop,
    LayerPlanSummary,
    LayerTrack,
)
from lumen.services import mapweb
from lumen.services.assets import summaries_by_ids

CACHE_S = 120
MAX_THUMB_BYTES = 2 * 1024 * 1024
THUMB_PATH = re.compile(r"^/thumbs/[\w\-./]+\.(?:jpe?g|png|webp|gif)$", re.IGNORECASE)
# A stop "has photos" when one was taken that day within this distance.
STOP_KM = 3.0

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _get(conn: sqlite3.Connection, path: str) -> Any:
    client = mapweb.client_for(conn)
    key = f"{client.base_url}{path}"
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_S:
        return cached[1]
    answer = client._request("GET", path)
    with _cache_lock:
        _cache[key] = (now, answer)
    return answer


def forget() -> None:
    """After sending: the footprints changed."""
    with _cache_lock:
        _cache.clear()


# --- Footprints -----------------------------------------------------------------------------


def footprints(conn: sqlite3.Connection) -> list[LayerFootprint]:
    return [
        LayerFootprint(
            id=int(pin["id"]),
            title=str(pin.get("title") or ""),
            description=str(pin.get("description") or "")[:500],
            emoji=str(pin.get("emoji") or "📍"),
            lat=float(pin["lat"]),
            lng=float(pin["lng"]),
            visited_at=pin.get("visited_at"),
            photo_count=len(pin.get("photos") or []),
            thumb=pin.get("thumb_url"),
            plan_id=pin.get("plan_id"),
        )
        for pin in _get(conn, "/api/points")
        if pin.get("lat") is not None and pin.get("lng") is not None
    ]


def _pin(conn: sqlite3.Connection, point_id: int) -> dict[str, Any]:
    for pin in _get(conn, "/api/points"):
        if int(pin["id"]) == point_id:
            return dict(pin)
    raise NotFoundError("Footprint not found", details={"id": point_id})


def _belongs(photo: mapweb.Photo, lat: float, lng: float, at: float | None) -> bool:
    """MapWeb's own rule for a photo joining an existing footprint (see mapweb.py)."""
    if photo.located and at is not None and photo.time is not None:
        km = mapweb.distance_km(photo.lat or 0, photo.lng or 0, lat, lng)
        hours = abs(photo.time - at) / mapweb.HOUR_S
        return (km <= mapweb.ATTACH_KM and hours <= mapweb.ATTACH_HOURS) or (
            km <= mapweb.SAME_SPOT_KM and mapweb._same_day(photo.time, at)
        )
    if not photo.located and at is not None and photo.time is not None:
        return abs(photo.time - at) <= mapweb.HOUR_S  # no location: within an hour
    return False


def footprint_photos(conn: sqlite3.Connection, point_id: int, language: str) -> FootprintPhotos:
    """LUMEN's photos that belong to this footprint, as MapWeb's import would place them."""
    pin = _pin(conn, point_id)
    lat, lng = float(pin["lat"]), float(pin["lng"])
    at = mapweb._pin_time(pin)
    # Candidates: near it, or (no location) taken within a day of it; then the exact rule.
    dlat = mapweb.ATTACH_KM / 111.0
    dlng = dlat / max(math.cos(math.radians(lat)), 0.01)
    ids = [
        int(r[0])
        for r in conn.execute(
            """
            SELECT a.id FROM media_assets a
            LEFT JOIN media_locations l ON l.asset_id = a.id
            WHERE a.media_type = 'photo' AND a.capture_time IS NOT NULL
              AND ((l.latitude BETWEEN ? AND ? AND l.longitude BETWEEN ? AND ?)
                   OR (l.asset_id IS NULL AND ? IS NOT NULL
                       AND a.capture_time BETWEEN date(?, '-1 day') AND date(?, '+2 day')))
            """,
            (
                lat - dlat, lat + dlat, lng - dlng, lng + dlng,
                pin.get("visited_at"), pin.get("visited_at"), pin.get("visited_at"),
            ),
        )
    ]  # fmt: skip
    photos = [p for p in mapweb.collect(conn, ids, language).photos if _belongs(p, lat, lng, at)]
    on_map = {
        int(r[0]): int(r[1]) for r in conn.execute("SELECT asset_id, point_id FROM mapweb_photos")
    }
    order = [p.asset_id for p in photos]
    found = {s.id: s for s in summaries_by_ids(conn, order)}
    items = [found[i] for i in order if i in found]
    return FootprintPhotos(
        point_id=point_id,
        items=items,
        here=[s.id for s in items if on_map.get(s.id) == point_id],
        elsewhere=[s.id for s in items if s.id in on_map and on_map[s.id] != point_id],
    )


# --- Tracks ---------------------------------------------------------------------------------


def tracks(conn: sqlite3.Connection) -> list[LayerTrack]:
    return [
        LayerTrack(
            id=int(track["id"]),
            name=str(track.get("name") or ""),
            sport=str(track.get("sport") or "other"),
            started_at=track.get("started_at"),
            ended_at=track.get("ended_at"),
            distance_m=float(track.get("distance_m") or 0),
            ascent_m=float(track.get("ascent_m") or 0),
            geometry=track["geometry"],
        )
        for track in _get(conn, "/api/tracks")
        if isinstance(track.get("geometry"), dict)
    ]


# --- Plans ----------------------------------------------------------------------------------


def plans(conn: sqlite3.Connection) -> list[LayerPlanSummary]:
    return [
        LayerPlanSummary(
            id=int(plan["id"]),
            title=str(plan.get("title") or ""),
            start_date=plan.get("start_date"),
            end_date=plan.get("end_date"),
        )
        for plan in _get(conn, "/api/plans")
    ]


def plan(conn: sqlite3.Connection, plan_id: int) -> LayerPlan:
    detail = _get(conn, f"/api/plans/{plan_id}")
    days = []
    for number, day in enumerate(detail.get("days") or [], start=1):
        date = day.get("day_date")
        stops = []
        for stop in day.get("stops") or []:
            if stop.get("lat") is None or stop.get("lng") is None:
                continue
            ids = _photos_near(conn, float(stop["lat"]), float(stop["lng"]), date)
            stops.append(
                LayerPlanStop(
                    name=str(stop.get("name") or ""),
                    lat=float(stop["lat"]),
                    lng=float(stop["lng"]),
                    asset_ids=ids,
                )
            )
        days.append(
            LayerPlanDay(number=number, date=date, title=str(day.get("title") or ""), stops=stops)
        )
    return LayerPlan(id=int(detail["id"]), title=str(detail.get("title") or ""), days=days)


def _photos_near(conn: sqlite3.Connection, lat: float, lng: float, date: str | None) -> list[int]:
    """Photos taken that day within STOP_KM of a stop (none without a date)."""
    if not date:
        return []
    dlat = STOP_KM / 111.0
    dlng = dlat / max(math.cos(math.radians(lat)), 0.01)
    rows = conn.execute(
        """
        SELECT a.id, l.latitude, l.longitude FROM media_assets a
        JOIN media_locations l ON l.asset_id = a.id
        WHERE substr(a.capture_time, 1, 10) = ? AND a.cull_flag != 'reject'
          AND l.latitude BETWEEN ? AND ? AND l.longitude BETWEEN ? AND ?
        ORDER BY a.capture_time
        """,
        (date[:10], lat - dlat, lat + dlat, lng - dlng, lng + dlng),
    ).fetchall()
    return [
        int(r["id"])
        for r in rows
        if mapweb.distance_km(lat, lng, r["latitude"], r["longitude"]) <= STOP_KM
    ]


# --- Thumbnails -----------------------------------------------------------------------------


def thumbnail(conn: sqlite3.Connection, path: str) -> tuple[bytes, str]:
    """A footprint's thumbnail from MapWeb (only its /thumbs/ files)."""
    if not THUMB_PATH.match(path) or ".." in path:
        raise LumenError("Not a MapWeb thumbnail")
    client = mapweb.client_for(conn)
    request = urllib.request.Request(f"{client.base_url}{path}")
    try:
        with urllib.request.urlopen(request, timeout=mapweb.TIMEOUT_S) as response:
            data = response.read(MAX_THUMB_BYTES + 1)
            kind = response.headers.get_content_type()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise mapweb.MapWebError(
            "MapWeb cannot be reached", details={"url": client.base_url, "reason": str(exc)}
        ) from exc
    if len(data) > MAX_THUMB_BYTES or not kind.startswith("image/"):
        raise LumenError("Not a MapWeb thumbnail")
    return data, kind
