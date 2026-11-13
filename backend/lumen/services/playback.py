"""Playing videos the web view cannot play: their cached H.264 copy, made on first play."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lumen.core.config import Settings
from lumen.core.errors import LumenError, NotFoundError
from lumen.media import playback
from lumen.media.formats import needs_playback_copy
from lumen.schemas.assets import PlaybackState
from lumen.services.assets import original_file
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskContext

PLAYBACK_TASK = "video_playback_copy"


def _cover(conn: sqlite3.Connection, asset_id: int) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        """
        SELECT a.media_type, c.extension, c.fingerprint, m.duration_ms
        FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
        LEFT JOIN media_metadata m ON m.file_id = c.id
        WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("Asset not found", details={"id": asset_id})
    return row


def _active_task(conn: sqlite3.Connection, asset_id: int) -> int | None:
    for row in conn.execute(
        "SELECT id, payload FROM tasks WHERE kind = ? AND status IN ('pending', 'running') "
        "AND cancel_requested = 0",
        (PLAYBACK_TASK,),
    ):
        if json.loads(row["payload"] or "{}").get("asset_id") == asset_id:
            return int(row["id"])
    return None


def state(
    conn: sqlite3.Connection, settings: Settings, asset_id: int, *, start: bool
) -> PlaybackState:
    """Whether the video needs a copy to play, whether it is ready (and, with ``start``,
    the task making it)."""
    row = _cover(conn, asset_id)
    if row["media_type"] != "video" or not needs_playback_copy(row["extension"] or ""):
        return PlaybackState(needed=False, ready=True, task_id=None)
    if not row["fingerprint"]:
        raise LumenError("The video has not been processed yet")
    if playback.playback_path(settings.cache_dir, row["fingerprint"]).is_file():
        return PlaybackState(needed=True, ready=True, task_id=None)
    task_id = _active_task(conn, asset_id)
    if task_id is None and start:
        if not settings.tool("ffmpeg"):
            raise LumenError("ffmpeg is needed to play this video")
        task_id = queue.enqueue(
            conn, PLAYBACK_TASK, payload={"asset_id": asset_id}, priority=20, unique=False
        )
    return PlaybackState(needed=True, ready=False, task_id=task_id)


def copy_file(conn: sqlite3.Connection, settings: Settings, asset_id: int) -> Path:
    row = _cover(conn, asset_id)
    path = (
        playback.playback_path(settings.cache_dir, row["fingerprint"])
        if row["fingerprint"]
        else None
    )
    if path is None or not path.is_file():
        raise NotFoundError("No playback copy yet", details={"id": asset_id})
    return path


def make_copy(ctx: TaskContext) -> dict[str, int]:
    asset_id = int(ctx.payload["asset_id"])
    row = _cover(ctx.conn, asset_id)
    ffmpeg = ctx.settings.tool("ffmpeg")
    if not ffmpeg:
        raise PermanentTaskError("ffmpeg is not available")
    target = playback.playback_path(ctx.settings.cache_dir, row["fingerprint"])
    if target.is_file():
        return {"asset_id": asset_id}
    source, _ = original_file(ctx.conn, asset_id)
    ctx.progress(0, 100, force=True)
    try:
        playback.convert(
            ffmpeg, source, target, row["duration_ms"],
            lambda done: ctx.progress(int(done * 100), 100),
        )  # fmt: skip
    except playback.PlaybackError as exc:
        raise PermanentTaskError(f"The video could not be converted: {exc}") from exc
    ctx.progress(100, 100, force=True)
    return {"asset_id": asset_id}
