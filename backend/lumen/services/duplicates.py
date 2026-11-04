"""Duplicate files (ADR-026): copies with identical content that the library lists as
separate photos, and merging them into one photo with several file locations.

Merging only changes the database: every file stays where it is (originals are
read-only), the merged photo lists all copies, and what the user set on any copy
(stars, tags, notes, portfolios, an edit) is kept. Deleting the extra copies on disk is
left to the user; the photo stays available while any copy is present (see
``scan.py``, which moves the cover to a present copy).
"""

from __future__ import annotations

import os
import sqlite3

from lumen.core.errors import LumenError
from lumen.db.connection import transaction, utc_now
from lumen.library.live import merge_user_data
from lumen.library.search import reindex_assets
from lumen.schemas.assets import AssetSummary
from lumen.schemas.duplicates import (
    DuplicateAsset,
    DuplicateFile,
    DuplicateGroup,
    DuplicateReport,
    MergeRequest,
    MergeResult,
)
from lumen.services.assets import summaries_by_ids


def _components(conn: sqlite3.Connection) -> list[list[int]]:
    """Sets of assets that share at least one identical present file."""
    rows = conn.execute(
        """
        SELECT fingerprint, asset_id FROM media_files
        WHERE fingerprint IS NOT NULL AND asset_id IS NOT NULL AND status = 'present'
          AND file_role != 'sidecar'
          AND fingerprint IN (
              SELECT fingerprint FROM media_files
              WHERE fingerprint IS NOT NULL AND asset_id IS NOT NULL AND status = 'present'
                AND file_role != 'sidecar'
              GROUP BY fingerprint HAVING COUNT(DISTINCT asset_id) > 1)
        """
    ).fetchall()
    parent: dict[int, int] = {}

    def find(asset: int) -> int:
        parent.setdefault(asset, asset)
        while parent[asset] != asset:
            parent[asset] = parent[parent[asset]]
            asset = parent[asset]
        return asset

    first_of: dict[str, int] = {}
    for fingerprint, asset_id in rows:
        find(asset_id)
        if fingerprint in first_of:
            parent[find(asset_id)] = find(first_of[fingerprint])
        else:
            first_of[fingerprint] = asset_id
    groups: dict[int, list[int]] = {}
    for asset_id in parent:
        groups.setdefault(find(asset_id), []).append(asset_id)
    return [sorted(group) for group in groups.values() if len(group) > 1]


def _counts(conn: sqlite3.Connection, sql: str, ids: list[int]) -> dict[int, int]:
    marks = ",".join("?" * len(ids))
    return {int(row[0]): int(row[1]) for row in conn.execute(sql.format(marks=marks), ids)}


def _rank(asset: AssetSummary, tags: int, collections: int) -> tuple[object, ...]:
    """The copy to keep: the one the user worked on most, else the first imported."""
    return (
        asset.is_edited,
        asset.cull_flag == "pick",
        asset.rating,
        asset.is_favorite,
        tags,
        collections,
        -asset.id,
    )


def find_duplicates(conn: sqlite3.Connection, *, limit: int = 500) -> DuplicateReport:
    components = _components(conn)
    ids = [asset_id for group in components for asset_id in group]
    if not ids:
        return DuplicateReport(groups=[], group_count=0, redundant_bytes=0)
    summaries = {s.id: s for s in summaries_by_ids(conn, ids)}
    tags: dict[int, int] = {}
    collections: dict[int, int] = {}
    files: dict[int, list[DuplicateFile]] = {}
    fingerprints: dict[int, dict[int, str]] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        tags |= _counts(
            conn,
            "SELECT asset_id, COUNT(*) FROM media_tags WHERE source != 'ai' "
            "AND asset_id IN ({marks}) GROUP BY asset_id",
            chunk,
        )
        collections |= _counts(
            conn,
            "SELECT asset_id, COUNT(*) FROM collection_items WHERE asset_id IN ({marks}) "
            "GROUP BY asset_id",
            chunk,
        )
        rows = conn.execute(
            f"""
            SELECT f.id, f.asset_id, f.relative_path, f.file_role, f.size_bytes, f.modified_at,
                   f.fingerprint, r.path AS root_path, r.display_name
            FROM media_files f JOIN storage_roots r ON r.id = f.storage_root_id
            WHERE f.status = 'present' AND f.asset_id IN ({",".join("?" * len(chunk))})
            ORDER BY f.file_role = 'primary' DESC, f.id
            """,
            chunk,
        )
        for row in rows:
            files.setdefault(row["asset_id"], []).append(
                DuplicateFile(
                    file_id=row["id"],
                    path=os.path.join(row["root_path"], row["relative_path"]),
                    folder=row["display_name"],
                    role=row["file_role"],
                    size_bytes=row["size_bytes"],
                    modified_at=row["modified_at"],
                )
            )
            if row["fingerprint"] and row["file_role"] != "sidecar":
                fingerprints.setdefault(row["asset_id"], {})[row["id"]] = row["fingerprint"]

    groups: list[DuplicateGroup] = []
    for component in components:
        members = [summaries[i] for i in component if i in summaries]
        if len(members) < 2:
            continue
        members.sort(
            key=lambda a: _rank(a, tags.get(a.id, 0), collections.get(a.id, 0)), reverse=True
        )
        keep = members[0].id
        # Files whose content the kept copy already has take space for nothing.
        kept = set(fingerprints.get(keep, {}).values())
        redundant = sum(
            f.size_bytes
            for a in members[1:]
            for f in files.get(a.id, [])
            if fingerprints.get(a.id, {}).get(f.file_id) in kept
        )
        groups.append(
            DuplicateGroup(
                assets=[
                    DuplicateAsset(
                        asset=a,
                        files=files.get(a.id, []),
                        tag_count=tags.get(a.id, 0),
                        collection_count=collections.get(a.id, 0),
                    )
                    for a in members
                ],
                keep_asset_id=keep,
                redundant_bytes=redundant,
            )
        )
    groups.sort(key=lambda g: g.redundant_bytes, reverse=True)
    return DuplicateReport(
        groups=groups[:limit],
        group_count=len(groups),
        redundant_bytes=sum(g.redundant_bytes for g in groups),
    )


def merge_duplicates(conn: sqlite3.Connection, request: MergeRequest) -> MergeResult:
    """Fold each group's copies into one photo (the database only; no file is touched)."""
    components = {asset_id: tuple(group) for group in _components(conn) for asset_id in group}
    suggested = {
        entry.asset.id: group.keep_asset_id
        for group in find_duplicates(conn, limit=len(components) + 1).groups
        for entry in group.assets
    }
    now = utc_now()
    merged = removed = 0
    with transaction(conn):
        for group in request.groups:
            ids = sorted(set(group.asset_ids))
            component = components.get(ids[0])
            if component is None or any(components.get(i) != component for i in ids):
                raise LumenError(
                    "These photos are not copies of the same file", details={"asset_ids": ids}
                )
            keep = group.keep_asset_id or suggested.get(ids[0], ids[0])
            if keep not in ids:
                raise LumenError("The photo to keep must be one of the copies")
            drops = [i for i in ids if i != keep]
            _merge(conn, keep, drops, now)
            merged += 1
            removed += len(drops)
    return MergeResult(merged_groups=merged, removed_assets=removed)


def _merge(conn: sqlite3.Connection, keep: int, drops: list[int], now: str) -> None:
    marks = ",".join("?" * (len(drops) + 1))
    flags = [row[0] for row in conn.execute(
        f"SELECT cull_flag FROM media_assets WHERE id IN ({marks})", [keep, *drops]
    )]  # fmt: skip
    flag = "pick" if "pick" in flags else "reject" if set(flags) == {"reject"} else "none"
    for drop in drops:
        merge_user_data(conn, keep=keep, drop=drop, now=now)
        kept_edit = conn.execute(
            "SELECT current_edit_id FROM media_assets WHERE id = ?", (keep,)
        ).fetchone()[0]
        dropped_edit = conn.execute(
            "SELECT current_edit_id FROM media_assets WHERE id = ?", (drop,)
        ).fetchone()[0]
        if kept_edit is None and dropped_edit is not None:
            # The copies are identical, so the edit applies to the kept one as it is.
            conn.execute("UPDATE edit_history SET asset_id = ? WHERE asset_id = ?", (keep, drop))
            conn.execute(
                "UPDATE media_assets SET current_edit_id = ? WHERE id = ?", (dropped_edit, keep)
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO ai_analysis_assets (analysis_id, asset_id, position)
            SELECT analysis_id, ?, position FROM ai_analysis_assets WHERE asset_id = ?
            """,
            (keep, drop),
        )
        conn.execute(
            "UPDATE collections SET cover_asset_id = ? WHERE cover_asset_id = ?", (keep, drop)
        )
        conn.execute(
            "UPDATE media_files SET asset_id = ?, updated_at = ? WHERE asset_id = ?",
            (keep, now, drop),
        )
        conn.execute("DELETE FROM media_assets WHERE id = ?", (drop,))
        conn.execute("DELETE FROM asset_search WHERE rowid = ?", (drop,))
    conn.execute(
        "UPDATE media_assets SET cull_flag = ?, updated_at = ? WHERE id = ?", (flag, now, keep)
    )
    reindex_assets(conn, [keep])
