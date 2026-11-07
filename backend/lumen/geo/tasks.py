"""Background task: name the place of every located asset (``media_places``)."""

from __future__ import annotations

import sqlite3

from lumen.db.connection import transaction, utc_now
from lumen.geo.places import data_version, gazetteer
from lumen.library.search import reindex_assets
from lumen.tasks.runner import TaskContext

GEO_TASK = "geo_locate_assets"
BATCH_SIZE = 500

# Located assets without a place, or whose place is from other data or an older location.
_PENDING = """
    FROM media_locations l LEFT JOIN media_places p ON p.asset_id = l.asset_id
    WHERE p.asset_id IS NULL OR p.data_version != ? OR p.located_at != l.updated_at
"""
_ORPHANS = (
    "SELECT asset_id FROM media_places "
    "WHERE asset_id NOT IN (SELECT asset_id FROM media_locations)"
)


def needs_locating(conn: sqlite3.Connection) -> bool:
    version = data_version()
    pending = conn.execute(f"SELECT EXISTS (SELECT 1 {_PENDING})", (version,)).fetchone()[0]
    orphans = conn.execute(f"SELECT EXISTS ({_ORPHANS})").fetchone()[0]
    return bool(pending or orphans)


def locate_assets(ctx: TaskContext) -> dict[str, int]:
    conn = ctx.conn
    version = data_version()
    with transaction(conn):
        orphans = [row[0] for row in conn.execute(_ORPHANS)]
        if orphans:
            marks = ",".join("?" * len(orphans))
            conn.execute(f"DELETE FROM media_places WHERE asset_id IN ({marks})", orphans)
            reindex_assets(conn, orphans)

    total = conn.execute(f"SELECT COUNT(*) {_PENDING}", (version,)).fetchone()[0]
    done = 0
    while True:
        ctx.check()
        rows = conn.execute(
            f"SELECT l.asset_id, l.latitude, l.longitude, l.updated_at {_PENDING} "
            "ORDER BY l.asset_id LIMIT ?",
            (version, BATCH_SIZE),
        ).fetchall()
        if not rows:
            break
        with transaction(conn):
            _write_places(conn, rows, version)
        done += len(rows)
        ctx.progress(done, max(total, done))
    return {"located": done}


def _write_places(conn: sqlite3.Connection, rows: list[sqlite3.Row], version: str) -> None:
    """Name the place of each (asset_id, latitude, longitude, updated_at) row. Call inside
    a transaction."""
    places = gazetteer().locate([(row["latitude"], row["longitude"]) for row in rows])
    now = utc_now()
    for row, place in zip(rows, places, strict=True):
        region = place.region
        conn.execute(
            """
            INSERT INTO media_places (
                asset_id, place_id, city, city_zh, city_fr, region, region_zh,
                region_fr, country_code, country, country_zh, country_fr, distance_km,
                data_version, located_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (asset_id) DO UPDATE SET
                place_id = excluded.place_id, city = excluded.city,
                city_zh = excluded.city_zh, city_fr = excluded.city_fr,
                region = excluded.region, region_zh = excluded.region_zh,
                region_fr = excluded.region_fr, country_code = excluded.country_code,
                country = excluded.country, country_zh = excluded.country_zh,
                country_fr = excluded.country_fr, distance_km = excluded.distance_km,
                data_version = excluded.data_version, located_at = excluded.located_at,
                updated_at = excluded.updated_at
            """,
            (
                row["asset_id"], place.place_id,
                place.city.name, place.city.zh, place.city.fr,
                region.name if region else None, region.zh if region else None,
                region.fr if region else None,
                place.country_code, place.country.name, place.country.zh,
                place.country.fr, place.distance_km, version, row["updated_at"], now,
            ),
        )  # fmt: skip
    reindex_assets(conn, [row["asset_id"] for row in rows])


def locate_now(conn: sqlite3.Connection, asset_ids: list[int]) -> None:
    """Name the places of these assets at once (after the user set their location), and
    drop the place of any that no longer has a location. Call inside a transaction."""
    version = data_version()
    for start in range(0, len(asset_ids), BATCH_SIZE):
        chunk = asset_ids[start : start + BATCH_SIZE]
        marks = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"""
            SELECT l.asset_id, l.latitude, l.longitude, l.updated_at
            FROM media_locations l LEFT JOIN media_places p ON p.asset_id = l.asset_id
            WHERE l.asset_id IN ({marks})
              AND (p.asset_id IS NULL OR p.data_version != ? OR p.located_at != l.updated_at)
            """,
            (*chunk, version),
        ).fetchall()
        if rows:
            _write_places(conn, rows, version)
        gone = conn.execute(
            f"DELETE FROM media_places WHERE asset_id IN ({marks}) "
            "AND asset_id NOT IN (SELECT asset_id FROM media_locations) RETURNING asset_id",
            chunk,
        ).fetchall()
        if gone:
            reindex_assets(conn, [row[0] for row in gone])
