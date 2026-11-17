"""Keeping LUMEN and MapWeb (Periplus) in step, beyond sending (ADR-034 follow-up).

- Which photos are on the map, on which footprint and as which photo there: recorded when
  sending, and checked with MapWeb (``photo-lookup``), which also notices photos taken
  off the map.
- Photos edited since they were sent ("outdated"): their file on the map is replaced
  (``photo-replace``), keeping its place and number.
- Automatic sending (off unless the user turns it on): photos imported since then that
  match the rule (stars, favourite) are sent like a manual send, each only once.

Older MapWebs do not list these features in ``/api/health``; then only sending works.
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from lumen.core.errors import LumenError
from lumen.db.connection import transaction, utc_now
from lumen.media.metadata import ExifToolSession
from lumen.schemas.mapweb import MapWebSync
from lumen.services.settings import get_settings
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskContext

logger = logging.getLogger(__name__)

SYNC_TASK = "mapweb_sync"
UPDATE_TASK = "mapweb_update"
AUTO_TASK = "mapweb_auto_send"
LOOKUP = "photo-lookup"
REPLACE = "photo-replace"
MAX_AUTO = 2000

# Edited since sent: another cover content, or another edit (none counts as one).
OUTDATED = "(mp.fingerprint IS NOT c.fingerprint OR mp.recipe_hash IS NOT e.recipe_hash)"
_JOIN = """
    FROM mapweb_photos mp
    JOIN media_assets a ON a.id = mp.asset_id
    JOIN media_files c ON c.id = a.cover_file_id
    LEFT JOIN edit_history e ON e.id = a.current_edit_id
"""


class MapWebFeatureMissing(LumenError):
    code = "mapweb_feature_missing"


def _client_and_features(conn: sqlite3.Connection) -> tuple[Any, list[str]]:
    from lumen.services.mapweb import client_for

    client = client_for(conn)
    return client, client.health()


def status(conn: sqlite3.Connection) -> MapWebSync:
    """How many photos are on the map, how many changed since; and what MapWeb supports
    (nothing when it cannot be reached: the counts are what LUMEN knows)."""
    from lumen.services.mapweb import MapWebError

    on_map, outdated = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM({OUTDATED}), 0) {_JOIN}"
    ).fetchone()
    try:
        _, features = _client_and_features(conn)
    except (MapWebError, LumenError):
        features = []
    return MapWebSync(on_map=int(on_map), outdated=int(outdated), features=features)


# --- Which photos are on the map ----------------------------------------------------------------


def refresh_photo_ids(conn: sqlite3.Connection, client: Any) -> None:
    """After a send: which photo each newly sent one became (when MapWeb can tell)."""
    from lumen.services.mapweb import MapWebError, source_key

    rows = conn.execute(
        "SELECT mp.asset_id, a.uuid FROM mapweb_photos mp "
        "JOIN media_assets a ON a.id = mp.asset_id WHERE mp.photo_id IS NULL"
    ).fetchall()
    if not rows:
        return
    try:
        if LOOKUP not in client.health():
            return
        found = client.lookup([source_key(r["uuid"]) for r in rows])
    except MapWebError as exc:
        logger.info("MapWeb photo ids not checked", extra={"error": exc.message})
        return
    with transaction(conn):
        for row in rows:
            place = found.get(source_key(row["uuid"]))
            if place:
                conn.execute(
                    "UPDATE mapweb_photos SET point_id = ?, photo_id = ? WHERE asset_id = ?",
                    (place[0], place[1], row["asset_id"]),
                )


def sync(conn: sqlite3.Connection, client: Any) -> dict[str, int]:
    """Ask MapWeb where every photo of the library is. Photos sent before LUMEN kept track
    are taken as sent in their current version; photos taken off the map are forgotten."""
    from lumen.services.mapweb import source_key

    rows = conn.execute("SELECT id, uuid FROM media_assets WHERE media_type = 'photo'").fetchall()
    found = client.lookup([source_key(r["uuid"]) for r in rows])
    now = utc_now()
    added = removed = 0
    with transaction(conn):
        known = {int(r[0]) for r in conn.execute("SELECT asset_id FROM mapweb_photos")}
        for row in rows:
            asset_id = int(row["id"])
            place = found.get(source_key(row["uuid"]))
            if place is None:
                if asset_id in known:
                    conn.execute("DELETE FROM mapweb_photos WHERE asset_id = ?", (asset_id,))
                    removed += 1
                continue
            if asset_id in known:
                conn.execute(
                    "UPDATE mapweb_photos SET point_id = ?, photo_id = ? WHERE asset_id = ?",
                    (place[0], place[1], asset_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO mapweb_photos (asset_id, point_id, photo_id, fingerprint,
                                               recipe_hash, sent_at)
                    SELECT a.id, ?, ?, c.fingerprint, e.recipe_hash, ?
                    FROM media_assets a JOIN media_files c ON c.id = a.cover_file_id
                    LEFT JOIN edit_history e ON e.id = a.current_edit_id WHERE a.id = ?
                    """,
                    (place[0], place[1], now, asset_id),
                )
                added += 1
    return {"on_map": len(found), "added": added, "removed": removed}


def start_sync(conn: sqlite3.Connection) -> int:
    from lumen.services.mapweb import client_for

    client_for(conn)  # configured?
    return queue.enqueue(conn, SYNC_TASK)


def sync_task(ctx: TaskContext) -> dict[str, int]:
    from lumen.services.mapweb import MapWebError

    try:
        client, features = _client_and_features(ctx.conn)
        if LOOKUP not in features:
            raise PermanentTaskError("This MapWeb cannot say which photos it has (update it)")
        return sync(ctx.conn, client)
    except (MapWebError, LumenError) as exc:
        raise PermanentTaskError(exc.message) from exc


# --- Outdated photos ----------------------------------------------------------------------------


def start_update(conn: sqlite3.Connection, asset_ids: list[int] | None) -> int:
    from lumen.services.mapweb import client_for

    client_for(conn)
    return queue.enqueue(conn, UPDATE_TASK, payload={"asset_ids": asset_ids}, unique=False)


def update_task(ctx: TaskContext) -> dict[str, Any]:
    """Replace on the map the photos edited since they were sent."""
    from lumen.develop.engine import DevelopError
    from lumen.services.assets import DevelopUnavailableError
    from lumen.services.mapweb import (
        MapWebError,
        _NoExifTool,
        developed_jpeg,
        export_options,
        record_sent,
    )

    try:
        client, features = _client_and_features(ctx.conn)
    except (MapWebError, LumenError) as exc:
        raise PermanentTaskError(exc.message) from exc
    if REPLACE not in features:
        raise PermanentTaskError("This MapWeb cannot replace photos (update it)")
    if LOOKUP in features:
        refresh_photo_ids(ctx.conn, client)
    wanted = ctx.payload.get("asset_ids")
    rows = [
        r
        for r in ctx.conn.execute(
            f"SELECT mp.asset_id, mp.point_id, mp.photo_id, c.file_name {_JOIN} "
            f"WHERE {OUTDATED} AND mp.photo_id IS NOT NULL"
        ).fetchall()
        if wanted is None or int(r["asset_id"]) in wanted
    ]
    ctx.progress(0, len(rows), force=True)
    replaced = 0
    failed: list[dict[str, Any]] = []
    exiftool_path = ctx.settings.tool("exiftool")
    with (
        tempfile.TemporaryDirectory(prefix="lumen-mapweb-") as folder,
        ExifToolSession(exiftool_path) if exiftool_path else _NoExifTool() as exiftool,
    ):
        options = export_options(exiftool)
        for index, row in enumerate(rows):
            ctx.check()
            asset_id = int(row["asset_id"])
            try:
                jpeg = developed_jpeg(ctx, Path(folder), options, exiftool, asset_id)
                client.replace_photo(
                    int(row["point_id"]), int(row["photo_id"]), jpeg,
                    f"{Path(row['file_name']).stem}.jpg",
                )  # fmt: skip
                record_sent(ctx.conn, asset_id, int(row["point_id"]), int(row["photo_id"]))
                replaced += 1
            except MapWebError as exc:
                if exc.details.get("status") is None:
                    raise PermanentTaskError(exc.message) from exc
                if exc.details.get("status") == 404:  # taken off the map meanwhile
                    with transaction(ctx.conn):
                        ctx.conn.execute(
                            "DELETE FROM mapweb_photos WHERE asset_id = ?", (asset_id,)
                        )
                failed.append({"asset_id": asset_id, "error": exc.message})
            except (DevelopError, DevelopUnavailableError, OSError) as exc:
                failed.append({"asset_id": asset_id, "error": str(exc)})
            ctx.progress(index + 1, len(rows))
    return {"replaced": replaced, "failed": failed[:50]}


# --- Automatic sending --------------------------------------------------------------------------


def queue_auto_send(conn: sqlite3.Connection) -> int | None:
    """After an import or a rating: queue the automatic sending, when it is on."""
    app = get_settings(conn)
    if not app.mapweb_auto_send or not app.mapweb_url:
        return None
    return queue.enqueue(conn, AUTO_TASK)


def auto_candidates(conn: sqlite3.Connection) -> list[int]:
    app = get_settings(conn)
    if not app.mapweb_auto_send or not app.mapweb_auto_since:
        return []
    rule = "a.rating >= ?" + (" OR a.is_favorite = 1" if app.mapweb_auto_favorites else "")
    return [
        int(r[0])
        for r in conn.execute(
            f"""
            SELECT a.id FROM media_assets a
            WHERE a.media_type = 'photo' AND a.cull_flag != 'reject'
              AND a.created_at >= ? AND ({rule})
              AND NOT EXISTS (SELECT 1 FROM mapweb_photos mp WHERE mp.asset_id = a.id)
              AND NOT EXISTS (SELECT 1 FROM mapweb_auto_done d WHERE d.asset_id = a.id)
            ORDER BY a.capture_time LIMIT ?
            """,
            (app.mapweb_auto_since, app.mapweb_auto_min_rating, MAX_AUTO),
        )
    ]


def auto_task(ctx: TaskContext) -> dict[str, int]:
    """Send the photos matching the rule, as a manual send would (same footprint rules);
    each photo only once, even if it is taken off the map afterwards."""
    from lumen.services.mapweb import SEND_TASK

    ids = auto_candidates(ctx.conn)
    if not ids:
        return {"queued": 0}
    now = utc_now()
    with transaction(ctx.conn):
        ctx.conn.executemany(
            "INSERT OR IGNORE INTO mapweb_auto_done (asset_id, done_at) VALUES (?, ?)",
            [(asset_id, now) for asset_id in ids],
        )
    ctx.enqueue(SEND_TASK, payload={"asset_ids": ids, "language": "zh-CN"}, unique=False)
    logger.info("photos sent to MapWeb automatically", extra={"count": len(ids)})
    return {"queued": len(ids)}
