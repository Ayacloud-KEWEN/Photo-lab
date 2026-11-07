"""Live Photos: attach the motion clip (.MOV) to its still's asset (ADR-017).

A still and a clip in the same folder are paired when both carry Apple's
ContentIdentifier and it matches, or, when either lacks it, when they share a name
and the clip is short. The clip becomes a ``companion`` of the photo asset; if it was
a video asset of its own, that asset's user data is merged in and the asset removed.

Google Photos exports the clip as ``.MP4`` (ADR-036): those pair only by a matching
ContentIdentifier. A clip whose asset holds several copies of it (merged duplicates)
brings them all; a photo that already has its clip takes further copies of it (same
ContentIdentifier) as more locations of the same motion.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from typing import TYPE_CHECKING

from lumen.db.connection import transaction, utc_now
from lumen.library.search import reindex_assets

if TYPE_CHECKING:
    from lumen.tasks.runner import TaskContext

logger = logging.getLogger(__name__)

LIVE_MAX_DURATION_MS = 4000  # Live Photo clips are ~1.5-3 s
STILL_EXTENSIONS = ("heic", "heif", "jpg", "jpeg")
CLIP_EXTENSION = "mov"  # the iPhone's own; matched by name too
CLIP_EXTENSIONS = (CLIP_EXTENSION, "mp4")  # mp4: Google Photos exports; matched by id only

# Apple's names for edited versions: IMG_E1234 (device), ABCDE1234 (Photos export).
_EDITED = re.compile(r"(?:_|^[^\W\d_]{4})E\d+$", re.IGNORECASE)  # group keys are case-folded

_COLUMNS = """
    SELECT f.id, f.storage_root_id, f.group_key, f.extension, f.asset_id,
           m.content_identifier, m.duration_ms, a.media_type,
           (SELECT COUNT(*) FROM media_files o
            WHERE o.asset_id = f.asset_id AND o.file_role != 'sidecar') AS asset_files
"""
_FILE = f"""
    {_COLUMNS}
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
        f"SELECT 1 FROM media_files WHERE asset_id = ? AND file_role = 'companion' "
        f"AND extension IN ({','.join('?' * len(CLIP_EXTENSIONS))}) LIMIT 1",
        (asset_id, *CLIP_EXTENSIONS),
    ).fetchone()
    return row is not None


def pair_live_photo(conn: sqlite3.Connection, file_id: int, now: str) -> bool:
    """Pair ``file_id`` (a still or a clip) with its other half, if found (in a transaction)."""
    me = conn.execute(f"{_FILE} WHERE f.id = ?", (file_id,)).fetchone()
    if me is None:
        return False
    is_clip = me["extension"] in CLIP_EXTENSIONS
    if not is_clip and (me["extension"] not in STILL_EXTENSIONS or me["media_type"] != "photo"):
        return False
    if is_clip and me["media_type"] != "video":
        return False  # already paired (a companion of a photo): nothing to do
    if not is_clip and _has_clip(conn, me["asset_id"]):
        return False  # further copies of its clip find it from their side

    wanted = STILL_EXTENSIONS if is_clip else CLIP_EXTENSIONS
    # Two indexed lookups (same name; same ContentIdentifier) rather than one OR across
    # two tables, which made SQLite scan the whole storage root for every imported file.
    others = f"""
        AND f.storage_root_id = ? AND f.id != ? AND f.status = 'present'
        AND f.file_role != 'sidecar' AND f.ingest_state = 'done'
        AND f.extension IN ({",".join("?" * len(wanted))})
    """
    common = (me["storage_root_id"], file_id, *wanted)
    rows = conn.execute(f"{_FILE} WHERE f.group_key = ? {others}", (me["group_key"], *common))
    found = {row["id"]: row for row in rows}
    if me["content_identifier"]:
        # CROSS JOIN keeps media_metadata first, so its content_identifier index is used.
        by_id = conn.execute(
            f"""
            {_COLUMNS}
            FROM media_metadata m
            CROSS JOIN media_files f ON f.id = m.file_id
            JOIN media_assets a ON a.id = f.asset_id
            WHERE m.content_identifier = ? {others}
            """,
            (me["content_identifier"], *common),
        )
        found.update((row["id"], row) for row in by_id)

    folder = os.path.dirname(me["group_key"])
    candidates = []
    for other in found.values():
        if os.path.dirname(other["group_key"]) != folder:
            continue
        still, clip = (other, me) if is_clip else (me, other)
        if still["media_type"] != "photo" or clip["media_type"] != "video":
            continue
        same_id = bool(still["content_identifier"]) and (
            still["content_identifier"] == clip["content_identifier"]
        )
        if clip["extension"] != CLIP_EXTENSION and not same_id:
            continue  # an mp4 is a Live Photo clip only by its id
        if is_clip and _has_clip(conn, still["asset_id"]) and not same_id:
            continue  # the photo has its clip; only another copy of it may join
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
    merge_user_data(conn, keep=photo_id, drop=video_id, now=now)
    # The clip, any other copies of it (merged duplicates) and sidecars move to the photo;
    # the clips become companions (sidecars stay sidecars).
    conn.execute(
        """
        UPDATE media_files
        SET asset_id = ?, updated_at = ?,
            file_role = CASE WHEN file_role = 'sidecar' THEN 'sidecar' ELSE 'companion' END
        WHERE asset_id = ?
        """,
        (photo_id, now, video_id),
    )
    conn.execute("DELETE FROM media_assets WHERE id = ?", (video_id,))
    logger.info(
        "live photo paired",
        extra={"asset_id": photo_id, "clip_file_id": clip_file_id, "removed_asset_id": video_id},
    )


def merge_user_data(conn: sqlite3.Connection, *, keep: int, drop: int, now: str) -> None:
    """Carry what the user set on one asset (``drop``) over to another (``keep``): the
    clip's own asset to the Live Photo, or a duplicate copy to the copy kept."""
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


# --------------------------------------------------------------- pairing the library again

REPAIR_TASK = "pair_live_photos"
REPAIR_KEY = "live_pairing_version"
REPAIR_VERSION = 2  # 2: .MP4 clips (Google Photos exports) and clips with several copies
_REPAIR_BATCH = 200


def _repair_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (REPAIR_KEY,)).fetchone()
    try:
        return int(json.loads(row[0])) if row else 1
    except (TypeError, ValueError):
        return 1


def needs_repair(conn: sqlite3.Connection) -> bool:
    """Imported before the pairing rules last changed: pair the library again once."""
    return _repair_version(conn) < REPAIR_VERSION


def repair_task(ctx: TaskContext) -> dict[str, int]:
    """Pair every clip still listed as a video of its own (the rules widened since it was
    imported). Each clip file tries once; finding its still merges its whole asset."""
    conn = ctx.conn
    clips = [
        int(row[0])
        for row in conn.execute(
            f"""
            SELECT f.id FROM media_files f
            JOIN media_assets a ON a.id = f.asset_id
            JOIN media_metadata m ON m.file_id = f.id
            WHERE a.media_type = 'video' AND f.status = 'present' AND f.ingest_state = 'done'
              AND f.extension IN ({",".join("?" * len(CLIP_EXTENSIONS))})
              AND (m.content_identifier IS NOT NULL OR m.duration_ms <= ?)
            ORDER BY f.id
            """,
            (*CLIP_EXTENSIONS, LIVE_MAX_DURATION_MS),
        )
    ]
    paired = 0
    ctx.progress(0, len(clips), force=True)
    for start in range(0, len(clips), _REPAIR_BATCH):
        ctx.check()
        now = utc_now()
        with transaction(conn):
            photos: list[int] = []
            for file_id in clips[start : start + _REPAIR_BATCH]:
                if pair_live_photo(conn, file_id, now):
                    paired += 1
                    row = conn.execute(
                        "SELECT asset_id FROM media_files WHERE id = ?", (file_id,)
                    ).fetchone()
                    photos.append(int(row[0]))
            if photos:
                reindex_assets(conn, photos)
        ctx.progress(min(start + _REPAIR_BATCH, len(clips)), len(clips))
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (REPAIR_KEY, json.dumps(REPAIR_VERSION), utc_now()),
        )
    logger.info("live photos paired again", extra={"clips": len(clips), "paired": paired})
    return {"clips": len(clips), "paired": paired}

