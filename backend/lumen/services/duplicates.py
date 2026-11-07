"""Duplicate files (ADR-026): copies with identical content that the library lists as
separate photos, and merging them into one photo with several file locations.

Copies of different quality (ADR-033) are the same shot saved again: recompressed by a
cloud service (a Google Photos export), converted (HEIC to JPEG) or resized. Their bytes
differ, so they are found by what does not change: the capture time to the second, the
file name, the camera, the proportions and (when the AI index has both) the picture.

Merging only changes the database: every file stays where it is (originals are
read-only), the merged photo lists all copies, and what the user set on any copy
(stars, tags, notes, portfolios, an edit) is kept. Deleting the extra copies on disk is
left to the user; the photo stays available while any copy is present (see
``scan.py``, which moves the cover to a present copy).
"""

from __future__ import annotations

import itertools
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from typing import Literal

import numpy as np

from lumen.ai.index import index as vector_index
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
from lumen.services.settings import get_settings
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


DuplicateKind = Literal["identical", "copies"]

COPY_SIMILARITY = 0.7
"""Least cosine similarity of a resized copy's image embedding to the best copy's. On the
user's library 98 % of copies are above 0.98; real copies rotated by 90 degrees or saved at
a few dozen KB go down to about 0.73."""
ASPECT_TOLERANCE = 0.02
DURATION_TOLERANCE_MS = 1500
ORIGINAL_FORMATS = frozenset(
    {"heic", "heif", "dng", "cr2", "cr3", "nef", "arw", "orf", "raf", "rw2", "pef", "srw"}
)
_NUMBERED = re.compile(r"\s*\(\d+\)$")


def _stem(file_name: str) -> str:
    """The name that copies share: no extension, any case, no " (1)" a copy added."""
    return _NUMBERED.sub("", os.path.splitext(file_name)[0].lower())


@dataclass(frozen=True)
class _Copy:
    asset_id: int
    pixels: int
    live: bool
    original_format: bool
    size: int
    camera: str
    ratio: float | None
    duration_ms: int | None

    @property
    def quality(self) -> tuple[int, bool, bool, int, int]:
        """Most pixels, then a Live Photo, then the original format, then the larger file."""
        return (self.pixels, self.live, self.original_format, self.size, -self.asset_id)

    def matches(self, other: _Copy) -> bool:
        if self.camera and other.camera and self.camera != other.camera:
            return False
        if (
            self.ratio
            and other.ratio
            and abs(self.ratio - other.ratio) > ASPECT_TOLERANCE * self.ratio
        ):
            return False
        return not (
            self.duration_ms is not None
            and other.duration_ms is not None
            and abs(self.duration_ms - other.duration_ms) > DURATION_TOLERANCE_MS
        )


def _copy_groups(conn: sqlite3.Connection) -> list[list[int]]:
    """Sets of listable assets that are copies of one shot, best copy first."""
    candidates: dict[tuple[str, str, str], list[int]] = {}
    for asset_id, media_type, taken, file_name in conn.execute(
        """
        SELECT a.id, a.media_type, a.capture_time, c.file_name
        FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
             AND c.ingest_state = 'done' AND c.status = 'present'
        WHERE a.capture_time IS NOT NULL
        """
    ):
        candidates.setdefault((taken, media_type, _stem(file_name)), []).append(int(asset_id))
    sets = [ids for ids in candidates.values() if len(ids) > 1]
    if not sets:
        return []

    ids = [asset_id for group in sets for asset_id in group]
    copies: dict[int, _Copy] = {}
    live = {
        int(row[0])
        for row in _rows(
            conn,
            "SELECT asset_id FROM media_files "
            "WHERE file_role = 'companion' AND status = 'present' {ids}",
            "asset_id",
            ids,
        )
    }
    for row in _rows(
        conn,
        """
        SELECT a.id, c.extension, c.size_bytes, m.width, m.height, m.camera_model, m.duration_ms
        FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
        LEFT JOIN media_metadata m ON m.file_id = c.id
        WHERE 1 {ids}
        """,
        "a.id",
        ids,
    ):
        width, height = row["width"] or 0, row["height"] or 0
        copies[int(row["id"])] = _Copy(
            asset_id=int(row["id"]),
            pixels=width * height,
            live=int(row["id"]) in live,
            original_format=(row["extension"] or "").lower() in ORIGINAL_FORMATS,
            size=int(row["size_bytes"] or 0),
            camera=(row["camera_model"] or "").strip().lower(),
            ratio=max(width, height) / min(width, height) if width and height else None,
            duration_ms=row["duration_ms"],
        )

    # Within a set, best first: each copy joins the first better copy it matches, or starts
    # its own group (another camera's photo of the same name, a crop).
    matched: list[tuple[_Copy, list[_Copy]]] = []
    for group in sets:
        members = sorted(
            (copies[i] for i in group if i in copies), key=lambda c: c.quality, reverse=True
        )
        clusters: list[tuple[_Copy, list[_Copy]]] = []
        for member in members:
            home = next((c for c in clusters if c[0].matches(member)), None)
            if home is None:
                clusters.append((member, []))
            else:
                home[1].append(member)
        matched.extend(cluster for cluster in clusters if cluster[1])

    # Copies of the same size are the picture saved again; a resized one is compared with
    # the best copy by its image embedding too (when the AI index has both).
    similarity = _similarities(
        conn,
        [
            (best.asset_id, other.asset_id)
            for best, others in matched
            for other in others
            if other.pixels != best.pixels
        ],
    )
    groups: list[list[int]] = []
    for best, others in matched:
        kept = [best.asset_id]
        for other in others:
            alike = similarity.get((best.asset_id, other.asset_id))
            if alike is not None and alike < COPY_SIMILARITY:
                continue
            kept.append(other.asset_id)
        if len(kept) > 1:
            groups.append(kept)
    return groups


_similarity_cache: dict[tuple[str, int, int, int], float] = {}
_similarity_lock = threading.Lock()


def _similarities(
    conn: sqlite3.Connection, pairs: list[tuple[int, int]]
) -> dict[tuple[int, int], float]:
    """Cosine similarity of the image embeddings of each pair that has both. Reading tens
    of thousands of vectors takes seconds, so the results are kept until the vector index
    changes (new embeddings, a restored database)."""
    model_id = get_settings(conn).ai_model
    generation = vector_index.generation(model_id)
    with _similarity_lock:
        known = {
            pair: _similarity_cache[(model_id, generation, *pair)]
            for pair in pairs
            if (model_id, generation, *pair) in _similarity_cache
        }
    missing = [pair for pair in pairs if pair not in known]
    ids = sorted({asset_id for pair in missing for asset_id in pair})
    vectors: dict[int, np.ndarray] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        for asset_id, blob in conn.execute(
            f"SELECT asset_id, vector FROM embeddings "
            f"WHERE model_id = ? AND asset_id IN ({','.join('?' * len(chunk))})",
            (model_id, *chunk),
        ):
            vector = np.frombuffer(blob, dtype=np.float16).astype(np.float32)
            norm = float(np.linalg.norm(vector))
            if norm:
                vectors[int(asset_id)] = vector / norm
    found = {
        (a, b): float(vectors[a] @ vectors[b])
        for a, b in missing
        if a in vectors and b in vectors
    }
    with _similarity_lock:
        if len(_similarity_cache) > 1_000_000 or any(
            key[:2] != (model_id, generation) for key in itertools.islice(_similarity_cache, 1)
        ):
            _similarity_cache.clear()  # results for older vectors
        _similarity_cache.update(
            {(model_id, generation, *pair): value for pair, value in found.items()}
        )
    return known | found


_SCAN_ABOVE = 20_000
"""Above this many assets one pass over a table beats looking them up 500 at a time."""


def _rows(conn: sqlite3.Connection, sql: str, column: str, ids: list[int]) -> list[sqlite3.Row]:
    """Rows of ``sql`` for these assets: ``{ids}`` in it becomes the condition on ``column``
    (or, for many assets, the whole table is read and filtered here)."""
    if len(ids) > _SCAN_ABOVE:
        wanted = set(ids)
        return [row for row in conn.execute(sql.format(ids="")) if int(row[0]) in wanted]
    rows: list[sqlite3.Row] = []
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        condition = f"AND {column} IN ({','.join('?' * len(chunk))})"
        rows.extend(conn.execute(sql.format(ids=condition), chunk))
    return rows


@dataclass
class _Planned:
    """A duplicate group: its copies (the one to keep first) and the space the rest take."""

    assets: list[int]
    redundant_bytes: int

    @property
    def keep(self) -> int:
        return self.assets[0]


def _groups(conn: sqlite3.Connection, kind: DuplicateKind) -> list[list[int]]:
    return _components(conn) if kind == "identical" else _copy_groups(conn)


def _plan(
    conn: sqlite3.Connection, kind: DuplicateKind = "identical"
) -> tuple[list[_Planned], dict[int, int], dict[int, int]]:
    """Every group with the copy to keep, from cheap columns only (no summaries); also the
    tag and portfolio counts. Largest redundant size first.

    Identical copies keep the one the user worked on most; copies of different quality
    keep the best picture (what the user set on the others is merged into it)."""
    components = _groups(conn, kind)
    ids = [asset_id for group in components for asset_id in group]
    rank: dict[int, tuple[object, ...]] = {}
    tags: dict[int, int] = {}
    collections: dict[int, int] = {}
    fingerprints: dict[int, list[tuple[str, int]]] = {}
    for row in _rows(
        conn,
        "SELECT asset_id, COUNT(*) FROM media_tags WHERE source != 'ai' {ids} GROUP BY asset_id",
        "asset_id",
        ids,
    ):
        tags[int(row[0])] = int(row[1])
    for row in _rows(
        conn,
        "SELECT asset_id, COUNT(*) FROM collection_items WHERE 1 {ids} GROUP BY asset_id",
        "asset_id",
        ids,
    ):
        collections[int(row[0])] = int(row[1])
    # Listable assets only (as the library shows them), with what decides the keeper.
    for row in _rows(
        conn,
        """
        SELECT a.id, a.rating, a.is_favorite, a.cull_flag,
               COALESCE(e.recipe_hash, '') != '' AS edited
        FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
             AND c.ingest_state = 'done' AND c.status = 'present'
        LEFT JOIN edit_history e ON e.id = a.current_edit_id
        WHERE a.capture_time IS NOT NULL {ids}
        """,
        "a.id",
        ids,
    ):
        rank[int(row["id"])] = (
            bool(row["edited"]), row["cull_flag"] == "pick", row["rating"],
            bool(row["is_favorite"]),
        )  # fmt: skip
    for row in _rows(
        conn,
        "SELECT asset_id, fingerprint, size_bytes FROM media_files "
        "WHERE status = 'present' AND file_role != 'sidecar' AND fingerprint IS NOT NULL {ids}",
        "asset_id",
        ids,
    ):
        fingerprints.setdefault(int(row[0]), []).append((str(row[1]), int(row[2])))

    def order(asset_id: int) -> tuple[object, ...]:
        """The copy the user worked on most, else the first imported."""
        return (
            *rank[asset_id], tags.get(asset_id, 0), collections.get(asset_id, 0), -asset_id
        )

    planned: list[_Planned] = []
    for component in components:
        if kind == "identical":
            members = sorted((i for i in component if i in rank), key=order, reverse=True)
        else:
            members = [i for i in component if i in rank]  # best picture first
        if len(members) < 2:
            continue
        if kind == "identical":
            # Files whose content the kept copy already has take space for nothing.
            kept = {fingerprint for fingerprint, _ in fingerprints.get(members[0], [])}
            redundant = sum(
                size for i in members[1:] for fingerprint, size in fingerprints.get(i, [])
                if fingerprint in kept
            )  # fmt: skip
        else:
            redundant = sum(size for i in members[1:] for _, size in fingerprints.get(i, []))
        planned.append(_Planned(assets=members, redundant_bytes=redundant))
    planned.sort(key=lambda group: group.redundant_bytes, reverse=True)
    return planned, tags, collections


_cache = GenerationCache(size=4)


def find_duplicates(
    conn: sqlite3.Connection, *, limit: int = 500, kind: DuplicateKind = "identical"
) -> DuplicateReport:
    return _cache.get(
        ("duplicates", kind, limit), lambda: _find_duplicates(conn, limit=limit, kind=kind)
    )


def _find_duplicates(
    conn: sqlite3.Connection, *, limit: int, kind: DuplicateKind
) -> DuplicateReport:
    planned, tags, collections = _plan(conn, kind)
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
    kind = request.kind
    components = {
        asset_id: tuple(sorted(group)) for group in _groups(conn, kind) for asset_id in group
    }
    planned, _, _ = _plan(conn, kind)
    suggested = {asset_id: group.keep for group in planned for asset_id in group.assets}
    now = utc_now()
    merged = removed = 0
    with transaction(conn):
        for group in request.groups:
            ids = sorted(set(group.asset_ids))
            component = components.get(ids[0])
            if component is None or any(components.get(i) != component for i in ids):
                raise LumenError(
                    "These photos are not copies of the same file" if kind == "identical"
                    else "These photos are not copies of the same shot",
                    details={"asset_ids": ids},
                )  # fmt: skip
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
    tens of thousands of groups take a while). The payload's ``kind`` says which groups."""
    kind: DuplicateKind = "copies" if ctx.payload.get("kind") == "copies" else "identical"
    planned, _, _ = _plan(ctx.conn, kind)
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
            # The copies show the same picture (crops are fractions of the frame), so the
            # edit applies to the kept one as it is.
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
