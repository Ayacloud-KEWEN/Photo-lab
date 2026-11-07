"""Locations and capture times corrected in LUMEN (ADR-035).

Originals stay read-only: a location set here is stored as ``source = 'manual'`` (imports
only update EXIF-sourced locations), and a capture time is corrected by a shift kept in
``media_assets.time_shift_s`` that re-imports apply again. Exports (and photos sent to
MapWeb) write both into the new files.
"""

from __future__ import annotations

import bisect
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from lumen.core.errors import LumenError
from lumen.db.connection import transaction, utc_now
from lumen.geo.places import gazetteer
from lumen.geo.tasks import locate_now
from lumen.library.search import reindex_assets
from lumen.schemas.assets import PlaceName
from lumen.schemas.locations import NearbyLocation, NearbyResult, PlaceMatch

_CHUNK = 500
MAX_SHIFT_S = 400 * 86400


def _chunks(ids: list[int]) -> Iterable[list[int]]:
    unique = list(dict.fromkeys(ids))
    for start in range(0, len(unique), _CHUNK):
        yield unique[start : start + _CHUNK]


# ---------------------------------------------------------------------------- location


def set_location(
    conn: sqlite3.Connection, asset_ids: list[int], latitude: float, longitude: float
) -> int:
    """Put these assets at one place (a manual location, kept over re-imports)."""
    now = utc_now()
    changed = 0
    with transaction(conn):
        for chunk in _chunks(asset_ids):
            existing = [
                int(r[0])
                for r in conn.execute(
                    f"SELECT id FROM media_assets WHERE id IN ({','.join('?' * len(chunk))})",
                    chunk,
                )
            ]
            conn.executemany(
                """
                INSERT INTO media_locations (asset_id, latitude, longitude, altitude_m, source,
                                             updated_at)
                VALUES (?, ?, ?, NULL, 'manual', ?)
                ON CONFLICT (asset_id) DO UPDATE SET
                    latitude = excluded.latitude, longitude = excluded.longitude,
                    altitude_m = NULL, source = 'manual', updated_at = excluded.updated_at
                """,
                [(asset_id, latitude, longitude, now) for asset_id in existing],
            )
            changed += len(existing)
            locate_now(conn, existing)
    return changed


def _exif_location(
    conn: sqlite3.Connection, asset_id: int
) -> tuple[float, float, float | None] | None:
    """The location in the asset's own files (the primary file's first)."""
    for (raw,) in conn.execute(
        """
        SELECT m.raw_json FROM media_files f JOIN media_metadata m ON m.file_id = f.id
        WHERE f.asset_id = ? AND m.raw_json IS NOT NULL
        ORDER BY f.file_role = 'primary' DESC, f.id
        """,
        (asset_id,),
    ):
        try:
            record = json.loads(raw)
            latitude = float(record["Composite:GPSLatitude"])
            longitude = float(record["Composite:GPSLongitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if -90 <= latitude <= 90 and -180 <= longitude <= 180 and (latitude, longitude) != (0, 0):
            try:
                altitude = float(record.get("Composite:GPSAltitude"))
            except (TypeError, ValueError):
                altitude = None
            return latitude, longitude, altitude
    return None


def restore_location(conn: sqlite3.Connection, asset_ids: list[int]) -> int:
    """Back to the location in the photo's file (none if it has none)."""
    now = utc_now()
    changed = 0
    with transaction(conn):
        for chunk in _chunks(asset_ids):
            manual = [
                int(r[0])
                for r in conn.execute(
                    f"SELECT asset_id FROM media_locations WHERE source = 'manual' "
                    f"AND asset_id IN ({','.join('?' * len(chunk))})",
                    chunk,
                )
            ]
            for asset_id in manual:
                found = _exif_location(conn, asset_id)
                if found is None:
                    conn.execute("DELETE FROM media_locations WHERE asset_id = ?", (asset_id,))
                else:
                    conn.execute(
                        "UPDATE media_locations SET latitude = ?, longitude = ?, altitude_m = ?, "
                        "source = 'exif', updated_at = ? WHERE asset_id = ?",
                        (*found, now, asset_id),
                    )
            changed += len(manual)
            locate_now(conn, manual)
    return changed


def _seconds(wall_clock: str) -> float | None:
    try:
        return datetime.fromisoformat(wall_clock).timestamp()
    except ValueError:
        return None


@dataclass(frozen=True, order=True)
class _Located:
    time: float
    asset_id: int
    latitude: float
    longitude: float


def nearby_locations(
    conn: sqlite3.Connection, asset_ids: list[int], max_hours: float, *, apply: bool
) -> NearbyResult:
    """Give each asset the location of the photo taken closest in time (within
    ``max_hours``) that has one: a phone's photos place a camera's taken alongside."""
    targets: list[tuple[int, str]] = []
    for chunk in _chunks(asset_ids):
        targets.extend(
            (int(r[0]), str(r[1]))
            for r in conn.execute(
                f"SELECT id, capture_time FROM media_assets WHERE capture_time IS NOT NULL "
                f"AND id IN ({','.join('?' * len(chunk))})",
                chunk,
            )
        )
    wanted = {asset_id for asset_id, _ in targets}
    located = sorted(
        _Located(time, int(r["asset_id"]), float(r["latitude"]), float(r["longitude"]))
        for r in conn.execute(
            """
            SELECT l.asset_id, l.latitude, l.longitude, a.capture_time
            FROM media_locations l JOIN media_assets a ON a.id = l.asset_id
            WHERE a.capture_time IS NOT NULL
            """
        )
        if int(r["asset_id"]) not in wanted and (time := _seconds(r["capture_time"])) is not None
    )  # fmt: skip
    times = [item.time for item in located]
    window = max_hours * 3600
    found: list[NearbyLocation] = []
    for asset_id, taken in targets:
        moment = _seconds(taken)
        if moment is None:
            continue
        index = bisect.bisect_left(times, moment)
        best = min(
            (located[i] for i in (index - 1, index) if 0 <= i < len(located)),
            key=lambda item: abs(item.time - moment),
            default=None,
        )
        if best is not None and abs(best.time - moment) <= window:
            found.append(
                NearbyLocation(
                    asset_id=asset_id, from_asset_id=best.asset_id,
                    latitude=best.latitude, longitude=best.longitude,
                    gap_s=round(abs(best.time - moment)),
                )
            )  # fmt: skip
    if apply and found:
        now = utc_now()
        with transaction(conn):
            conn.executemany(
                """
                INSERT INTO media_locations (asset_id, latitude, longitude, altitude_m, source,
                                             updated_at)
                VALUES (?, ?, ?, NULL, 'manual', ?)
                ON CONFLICT (asset_id) DO UPDATE SET
                    latitude = excluded.latitude, longitude = excluded.longitude,
                    altitude_m = NULL, source = 'manual', updated_at = excluded.updated_at
                """,
                [(item.asset_id, item.latitude, item.longitude, now) for item in found],
            )
            located_ids = [item.asset_id for item in found]
            for start in range(0, len(located_ids), _CHUNK):
                locate_now(conn, located_ids[start : start + _CHUNK])
    return NearbyResult(
        found=len(found),
        missing=len(set(asset_ids)) - len(found),
        examples=found[:20],
    )


def search_places(query: str, limit: int = 10) -> list[PlaceMatch]:
    return [
        PlaceMatch(
            place_id=place.place_id,
            city=PlaceName(name=place.city.name, zh=place.city.zh, fr=place.city.fr),
            region=PlaceName(name=place.region.name, zh=place.region.zh, fr=place.region.fr)
            if place.region
            else None,
            country=PlaceName(
                name=place.country.name, zh=place.country.zh, fr=place.country.fr
            ),
            latitude=round(latitude, 5),
            longitude=round(longitude, 5),
        )
        for place, latitude, longitude in gazetteer().search(query, limit)
    ]


# -------------------------------------------------------------------------------- time


def shift_time(conn: sqlite3.Connection, asset_ids: list[int], seconds: int) -> int:
    """Move these assets' capture times by ``seconds`` (a camera clock set wrong)."""
    if abs(seconds) > MAX_SHIFT_S:
        raise LumenError("A shift of more than 400 days is not allowed")
    if seconds == 0:
        return 0
    now = utc_now()
    changed = 0
    with transaction(conn):
        for chunk in _chunks(asset_ids):
            marks = ",".join("?" * len(chunk))
            changed += conn.execute(
                f"""
                UPDATE media_assets
                SET capture_time = strftime('%Y-%m-%dT%H:%M:%S', capture_time, ? || ' seconds'),
                    time_shift_s = time_shift_s + ?, updated_at = ?
                WHERE capture_time IS NOT NULL AND id IN ({marks})
                """,
                (seconds, seconds, now, *chunk),
            ).rowcount
            reindex_assets(conn, chunk)
    return changed


def restore_time(conn: sqlite3.Connection, asset_ids: list[int]) -> int:
    """Undo the shifts: back to the time in the photos' files."""
    now = utc_now()
    changed = 0
    with transaction(conn):
        for chunk in _chunks(asset_ids):
            marks = ",".join("?" * len(chunk))
            changed += conn.execute(
                f"""
                UPDATE media_assets
                SET capture_time = strftime('%Y-%m-%dT%H:%M:%S', capture_time,
                                            (-time_shift_s) || ' seconds'),
                    time_shift_s = 0, updated_at = ?
                WHERE time_shift_s != 0 AND id IN ({marks})
                """,
                (now, *chunk),
            ).rowcount
            reindex_assets(conn, chunk)
    return changed


# ------------------------------------------------------------------- for new files


@dataclass(frozen=True)
class Overrides:
    """What an exported copy says differently from the original's metadata."""

    location: tuple[float, float] | None = None
    capture_time: str | None = None  # "YYYY:MM:DD HH:MM:SS"


def overrides_for(conn: sqlite3.Connection, asset_id: int) -> Overrides:
    row = conn.execute(
        """
        SELECT a.capture_time, a.time_shift_s, l.latitude, l.longitude, l.source
        FROM media_assets a LEFT JOIN media_locations l ON l.asset_id = a.id
        WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    if row is None:
        return Overrides()
    location = (
        (float(row["latitude"]), float(row["longitude"])) if row["source"] == "manual" else None
    )
    taken = None
    if row["time_shift_s"] and row["capture_time"]:
        try:
            taken = datetime.fromisoformat(row["capture_time"]).strftime("%Y:%m:%d %H:%M:%S")
        except ValueError:
            taken = None
    return Overrides(location=location, capture_time=taken)

