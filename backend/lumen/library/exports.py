"""The export task: develop each photo (or cut each video) with its edit into a new file."""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lumen.core.errors import NotFoundError
from lumen.develop import live
from lumen.develop.engine import DevelopError
from lumen.develop.exporter import ExportOptions, export_photo, reserve_path
from lumen.develop.recipe import EditRecipe
from lumen.develop.video import VideoExportError, VideoExportStopped, VideoOptions, export_video
from lumen.media.metadata import ExifToolSession
from lumen.schemas.exports import ExportFailure, ExportRequest, ExportResult
from lumen.services.assets import DevelopUnavailableError, develop_source, video_source
from lumen.services.develop import current_recipe, current_video_recipe
from lumen.services.locations import overrides_for
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskContext

logger = logging.getLogger(__name__)

EXPORT_TASK = "export_assets"
MAX_REPORTED_FAILURES = 50


class _Unavailable(Exception):
    """The original is missing (or the asset is gone): skipped, not a failure."""


def export_assets(ctx: TaskContext) -> dict[str, Any]:
    request = ExportRequest.model_validate(ctx.payload)
    folder = Path(request.destination)
    photo_options = ExportOptions(
        long_edge=request.long_edge,
        quality=request.quality,
        include_metadata=request.include_metadata,
        include_location=request.include_location,
    )
    video_options = VideoOptions(
        mode=request.video_mode,
        include_metadata=request.include_metadata,
        include_location=request.include_location,
    )
    ids = request.asset_ids
    tools = live.Tools.of(ctx.settings)
    # Resume after a restart: progress is recorded after every item.
    start = min(int(queue.get(ctx.conn, ctx.task_id)["progress_current"]), len(ids))
    exported, skipped = start, 0
    failed: list[ExportFailure] = []

    def stop_video() -> bool:
        return ctx.should_stop() or queue.cancel_requested(ctx.conn, ctx.task_id)

    with contextlib.ExitStack() as stack:
        exiftool_path = ctx.settings.tool("exiftool")
        exiftool = (
            stack.enter_context(ExifToolSession(exiftool_path))
            if request.include_metadata and exiftool_path
            else None
        )
        ctx.progress(start, len(ids), force=True)
        for index in range(start, len(ids)):
            if not folder.is_dir():
                raise PermanentTaskError(f"Export folder is not available: {folder}")
            asset_id = ids[index]
            name = f"#{asset_id}"
            width = max(3, len(str(len(ids))))
            try:
                if _media_type(ctx, asset_id) == "video":
                    video = video_source(ctx.conn, asset_id)
                    name = video.path.name
                    ffmpeg = ctx.settings.tool("ffmpeg")
                    if ffmpeg is None:
                        raise VideoExportError("ffmpeg is not available")
                    export_video(
                        video.path,
                        current_video_recipe(ctx.conn, asset_id),
                        folder,
                        video_options,
                        ffmpeg=ffmpeg,
                        ffprobe=ctx.settings.tool("ffprobe"),
                        should_stop=stop_video,
                        stem=f"{index + 1:0{width}d}_{video.path.stem}"
                        if request.numbered
                        else None,
                    )
                else:
                    photo = develop_source(ctx.conn, asset_id)
                    name = photo.path.name
                    corrected = overrides_for(ctx.conn, asset_id)
                    clip = photo.clip(tools)
                    stem = f"{index + 1:0{width}d}_{photo.path.stem}" if request.numbered else None
                    if request.live_as != "photo" and clip is not None:
                        _export_motion(
                            clip,
                            current_recipe(ctx.conn, asset_id),
                            folder,
                            stem or photo.path.stem,
                            request,
                            corrected.capture_time,
                            stop_video,
                        )
                        exported += 1
                        ctx.progress(index + 1, len(ids), force=True)
                        continue
                    export_photo(
                        photo.path,
                        photo.format,
                        current_recipe(ctx.conn, asset_id),
                        folder,
                        photo_options,
                        exiftool,
                        stem=f"{index + 1:0{width}d}_{photo.path.stem}"
                        if request.numbered
                        else None,
                        location=corrected.location,
                        capture_time=corrected.capture_time,
                        motion=clip,
                    )
                exported += 1
            except (_Unavailable, DevelopUnavailableError, NotFoundError):
                skipped += 1
            except (VideoExportStopped, live.LiveStopped):
                ctx.progress(index, len(ids), force=True)  # raises: cancelled or shutting down
                raise
            except (DevelopError, VideoExportError, live.LiveError, OSError, ValueError) as exc:
                logger.warning("export failed", extra={"asset_id": asset_id, "error": str(exc)})
                failed.append(ExportFailure(asset_id=asset_id, file_name=name, error=str(exc)))
            ctx.progress(index + 1, len(ids), force=True)

    if exported == 0 and failed:
        raise PermanentTaskError(f"Nothing could be exported: {failed[0].error}")
    result = ExportResult(
        destination=str(folder),
        exported=exported,
        skipped=skipped,
        failed=failed[:MAX_REPORTED_FAILURES],
    )
    return result.model_dump()


def _export_motion(
    clip: live.Clip,
    recipe: EditRecipe,
    folder: Path,
    stem: str,
    request: ExportRequest,
    capture_time: str | None,
    should_stop: Callable[[], bool],
) -> Path:
    """A Live Photo as a video (its effect and adjustments, H.264) or a looping GIF.

    Only the capture time is written to an MP4: no location, whatever the GPS option.
    """
    extension = ".gif" if request.live_as == "gif" else ".mp4"
    edge = request.long_edge or (live.GIF_EDGE if request.live_as == "gif" else None)
    target = reserve_path(folder, stem, extension)
    handle, temp = tempfile.mkstemp(dir=folder, prefix=".lumen-", suffix=extension)
    os.close(handle)
    try:
        live.render_motion(
            clip,
            recipe,
            Path(temp),
            format="gif" if request.live_as == "gif" else "mp4",
            edge=edge,
            creation_time=capture_time if request.include_metadata else None,
            should_stop=should_stop,
        )
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return target


def _media_type(ctx: TaskContext, asset_id: int) -> str:
    row = ctx.conn.execute(
        "SELECT media_type FROM media_assets WHERE id = ?", (asset_id,)
    ).fetchone()
    if row is None:
        raise _Unavailable()
    return str(row["media_type"])
