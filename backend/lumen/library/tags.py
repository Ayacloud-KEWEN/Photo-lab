"""Tag primitives shared by ingestion (keyword import) and the tags API."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from lumen.db.connection import utc_now

MAX_TAG_LENGTH = 100


def normalize_tag_name(name: str) -> str:
    return " ".join(name.split())[:MAX_TAG_LENGTH]


def tag_key(name: str) -> str:
    return normalize_tag_name(name).casefold()


def get_or_create_tag(conn: sqlite3.Connection, name: str) -> int:
    clean = normalize_tag_name(name)
    if not clean:
        raise ValueError("empty tag name")
    row = conn.execute("SELECT id FROM tags WHERE name_key = ?", (tag_key(clean),)).fetchone()
    if row is not None:
        return int(row["id"])
    cursor = conn.execute(
        "INSERT INTO tags (name, name_key, created_at) VALUES (?, ?, ?)",
        (clean, tag_key(clean), utc_now()),
    )
    return int(cursor.lastrowid or 0)


def tag_assets(
    conn: sqlite3.Connection, asset_ids: Iterable[int], tag_id: int, source: str
) -> None:
    now = utc_now()
    conn.executemany(
        "INSERT OR IGNORE INTO media_tags (asset_id, tag_id, source, created_at) "
        "VALUES (?, ?, ?, ?)",
        [(asset_id, tag_id, source, now) for asset_id in asset_ids],
    )
