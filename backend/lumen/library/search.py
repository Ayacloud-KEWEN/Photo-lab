"""Full-text search index maintenance (see migration 0003, view ``asset_search_source``)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

_CHUNK = 500


def reindex_assets(conn: sqlite3.Connection, asset_ids: Iterable[int]) -> None:
    """Rebuild the search documents of the given assets (call inside a transaction)."""
    ids = sorted(set(asset_ids))
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start : start + _CHUNK]
        marks = ",".join("?" * len(chunk))
        conn.execute(f"DELETE FROM asset_search WHERE rowid IN ({marks})", chunk)
        conn.execute(
            f"INSERT INTO asset_search (rowid, body) "
            f"SELECT asset_id, body FROM asset_search_source WHERE asset_id IN ({marks})",
            chunk,
        )


def search_terms(query: str) -> list[str]:
    """Split a user query into terms; every term must match (as a substring)."""
    return [term for term in query.split() if term][:10]


def like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
