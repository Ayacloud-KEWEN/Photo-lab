"""A portfolio's travel diary: its items by capture day, with the user's text between them."""

from __future__ import annotations

import sqlite3

from lumen.core.errors import LumenError, NotFoundError
from lumen.db.connection import transaction, utc_now
from lumen.schemas.assets import PlaceName
from lumen.schemas.collections import Diary, DiaryDay, DiaryNote, DiaryWrite


def _collection(conn: sqlite3.Connection, collection_id: int) -> None:
    if conn.execute("SELECT 1 FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
        raise NotFoundError("Collection not found", details={"id": collection_id})


def get_diary(conn: sqlite3.Connection, collection_id: int) -> Diary:
    _collection(conn, collection_id)
    rows = conn.execute(
        """
        SELECT a.id, a.capture_time, p.city, p.city_zh, p.city_fr
        FROM collection_items i
        JOIN media_assets a ON a.id = i.asset_id
        LEFT JOIN media_places p ON p.asset_id = a.id
        WHERE i.collection_id = ?
        ORDER BY a.capture_time IS NULL, a.capture_time, i.position
        """,
        (collection_id,),
    ).fetchall()
    texts: dict[tuple[str, int | None], str] = {
        (r["day"], r["after_asset_id"]): r["text"]
        for r in conn.execute(
            "SELECT day, after_asset_id, text FROM collection_diary WHERE collection_id = ?",
            (collection_id,),
        )
    }
    days: dict[str, DiaryDay] = {}
    for row in rows:
        date = (row["capture_time"] or "")[:10]
        day = days.get(date)
        if day is None:
            day = days[date] = DiaryDay(
                number=len(days) + 1, date=date, places=[], asset_ids=[],
                intro=texts.get((date, None)), notes=[],
            )  # fmt: skip
        asset_id = int(row["id"])
        day.asset_ids.append(asset_id)
        if row["city"] and all(place.name != row["city"] for place in day.places):
            day.places.append(PlaceName(name=row["city"], zh=row["city_zh"], fr=row["city_fr"]))
        if (date, asset_id) in texts:
            day.notes.append(DiaryNote(after_asset_id=asset_id, text=texts[(date, asset_id)]))
    return Diary(days=list(days.values()))


def write(conn: sqlite3.Connection, collection_id: int, body: DiaryWrite) -> None:
    """Set (or, with empty text, remove) a day's opening text or the text after a photo."""
    with transaction(conn):
        _collection(conn, collection_id)
        if body.after_asset_id is not None and (
            conn.execute(
                "SELECT 1 FROM collection_items WHERE collection_id = ? AND asset_id = ?",
                (collection_id, body.after_asset_id),
            ).fetchone()
            is None
        ):
            raise LumenError("The photo is not in the portfolio")
        conn.execute(
            "DELETE FROM collection_diary WHERE collection_id = ? AND day = ? "
            "AND after_asset_id IS ?",
            (collection_id, body.day, body.after_asset_id),
        )
        text = body.text.strip()
        if text:
            conn.execute(
                "INSERT INTO collection_diary (collection_id, day, after_asset_id, text, "
                "updated_at) VALUES (?, ?, ?, ?, ?)",
                (collection_id, body.day, body.after_asset_id, text, utc_now()),
            )


def import_story_notes(conn: sqlite3.Connection, collection_id: int, analysis_id: int) -> int:
    """Day notes of a travel story become the opening texts of days that have none."""
    from lumen.vlm.story import notes_of

    _collection(conn, collection_id)
    filled = 0
    with transaction(conn):
        for day in notes_of(conn, collection_id, analysis_id):
            if not day.text:
                continue
            exists = conn.execute(
                "SELECT 1 FROM collection_diary WHERE collection_id = ? AND day = ? "
                "AND after_asset_id IS NULL",
                (collection_id, day.date),
            ).fetchone()
            if exists is None:
                conn.execute(
                    "INSERT INTO collection_diary (collection_id, day, after_asset_id, text, "
                    "updated_at) VALUES (?, ?, NULL, ?, ?)",
                    (collection_id, day.date, day.text, utc_now()),
                )
                filled += 1
    return filled
