"""Live Photos: attach the motion clip (.MOV) to its still's asset (ADR-017).

A still and a clip in the same folder are paired when both carry Apple's
ContentIdentifier and it matches, or, when either lacks it, when they share a name
and the clip is short. The clip becomes a ``companion`` of the photo asset; if it was
a video asset of its own, that asset's user data is merged in and the asset removed.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3

logger = logging.getLogger(__name__)

LIVE_MAX_DURATION_MS = 4000  # Live Photo clips are ~1.5-3 s
STILL_EXTENSIONS = ("heic", "heif", "jpg", "jpeg")
CLIP_EXTENSION = "mov"

# Apple's names for edited versions: IMG_E1234 (device), ABCDE1234 (Photos export).
_EDITED = re.compile(r"(?:_|^[^\W\d_]{4})E\d+$", re.IGNORECASE)  # group keys are case-folded

_FILE = """
    SELECT f.id, f.storage_root_id, f.group_key, f.extension, f.asset_id,
           m.content_identifier, m.duration_ms, a.media_type,
           (SELECT COUNT(*) FROM media_files o
            WHERE o.asset_id = f.asset_id AND o.file_role != 'sidecar') AS asset_files
    FROM media_files f
    JOIN media_assets a ON a.id = f.asset_id
    JOIN media_metadata m ON m.file_id = f.id
"""


def is_live_match(
    still_id: str | None, clip_id: str | None, *, same_name: bool, clip_ms: int | None
) -> bool:
    if still_id and clip_id:
        return still_id == clip_id
    return same_name and clip_ms is not None and clip_ms <= LIVE_MAX_DURATION_MS


def _edited(group_key: str) -> bool:
    return bool(_EDITED.search(os.path.basename(group_key)))


def _has_clip(conn: sqlite3.Connection, asset_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM media_files WHERE asset_id = ? AND file_role = 'companion' "
        "AND extension = ? LIMIT 1",
        (asset_id, CLIP_EXTENSION),
    ).fetchone()
    return row is not None


def pair_live_photo(conn: sqlite3.Connection, file_id: int, now: str) -> bool:
    """Pair ``file_id`` (a still or a clip) with its other half, if found (in a transaction)."""
    me = conn.execute(f"{_FILE} WHERE f.id = ?", (file_id,)).fetchone()
    if me is None:
        return False
    is_clip = me["extension"] == CLIP_EXTENSION
    if not is_clip and (me["extension"] not in STILL_EXTENSIONS or me["media_type"] != "photo"):
        return False
    if is_clip and (me["media_type"] == "photo" or me["asset_files"] != 1):
        return False  # already paired, or grouped with other files: leave it alone
    if not is_clip and _has_clip(conn, me["asset_id"]):
        return False

    wanted = STILL_EXTENSIONS if is_clip else (CLIP_EXTENSION,)
    rows = conn.execute(
        f"""
        {_FILE}
        WHERE f.storage_root_id = ? AND f.id != ? AND f.status = 'present'
          AND f.file_role != 'sidecar' AND f.ingest_state = 'done'
          AND f.extension IN ({",".join("?" * len(wanted))})
          AND (f.group_key = ? OR m.content_identifier = ?)
        """,
        (me["storage_root_id"], file_id, *wanted, me["group_key"], me["content_identifier"]),
    ).fetchall()

    folder = os.path.dirname(me["group_key"])
    candidates = []
    for other in rows:
        if os.path.dirname(other["group_key"]) != folder:
            continue
        still, clip = (other, me) if is_clip else (me, other)
        if still["media_type"] != "photo" or clip["media_type"] != "video":
            continue
        if clip["asset_files"] != 1 or (is_clip and _has_clip(conn, still["asset_id"])):
            continue
        same_name = other["group_key"] == me["group_key"]
        if not same_name and _edited(other["group_key"]) != _edited(me["group_key"]):
            # An original and an edited version share the id: pair originals together and
            # edited versions together, whatever order they are imported in.
            continue
        if not is_live_match(
            still["content_identifier"],
            clip["content_identifier"],
            same_name=same_name,
            clip_ms=clip["duration_ms"],
        ):
            continue
        candidates.append(((not same_name, other["id"]), still, clip))
    if not candidates:
        return False

    _, still, clip = min(candidates, key=lambda candidate: candidate[0])
    _attach_clip(conn, int(still["asset_id"]), int(clip["id"]), int(clip["asset_id"]), now)
    return True


def _attach_clip(
    conn: sqlite3.Connection, photo_id: int, clip_file_id: int, video_id: int, now: str
) -> None:
    _merge_user_data(conn, keep=photo_id, drop=video_id, now=now)
    conn.execute(
        "UPDATE media_files SET asset_id = ?, updated_at = ? WHERE asset_id = ?",
        (photo_id, now, video_id),  # the clip and any sidecars of it
    )
    conn.execute(
        "UPDATE media_files SET file_role = 'companion', updated_at = ? WHERE id = ?",
        (now, clip_file_id),
    )
    conn.execute("DELETE FROM media_assets WHERE id = ?", (video_id,))
    logger.info(
        "live photo paired",
        extra={"asset_id": photo_id, "clip_file_id": clip_file_id, "removed_asset_id": video_id},
    )


def _merge_user_data(conn: sqlite3.Connection, *, keep: int, drop: int, now: str) -> None:
    """Carry what the user set on the clip's own asset over to the photo asset."""
    kept = conn.execute("SELECT * FROM media_assets WHERE id = ?", (keep,)).fetchone()
    gone = conn.execute("SELECT * FROM media_assets WHERE id = ?", (drop,)).fetchone()
    rating, source = kept["rating"], kept["rating_source"]
    if gone["rating_source"] == "user" and (source != "user" or gone["rating"] > rating):
        rating, source = gone["rating"], "user"
    notes = "\n\n".join(n for n in (kept["notes"], gone["notes"]) if n) or None
    conn.execute(
        """
        UPDATE media_assets
        SET rating = ?, rating_source = ?, is_favorite = MAX(is_favorite, ?), notes = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (rating, source, gone["is_favorite"], notes, now, keep),
    )
    # AI labels describe the cover, which stays the photo: they are not carried over.
    conn.execute(
        """
        INSERT OR IGNORE INTO media_tags (asset_id, tag_id, source, confidence, created_at)
        SELECT ?, tag_id, source, confidence, created_at FROM media_tags
        WHERE asset_id = ? AND source != 'ai'
        """,
        (keep, drop),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO media_locations
            (asset_id, latitude, longitude, altitude_m, source, updated_at)
        SELECT ?, latitude, longitude, altitude_m, source, updated_at FROM media_locations
        WHERE asset_id = ?
        """,
        (keep, drop),
    )
    # Portfolios that held the clip hold the Live Photo instead, in the clip's place.
    conn.execute(
        """
        INSERT OR IGNORE INTO collection_items
            (collection_id, asset_id, position, caption, added_at)
        SELECT collection_id, ?, position, caption, added_at FROM collection_items
        WHERE asset_id = ?
        """,
        (keep, drop),
    )
