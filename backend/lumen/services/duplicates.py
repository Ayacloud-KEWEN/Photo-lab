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
from dataclasses import dataclass

from lumen.core.errors import LumenError
from lumen.db.connection import GenerationCache, transaction, utc_now
from lumen.library.live import merge_user_data
from lumen.library.search import reindex_assets
from lumen.schemas.duplicates import (
    DuplicateAsset,
    DuplicateFile,
    DuplicateGroup,
    DuplicateReport,
    MergeRequest,
    MergeResult,
)
from lumen.services.assets import summaries_by_ids
from lumen.tasks.runner import TaskContext


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


@dataclass
class _Planned:
    """A duplicate group: its copies (the one to keep first) and the space the rest take."""

    assets: list[int]
    redundant_bytes: int

    @property
    def keep(self) -> int:
        return self.assets[0]


def _plan(conn: sqlite3.Connection) -> tuple[list[_Planned], dict[int, int], dict[int, int]]:
    """Every group with the copy to keep, from cheap columns only (no summaries); also the
    tag and portfolio counts. Largest redundant size first."""
    components = _components(conn)
    ids = [asset_id for group in components for asset_id in group]
    rank: dict[int, tuple[object, ...]] = {}
    tags: dict[int, int] = {}
    collections: dict[int, int] = {}
    fingerprints: dict[int, list[tuple[str, int]]] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        marks = ",".join("?" * len(chunk))
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
        # Listable assets only (as the library shows them), with what decides the keeper.
        for row in conn.execute(
            f"""
            SELECT a.id, a.rating, a.is_favorite, a.cull_flag,
                   COALESCE(e.recipe_hash, '') != '' AS edited
            FROM media_assets a
            JOIN media_files c ON c.id = a.cover_file_id
                 AND c.ingest_state = 'done' AND c.status = 'present'
            LEFT JOIN edit_history e ON e.id = a.current_edit_id
            WHERE a.capture_time IS NOT NULL AND a.id IN ({marks})
            """,
            chunk,
        ):
            rank[int(row["id"])] = (
                bool(row["edited"]), row["cull_flag"] == "pick", row["rating"],
                bool(row["is_favorite"]),
            )  # fmt: skip
        for row in conn.execute(
            f"SELECT asset_id, fingerprint, size_bytes FROM media_files "
            f"WHERE status = 'present' AND file_role != 'sidecar' AND fingerprint IS NOT NULL "
            f"AND asset_id IN ({marks})",
            chunk,
        ):
            fingerprints.setdefault(int(row[0]), []).append((str(row[1]), int(row[2])))

    def order(asset_id: int) -> tuple[object, ...]:
        """The copy the user worked on most, else the first imported."""
        return (
            *rank[asset_id], tags.get(asset_id, 0), collections.get(asset_id, 0), -asset_id
        )

    planned: list[_Planned] = []
    for component in components:
        members = sorted((i for i in component if i in rank), key=order, reverse=True)
        if len(members) < 2:
            continue
        # Files whose content the kept copy already has take space for nothing.
        kept = {fingerprint for fingerprint, _ in fingerprints.get(members[0], [])}
        redundant = sum(
            size for i in members[1:] for fingerprint, size in fingerprints.get(i, [])
            if fingerprint in kept
        )  # fmt: skip
        planned.append(_Planned(assets=members, redundant_bytes=redundant))
    planned.sort(key=lambda group: group.redundant_bytes, reverse=True)
    return planned, tags, collections


_cache = GenerationCache(size=4)


def find_duplicates(conn: sqlite3.Connection, *, limit: int = 500) -> DuplicateReport:
    return _cache.get(("duplicates", limit), lambda: _find_duplicates(conn, limit=limit))


def _find_duplicates(conn: sqlite3.Connection, *, limit: int) -> DuplicateReport:
    planned, tags, collections = _plan(conn)
    shown = planned[:limit]
    ids = [asset_id for group in shown for asset_id in group.assets]
    summaries = {s.id: s for s in summaries_by_ids(conn, ids)}
    files: dict[int, list[DuplicateFile]] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        rows = conn.execute(
            f"""
            SELECT f.id, f.asset_id, f.relative_path, f.file_role, f.size_bytes, f.modified_at,
                   r.path AS root_path, r.display_name
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
    groups = [
        DuplicateGroup(
            assets=[
                DuplicateAsset(
                    asset=summaries[i],
                    files=files.get(i, []),
                    tag_count=tags.get(i, 0),
                    collection_count=collections.get(i, 0),
                )
                for i in group.assets
                if i in summaries
            ],
            keep_asset_id=group.keep,
            redundant_bytes=group.redundant_bytes,
        )
        for group in shown
    ]
    return DuplicateReport(
        groups=groups,
        group_count=len(planned),
        redundant_bytes=sum(group.redundant_bytes for group in planned),
    )


def merge_duplicates(conn: sqlite3.Connection, request: MergeRequest) -> MergeResult:
    """Fold each group's copies into one photo (the database only; no file is touched)."""
    components = {asset_id: tuple(group) for group in _components(conn) for asset_id in group}
    planned, _, _ = _plan(conn)
    suggested = {asset_id: group.keep for group in planned for asset_id in group.assets}
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


MERGE_ALL_TASK = "merge_duplicates"
_MERGE_CHUNK = 100


def merge_all_task(ctx: TaskContext) -> dict[str, int]:
    """Merge every duplicate group, each into its suggested copy (a background task:
    tens of thousands of groups take a while)."""
    planned, _, _ = _plan(ctx.conn)
    merged = removed = 0
    ctx.progress(0, len(planned), force=True)
    for start in range(0, len(planned), _MERGE_CHUNK):
        ctx.check()
        now = utc_now()
        with transaction(ctx.conn):
            for group in planned[start : start + _MERGE_CHUNK]:
                _merge(ctx.conn, group.keep, group.assets[1:], now)
                merged += 1
                removed += len(group.assets) - 1
        ctx.progress(merged, len(planned))
    return {"merged_groups": merged, "removed_assets": removed}


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
