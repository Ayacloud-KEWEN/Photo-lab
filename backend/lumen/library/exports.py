"""The export task: develop each photo with its edit and write it as a new JPEG."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from lumen.core.errors import NotFoundError
from lumen.develop.engine import DevelopError
from lumen.develop.exporter import ExportOptions, export_photo
from lumen.media.metadata import ExifToolSession
from lumen.schemas.exports import ExportFailure, ExportRequest, ExportResult
from lumen.services.assets import DevelopUnavailableError, develop_source
from lumen.services.develop import current_recipe
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskContext

logger = logging.getLogger(__name__)

EXPORT_TASK = "export_assets"
MAX_REPORTED_FAILURES = 50


def export_assets(ctx: TaskContext) -> dict[str, Any]:
    request = ExportRequest.model_validate(ctx.payload)
    folder = Path(request.destination)
    options = ExportOptions(
        long_edge=request.long_edge,
        quality=request.quality,
        include_metadata=request.include_metadata,
        include_location=request.include_location,
    )
    ids = request.asset_ids
    # Resume after a restart: progress is recorded after every photo.
    start = min(int(queue.get(ctx.conn, ctx.task_id)["progress_current"]), len(ids))
    exported, skipped = start, 0
    failed: list[ExportFailure] = []

    with contextlib.ExitStack() as stack:
        exiftool_path = ctx.settings.tool("exiftool")
        exiftool = (
            stack.enter_context(ExifToolSession(exiftool_path))
            if options.include_metadata and exiftool_path
            else None
        )
        ctx.progress(start, len(ids), force=True)
        for index in range(start, len(ids)):
            if not folder.is_dir():
                raise PermanentTaskError(f"Export folder is not available: {folder}")
            asset_id = ids[index]
            try:
                source = develop_source(ctx.conn, asset_id)
            except (DevelopUnavailableError, NotFoundError):
                skipped += 1
            else:
                try:
                    export_photo(
                        source.path,
                        source.format,
                        current_recipe(ctx.conn, asset_id),
                        folder,
                        options,
                        exiftool,
                    )
                    exported += 1
                except (DevelopError, OSError, ValueError) as exc:
                    logger.warning("export failed", extra={"asset_id": asset_id, "error": str(exc)})
                    failed.append(
                        ExportFailure(asset_id=asset_id, file_name=source.path.name, error=str(exc))
                    )
            ctx.progress(index + 1, len(ids), force=True)

    if exported == 0 and failed:
        raise PermanentTaskError(f"No photo could be exported: {failed[0].error}")
    result = ExportResult(
        destination=str(folder),
        exported=exported,
        skipped=skipped,
        failed=failed[:MAX_REPORTED_FAILURES],
    )
    return result.model_dump()
