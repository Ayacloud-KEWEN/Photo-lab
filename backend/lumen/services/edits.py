"""User edits: ratings, favorites, notes and tags. Stored in the database only;
original files and sidecars are never written."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from lumen.core.errors import ConflictError, LumenError, NotFoundError
from lumen.db.connection import transaction, utc_now
from lumen.library.search import reindex_assets
from lumen.library.tags import get_or_create_tag, normalize_tag_name, tag_assets, tag_key
from lumen.schemas.assets import AssetBatchUpdate, AssetDetail, AssetUpdate, Tag
from lumen.services.assets import get_asset

_CHUNK = 500


def _chunks(ids: list[int]) -> Iterable[list[int]]:
    for start in range(0, len(ids), _CHUNK):
        yield ids[start : start + _CHUNK]


def update_asset(conn: sqlite3.Connection, asset_id: int, data: AssetUpdate) -> AssetDetail:
    changes = data.model_dump(exclude_unset=True)
    now = utc_now()
    with transaction(conn):
        if conn.execute("SELECT 1 FROM media_assets WHERE id = ?", (asset_id,)).fetchone() is None:
            raise NotFoundError("Asset not found", details={"id": asset_id})
        if changes.get("rating") is not None:
            conn.execute(
                "UPDATE media_assets SET rating = ?, rating_source = 'user', updated_at = ? "
                "WHERE id = ?",
                (changes["rating"], now, asset_id),
            )
        if changes.get("is_favorite") is not None:
            conn.execute(
                "UPDATE media_assets SET is_favorite = ?, updated_at = ? WHERE id = ?",
                (int(changes["is_favorite"]), now, asset_id),
            )
        if "notes" in changes:
            notes = (changes["notes"] or "").strip() or None
            conn.execute(
                "UPDATE media_assets SET notes = ?, updated_at = ? WHERE id = ?",
                (notes, now, asset_id),
            )
            reindex_assets(conn, [asset_id])
    return get_asset(conn, asset_id)


def batch_update(conn: sqlite3.Connection, data: AssetBatchUpdate) -> int:
    """Apply the same change to many assets; returns how many assets exist among the ids."""
    ids = sorted(set(data.asset_ids))
    add_tags = [name for name in (normalize_tag_name(n) for n in data.add_tags) if name]
    now = utc_now()
    with transaction(conn):
        existing: list[int] = []
        for chunk in _chunks(ids):
            marks = ",".join("?" * len(chunk))
            existing += [
                int(row[0])
                for row in conn.execute(f"SELECT id FROM media_assets WHERE id IN ({marks})", chunk)
            ]
        for chunk in _chunks(existing):
            marks = ",".join("?" * len(chunk))
            if data.rating is not None:
                conn.execute(
                    f"UPDATE media_assets SET rating = ?, rating_source = 'user', updated_at = ? "
                    f"WHERE id IN ({marks})",
                    (data.rating, now, *chunk),
                )
            if data.is_favorite is not None:
                conn.execute(
                    f"UPDATE media_assets SET is_favorite = ?, updated_at = ? "
                    f"WHERE id IN ({marks})",
                    (int(data.is_favorite), now, *chunk),
                )
            for tag_id in data.remove_tag_ids:
                conn.execute(
                    f"DELETE FROM media_tags WHERE tag_id = ? AND asset_id IN ({marks})",
                    (tag_id, *chunk),
                )
        for name in add_tags:
            tag_assets(conn, existing, get_or_create_tag(conn, name), "user")
        if add_tags or data.remove_tag_ids:
            reindex_assets(conn, existing)
    return len(existing)


def create_tag(conn: sqlite3.Connection, name: str) -> Tag:
    clean = normalize_tag_name(name)
    if not clean:
        raise LumenError("Tag name is empty")
    with transaction(conn):
        if conn.execute("SELECT 1 FROM tags WHERE name_key = ?", (tag_key(clean),)).fetchone():
            raise ConflictError("A tag with this name already exists", details={"name": clean})
        tag_id = get_or_create_tag(conn, clean)
    return Tag(id=tag_id, name=clean, asset_count=0)


def rename_tag(conn: sqlite3.Connection, tag_id: int, name: str) -> Tag:
    clean = normalize_tag_name(name)
    if not clean:
        raise LumenError("Tag name is empty")
    with transaction(conn):
        if conn.execute("SELECT 1 FROM tags WHERE id = ?", (tag_id,)).fetchone() is None:
            raise NotFoundError("Tag not found", details={"id": tag_id})
        clash = conn.execute(
            "SELECT id FROM tags WHERE name_key = ? AND id != ?", (tag_key(clean), tag_id)
        ).fetchone()
        if clash is not None:
            raise ConflictError("A tag with this name already exists", details={"name": clean})
        conn.execute(
            "UPDATE tags SET name = ?, name_key = ? WHERE id = ?", (clean, tag_key(clean), tag_id)
        )
        asset_ids = _tagged_assets(conn, tag_id)
        reindex_assets(conn, asset_ids)
    return Tag(id=tag_id, name=clean, asset_count=len(asset_ids))


def delete_tag(conn: sqlite3.Connection, tag_id: int) -> None:
    with transaction(conn):
        if conn.execute("SELECT 1 FROM tags WHERE id = ?", (tag_id,)).fetchone() is None:
            raise NotFoundError("Tag not found", details={"id": tag_id})
        asset_ids = _tagged_assets(conn, tag_id)
        conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        reindex_assets(conn, asset_ids)


def _tagged_assets(conn: sqlite3.Connection, tag_id: int) -> list[int]:
    return [
        int(row[0])
        for row in conn.execute("SELECT asset_id FROM media_tags WHERE tag_id = ?", (tag_id,))
    ]
