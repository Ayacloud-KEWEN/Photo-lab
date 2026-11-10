"""Running the local model for a text task (captions, questions): checks, start and stop.

The model reads the photos it has not read yet, then answers prompts built from what it
read. Tests replace the model with ``pipeline.set_reader_factory``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from lumen.core.config import Settings
from lumen.core.errors import LumenError
from lumen.tasks.runner import PermanentTaskError, TaskContext
from lumen.vlm import describe as describing
from lumen.vlm.models import DEFAULT_MODEL, MODELS, llama_server, models_dir
from lumen.vlm.server import ServerError

# Prompts built from many photos need more room than reading one photo.
CONTEXT = 16_384


def installed(folder: Path, model: str = DEFAULT_MODEL) -> bool:
    return llama_server(folder).is_file() and MODELS[model].downloaded(models_dir(folder))


def require_installed(conn: sqlite3.Connection, settings: Settings) -> None:
    """For endpoints: refuse before queueing work the model cannot do."""
    from lumen.vlm.pipeline import vlm_folder

    if not installed(vlm_folder(conn, settings)):
        raise LumenError("The local model is not installed (download it in Settings)")


def unread(conn: sqlite3.Connection, asset_ids: Sequence[int]) -> list[int]:
    """The photos among these the model has not read (with the current prompt)."""
    return [
        asset_id
        for asset_id in asset_ids
        if conn.execute(
            "SELECT 1 FROM media_descriptions WHERE asset_id = ? AND prompt_version >= ?",
            (asset_id, describing.PROMPT_VERSION),
        ).fetchone()
        is None
    ]


@contextmanager
def local_model(ctx: TaskContext, model: str = DEFAULT_MODEL) -> Iterator[object]:
    """The started model (a ``pipeline.Reader``), stopped afterwards."""
    from lumen.services.settings import get_settings
    from lumen.vlm import pipeline

    folder = pipeline.vlm_folder(ctx.conn, ctx.settings)
    if not installed(folder, model):
        raise PermanentTaskError("The local model is not installed (download it in Settings)")
    app = get_settings(ctx.conn)
    if app.ai_enabled:
        pipeline._unload_siglip(ctx.settings)
    reader = pipeline._reader_factory(folder, pipeline.GPU_RESERVE_MIB if app.ai_enabled else None)
    try:
        try:
            reader.start(model, CONTEXT)
        except ServerError as exc:
            raise PermanentTaskError(f"The local model could not start: {exc}") from exc
        yield reader
    finally:
        reader.stop()


def read_photos(
    ctx: TaskContext, reader: object, asset_ids: Sequence[int], step: int, total: int
) -> int:
    """Read these photos (progress from ``step``); returns the next step."""
    from lumen.vlm import pipeline

    for asset_id in asset_ids:
        ctx.progress(step, total)
        pipeline._read_one(ctx, reader, asset_id, DEFAULT_MODEL)  # type: ignore[arg-type]
        step += 1
    return step
