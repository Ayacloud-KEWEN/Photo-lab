"""Running the local model for a text task (captions, questions): checks, start and stop.

The model reads the photos it has not read yet, then answers prompts built from what it
read. Tests replace the model with ``pipeline.set_reader_factory``.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

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


# A model kept running for a while after a question, so the next one starts at once.
_warm_lock = threading.Lock()
_warm: dict[str, Any] = {}


def release_warm() -> None:
    """Stop a model kept running (before anything else starts one: there is room for one)."""
    with _warm_lock:
        reader, timer = _warm.pop("reader", None), _warm.pop("timer", None)
        _warm.clear()
    if timer is not None:
        timer.cancel()
    if reader is not None:
        reader.stop()


@contextmanager
def local_model(
    ctx: TaskContext, model: str = DEFAULT_MODEL, *, keep_warm_s: float = 0
) -> Iterator[Any]:
    """The started model (a ``pipeline.Reader``), stopped afterwards, or ``keep_warm_s``
    later when the next task can reuse it."""
    from lumen.services.settings import get_settings
    from lumen.vlm import pipeline

    folder = pipeline.vlm_folder(ctx.conn, ctx.settings)
    if not installed(folder, model):
        raise PermanentTaskError("The local model is not installed (download it in Settings)")
    with _warm_lock:
        reuse = _warm.get("model") == model and _warm.get("factory") is pipeline._reader_factory
        reader = _warm.pop("reader", None) if reuse else None
        timer = _warm.pop("timer", None) if reuse else None
    if timer is not None:
        timer.cancel()
    if reader is None:
        release_warm()
        app = get_settings(ctx.conn)
        if app.ai_enabled:
            pipeline._unload_siglip(ctx.settings)
        reserve = pipeline.GPU_RESERVE_MIB if app.ai_enabled else None
        reader = pipeline._reader_factory(folder, reserve)
        try:
            reader.start(model, CONTEXT)
        except ServerError as exc:
            reader.stop()
            raise PermanentTaskError(f"The local model could not start: {exc}") from exc
    keep = False
    try:
        yield reader
        keep = keep_warm_s > 0
    finally:
        if keep:
            timer = threading.Timer(keep_warm_s, release_warm)
            timer.daemon = True
            with _warm_lock:
                _warm.update(
                    reader=reader, model=model, timer=timer, factory=pipeline._reader_factory
                )
            timer.start()
        else:
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
