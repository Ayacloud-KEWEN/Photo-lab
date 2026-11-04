"""Portfolios: albums and trips. Each is an ordered list of assets with optional captions;
assets stay where they are (a collection only refers to them)."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterable
from datetime import datetime

from lumen.core.errors import LumenError, NotFoundError
from lumen.db.connection import GenerationCache, transaction, utc_now
from lumen.library.trips import Shot, find_trips, spread
from lumen.schemas.assets import PlaceName
from lumen.schemas.collections import (
    Collection,
    CollectionCreate,
    CollectionDetail,
    CollectionItem,
    CollectionUpdate,
    TripSuggestion,
    TripSuggestions,
)
from lumen.services.assets import summaries_by_ids

_CHUNK = 500
MAX_SUGGESTIONS = 20
SAMPLES = 4

_SELECT = """
    SELECT c.*,
           (SELECT COUNT(*) FROM collection_items i WHERE i.collection_id = c.id) AS item_count,
           COALESCE(c.cover_asset_id, (
               SELECT i.asset_id FROM collection_items i WHERE i.collection_id = c.id
               ORDER BY i.position LIMIT 1)) AS cover_id,
           (SELECT MIN(a.capture_time) FROM collection_items i
            JOIN media_assets a ON a.id = i.asset_id WHERE i.collection_id = c.id) AS first_capture,
           (SELECT MAX(a.capture_time) FROM collection_items i
            JOIN media_assets a ON a.id = i.asset_id WHERE i.collection_id = c.id) AS last_capture
    FROM collections c
"""


def _chunks(ids: list[int]) -> Iterable[list[int]]:
    for start in range(0, len(ids), _CHUNK):
        yield ids[start : start + _CHUNK]


def _to_model(row: sqlite3.Row, covers: dict[int, object]) -> Collection:
    cover = covers.get(row["cover_id"]) if row["cover_id"] is not None else None
    return Collection.model_validate(
        {
            **{key: row[key] for key in row.keys() if key in Collection.model_fields},  # noqa: SIM118 - sqlite3.Row
            "cover": cover,
        }
    )


def _covers(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> dict[int, object]:
    ids = [int(row["cover_id"]) for row in rows if row["cover_id"] is not None]
    return {summary.id: summary for summary in summaries_by_ids(conn, ids)}


def list_collections(conn: sqlite3.Connection) -> list[Collection]:
    """Trips by date (newest first), then albums by name."""
    rows = conn.execute(
        f"{_SELECT} ORDER BY c.kind = 'album', COALESCE(c.start_date, '') DESC, c.name"
    ).fetchall()
    covers = _covers(conn, rows)
    return [_to_model(row, covers) for row in rows]


def _row(conn: sqlite3.Connection, collection_id: int) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(f"{_SELECT} WHERE c.id = ?", (collection_id,)).fetchone()
    if row is None:
        raise NotFoundError("Collection not found", details={"id": collection_id})
    return row


def get_collection(conn: sqlite3.Connection, collection_id: int) -> CollectionDetail:
    row = _row(conn, collection_id)
    items = conn.execute(
        "SELECT asset_id, caption FROM collection_items WHERE collection_id = ? "
        "ORDER BY position, added_at",
        (collection_id,),
    ).fetchall()
    summaries = {s.id: s for s in summaries_by_ids(conn, [int(i["asset_id"]) for i in items])}
    collection = _to_model(row, _covers(conn, [row]))
    return CollectionDetail(
        **collection.model_dump(),
        items=[
            CollectionItem(asset=summaries[int(item["asset_id"])], caption=item["caption"])
            for item in items
            if int(item["asset_id"]) in summaries  # not (yet) listable: e.g. missing file
        ],
    )


def create_collection(conn: sqlite3.Connection, body: CollectionCreate) -> CollectionDetail:
    now = utc_now()
    with transaction(conn):
        cursor = conn.execute(
            """
            INSERT INTO collections (uuid, name, kind, description, place, start_date, end_date,
                                     created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()), body.name, body.kind, body.description, body.place,
                _date(body.start_date), _date(body.end_date), now, now,
            ),
        )  # fmt: skip
        collection_id = int(cursor.lastrowid or 0)
        _add(conn, collection_id, body.asset_ids, now)
    return get_collection(conn, collection_id)


def _date(value: object) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def update_collection(
    conn: sqlite3.Connection, collection_id: int, body: CollectionUpdate
) -> CollectionDetail:
    changes = body.model_dump(exclude_unset=True)
    with transaction(conn):
        _row(conn, collection_id)
        if changes.get("name", "") is None or changes.get("kind", "") is None:
            raise LumenError("A collection needs a name and a kind")
        cover = changes.get("cover_asset_id")
        if cover is not None and not _contains(conn, collection_id, cover):
            raise LumenError("The cover must be in the collection", details={"asset_id": cover})
        for key in ("start_date", "end_date"):
            if key in changes:
                changes[key] = _date(changes[key])
        if changes:
            assignments = ", ".join(f"{key} = ?" for key in changes)
            conn.execute(
                f"UPDATE collections SET {assignments}, updated_at = ? WHERE id = ?",
                (*changes.values(), utc_now(), collection_id),
            )
    return get_collection(conn, collection_id)


def delete_collection(conn: sqlite3.Connection, collection_id: int) -> None:
    """Delete the collection; its photos and videos are not touched."""
    with transaction(conn):
        _row(conn, collection_id)
        conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))


def _contains(conn: sqlite3.Connection, collection_id: int, asset_id: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM collection_items WHERE collection_id = ? AND asset_id = ?",
            (collection_id, asset_id),
        ).fetchone()
        is not None
    )


def _add(conn: sqlite3.Connection, collection_id: int, asset_ids: list[int], now: str) -> int:
    ids = list(dict.fromkeys(asset_ids))
    existing: set[int] = set()
    for chunk in _chunks(ids):
        existing.update(
            int(r[0])
            for r in conn.execute(
                f"SELECT id FROM media_assets WHERE id IN ({','.join('?' * len(chunk))})", chunk
            )
        )
    position = conn.execute(
        "SELECT COALESCE(MAX(position) + 1, 0) FROM collection_items WHERE collection_id = ?",
        (collection_id,),
    ).fetchone()[0]
    added = 0
    for asset_id in ids:
        if asset_id not in existing:
            continue
        cursor = conn.execute(
            "INSERT OR IGNORE INTO collection_items (collection_id, asset_id, position, added_at) "
            "VALUES (?, ?, ?, ?)",
            (collection_id, asset_id, position, now),
        )
        if cursor.rowcount:
            added += 1
            position += 1
    if added:
        conn.execute("UPDATE collections SET updated_at = ? WHERE id = ?", (now, collection_id))
    return added


def add_items(conn: sqlite3.Connection, collection_id: int, asset_ids: list[int]) -> int:
    """Append assets (in the order given; ones already in the collection stay put)."""
    with transaction(conn):
        _row(conn, collection_id)
        return _add(conn, collection_id, asset_ids, utc_now())


def remove_items(conn: sqlite3.Connection, collection_id: int, asset_ids: list[int]) -> int:
    with transaction(conn):
        _row(conn, collection_id)
        removed = 0
        for chunk in _chunks(list(dict.fromkeys(asset_ids))):
            removed += conn.execute(
                f"DELETE FROM collection_items WHERE collection_id = ? "
                f"AND asset_id IN ({','.join('?' * len(chunk))})",
                (collection_id, *chunk),
            ).rowcount
        conn.execute(
            "UPDATE collections SET cover_asset_id = NULL, updated_at = ? WHERE id = ? "
            "AND cover_asset_id IS NOT NULL AND cover_asset_id NOT IN "
            "(SELECT asset_id FROM collection_items WHERE collection_id = ?)",
            (utc_now(), collection_id, collection_id),
        )
    return removed


def reorder(conn: sqlite3.Connection, collection_id: int, asset_ids: list[int]) -> int:
    """Put the items in the given order; it must name every item exactly once."""
    with transaction(conn):
        _row(conn, collection_id)
        current = {
            int(r[0])
            for r in conn.execute(
                "SELECT asset_id FROM collection_items WHERE collection_id = ?", (collection_id,)
            )
        }
        if len(asset_ids) != len(current) or set(asset_ids) != current:
            raise LumenError("The new order must list every item of the collection once")
        conn.executemany(
            "UPDATE collection_items SET position = ? WHERE collection_id = ? AND asset_id = ?",
            [(position, collection_id, asset_id) for position, asset_id in enumerate(asset_ids)],
        )
        conn.execute(
            "UPDATE collections SET updated_at = ? WHERE id = ?", (utc_now(), collection_id)
        )
    return len(asset_ids)


def set_caption(
    conn: sqlite3.Connection, collection_id: int, asset_id: int, caption: str | None
) -> None:
    text = caption.strip() if caption else None
    with transaction(conn):
        updated = conn.execute(
            "UPDATE collection_items SET caption = ? WHERE collection_id = ? AND asset_id = ?",
            (text or None, collection_id, asset_id),
        ).rowcount
        if not updated:
            raise NotFoundError(
                "Item not found", details={"collection_id": collection_id, "asset_id": asset_id}
            )


_cache = GenerationCache(size=1)


def suggest_trips(conn: sqlite3.Connection) -> TripSuggestions:
    return _cache.get("trips", lambda: _suggest_trips(conn))


def _suggest_trips(conn: sqlite3.Connection) -> TripSuggestions:
    """Trips found in the library that no trip collection covers yet."""
    rows = conn.execute(
        """
        SELECT a.id, a.capture_time, l.latitude, l.longitude
        FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
             AND c.ingest_state = 'done' AND c.status = 'present'
        LEFT JOIN media_locations l ON l.asset_id = a.id
        WHERE a.capture_time IS NOT NULL AND a.cull_flag != 'reject'
        ORDER BY a.capture_time, a.id
        """
    ).fetchall()
    shots = []
    for row in rows:
        try:
            taken = datetime.fromisoformat(row["capture_time"])
        except ValueError:
            continue
        shots.append(
            Shot(int(row["id"]), taken.replace(tzinfo=None), row["latitude"], row["longitude"])
        )

    covered = [
        (r["start_date"], r["end_date"])
        for r in conn.execute(
            "SELECT start_date, end_date FROM collections "
            "WHERE kind = 'trip' AND start_date IS NOT NULL AND end_date IS NOT NULL"
        )
    ]
    suggestions: list[TripSuggestion] = []
    for trip in reversed(find_trips(shots)):
        start, end = trip.start.date().isoformat(), trip.end.date().isoformat()
        if any(start <= until and since <= end for since, until in covered):
            continue
        ids = [shot.asset_id for shot in trip.shots]
        cities, countries = _trip_places(conn, ids)
        suggestions.append(
            TripSuggestion(
                start_date=start,
                end_date=end,
                asset_count=len(ids),
                asset_ids=ids,
                samples=summaries_by_ids(conn, spread(ids, SAMPLES)),
                latitude=round(trip.latitude, 5),
                longitude=round(trip.longitude, 5),
                distance_km=round(trip.distance_km, 1),
                cities=cities,
                countries=countries,
            )
        )
        if len(suggestions) >= MAX_SUGGESTIONS:
            break
    return TripSuggestions(items=suggestions)


def _trip_places(
    conn: sqlite3.Connection, ids: list[int]
) -> tuple[list[PlaceName], list[PlaceName]]:
    """The trip's most photographed towns (up to 3) and its countries."""
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""
        SELECT place_id, city, city_zh, city_fr, country_code, country, country_zh, country_fr,
               COUNT(*) AS count
        FROM media_places WHERE asset_id IN ({marks})
        GROUP BY place_id ORDER BY count DESC, city
        """,
        ids,
    ).fetchall()
    cities = [PlaceName(name=r["city"], zh=r["city_zh"], fr=r["city_fr"]) for r in rows[:3]]
    totals: dict[str, int] = {}
    names: dict[str, PlaceName] = {}
    for r in rows:
        totals[r["country_code"]] = totals.get(r["country_code"], 0) + r["count"]
        names[r["country_code"]] = PlaceName(
            name=r["country"], zh=r["country_zh"], fr=r["country_fr"]
        )
    countries = [names[code] for code in sorted(totals, key=lambda code: -totals[code])]
    return cities, countries
