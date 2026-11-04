"""Culling (ADR-025): groups of similar photos, photos that look like rejects, and the
files of rejected photos. Nothing here changes or deletes files."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

import numpy as np

from lumen.schemas.assets import AssetQuality, AssetSummary
from lumen.schemas.cull import CullItem, RejectedFiles, SimilarGroup, SimilarGroups, Suspects
from lumen.services.assets import summaries_by_ids
from lumen.services.settings import get_settings

# Documents and screenshots are white or dark by nature: not suspects for exposure alone.
# (AI label names, see ai/labels.py.)
DOCUMENT_LABELS = ("文档", "截图")

_VISIBLE = """
    FROM media_assets a
    JOIN media_files c ON c.id = a.cover_file_id
         AND c.ingest_state = 'done' AND c.status = 'present'
    WHERE a.capture_time IS NOT NULL AND a.media_type = 'photo'
"""


def _qualities(conn: sqlite3.Connection, ids: list[int]) -> dict[int, AssetQuality]:
    found: dict[int, AssetQuality] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        rows = conn.execute(
            f"SELECT asset_id, sharpness, exposure, score, flags FROM media_quality "
            f"WHERE score IS NOT NULL AND asset_id IN ({','.join('?' * len(chunk))})",
            chunk,
        )
        for row in rows:
            found[int(row[0])] = AssetQuality(
                sharpness=row[1],
                exposure=row[2],
                score=row[3],
                flags=[flag for flag in str(row[4]).split(",") if flag],  # type: ignore[misc]
            )
    return found


def _rank(asset: AssetSummary, quality: AssetQuality | None) -> tuple[object, ...]:
    """Which photo of a group to keep: not rejected, then the user's own signals
    (favourite, stars, edited), then measured quality, then resolution."""
    return (
        asset.cull_flag != "reject",
        asset.is_favorite,
        asset.rating,
        asset.is_edited,
        quality.score if quality else 0.0,
        (asset.width or 0) * (asset.height or 0),
    )


def similar_groups(
    conn: sqlite3.Connection,
    *,
    window_minutes: int = 10,
    similarity: float = 0.9,
    pending_only: bool = True,
) -> SimilarGroups:
    """Photos taken within ``window_minutes`` of each other whose image embeddings are at
    least ``similarity`` alike, chained into groups (newest group first)."""
    model_id = get_settings(conn).ai_model
    rows = conn.execute(
        """
        SELECT a.id, a.capture_time, e.vector
        FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
             AND c.ingest_state = 'done' AND c.status = 'present'
        JOIN embeddings e ON e.asset_id = a.id AND e.model_id = ?
        WHERE a.capture_time IS NOT NULL AND a.media_type = 'photo'
        ORDER BY a.capture_time, a.id
        """,
        (model_id,),
    ).fetchall()
    if not rows:
        return SimilarGroups(available=False, groups=[], group_count=0, pending_count=0)

    ids = [int(row[0]) for row in rows]
    times = np.array([_timestamp(row[1]) for row in rows])
    vectors = np.stack([np.frombuffer(row[2], dtype=np.float16) for row in rows]).astype(
        np.float32
    )
    window = window_minutes * 60
    parent = list(range(len(ids)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(ids)):
        end = int(np.searchsorted(times, times[i] + window, side="right"))
        if end <= i + 1:
            continue
        alike = vectors[i + 1 : end] @ vectors[i]
        for offset in np.flatnonzero(alike >= similarity).tolist():
            parent[find(i)] = find(i + 1 + offset)

    members: dict[int, list[int]] = {}
    for index, asset_id in enumerate(ids):
        members.setdefault(find(index), []).append(asset_id)
    clusters = [group for group in members.values() if len(group) > 1]

    summaries = {s.id: s for s in summaries_by_ids(conn, [i for g in clusters for i in g])}
    qualities = _qualities(conn, list(summaries))
    groups: list[SimilarGroup] = []
    for cluster in clusters:
        assets = [summaries[i] for i in cluster if i in summaries]
        if len(assets) < 2:
            continue
        best = max(assets, key=lambda a: _rank(a, qualities.get(a.id)))
        groups.append(
            SimilarGroup(
                items=[CullItem(asset=a, quality=qualities.get(a.id)) for a in assets],
                recommended_id=best.id,
                pending=any(a.cull_flag == "none" for a in assets),
            )
        )
    groups.sort(key=lambda g: g.items[0].asset.capture_time or "", reverse=True)
    pending = sum(1 for g in groups if g.pending)
    return SimilarGroups(
        available=True,
        groups=[g for g in groups if g.pending] if pending_only else groups,
        group_count=len(groups),
        pending_count=pending,
    )


def suspects(conn: sqlite3.Connection, *, pending_only: bool = True, limit: int = 500) -> Suspects:
    """Photos measured as blurry or badly exposed, worst first."""
    rows = conn.execute(
        f"""
        SELECT a.id {_VISIBLE}
          AND EXISTS (
              SELECT 1 FROM media_quality q WHERE q.asset_id = a.id AND q.flags != ''
                AND (q.flags LIKE '%blurry%' OR NOT EXISTS (
                    SELECT 1 FROM media_tags mt JOIN tags t ON t.id = mt.tag_id
                    WHERE mt.asset_id = a.id AND t.name IN (?, ?))))
          {"AND a.cull_flag = 'none'" if pending_only else ""}
        """,
        DOCUMENT_LABELS,
    ).fetchall()
    ids = [int(row[0]) for row in rows]
    qualities = _qualities(conn, ids)
    items = [
        CullItem(asset=asset, quality=qualities.get(asset.id))
        for asset in summaries_by_ids(conn, ids)
    ]
    items.sort(key=lambda item: item.quality.score if item.quality else 1.0)
    return Suspects(items=items[:limit], total=len(items))


def rejected_files(conn: sqlite3.Connection) -> RejectedFiles:
    """Every file on disk of the rejected assets (photo, RAW, Live Photo clip, sidecar)."""
    rows = conn.execute(
        """
        SELECT r.path, f.relative_path FROM media_assets a
        JOIN media_files f ON f.asset_id = a.id AND f.status = 'present'
        JOIN storage_roots r ON r.id = f.storage_root_id
        WHERE a.cull_flag = 'reject'
        ORDER BY a.capture_time, f.relative_path
        """
    ).fetchall()
    assets = conn.execute("SELECT COUNT(*) FROM media_assets WHERE cull_flag = 'reject'")
    return RejectedFiles(
        asset_count=int(assets.fetchone()[0]),
        paths=[os.path.join(row[0], row[1]) for row in rows],
    )


def _timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value[:19]).timestamp()
    except ValueError:
        return 0.0
