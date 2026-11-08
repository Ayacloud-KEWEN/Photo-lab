"""Local vision-language model: status, requests and the stored descriptions (ADR-038)."""

from __future__ import annotations

import json
import sqlite3

from lumen.core.config import Settings
from lumen.core.errors import LumenError
from lumen.schemas.vlm import AssetDescription, VlmModelInfo, VlmStatus
from lumen.services.settings import get_settings
from lumen.tasks import queue
from lumen.vlm import pipeline
from lumen.vlm.describe import PROMPT_VERSION
from lumen.vlm.models import DEFAULT_MODEL, FINE_MODEL, MODELS, llama_server, models_dir


def status(conn: sqlite3.Connection, settings: Settings) -> VlmStatus:
    app = get_settings(conn)
    folder = pipeline.vlm_folder(conn, settings)
    described = conn.execute(
        "SELECT COUNT(*) FROM media_descriptions WHERE prompt_version = ?", (PROMPT_VERSION,)
    ).fetchone()[0]
    requested = conn.execute("SELECT COUNT(*) FROM vlm_requests").fetchone()[0]
    to_read = len(pipeline.library_order(conn, app.vlm_scope)) if app.vlm_enabled else 0
    roles = {DEFAULT_MODEL: "default", FINE_MODEL: "fine"}
    return VlmStatus(
        enabled=app.vlm_enabled,
        scope=app.vlm_scope,
        folder=str(folder),
        runtime_installed=llama_server(folder).is_file(),
        models=[
            VlmModelInfo(
                id=spec.id,
                label=spec.label,
                role=roles[spec.id],  # type: ignore[arg-type]
                downloaded=spec.downloaded(models_dir(folder)),
                size_gb=spec.size_gb,
                licence=spec.licence,
                repo=spec.repo,
            )
            for spec in (MODELS[DEFAULT_MODEL], MODELS[FINE_MODEL])
        ],
        described=int(described),
        requested=int(requested),
        to_read=to_read,
    )


def describe_later(
    conn: sqlite3.Connection, asset_ids: list[int], *, fine: bool
) -> tuple[int, int]:
    """Queue photos to be read first; returns (photos queued, task id)."""
    queued = pipeline.request(conn, asset_ids, fine=fine)
    if queued == 0:
        raise LumenError("Only photos can be read by the local model")
    return queued, queue.enqueue(conn, pipeline.VLM_TASK)


def start_download(conn: sqlite3.Connection, model: str) -> int:
    if model not in (DEFAULT_MODEL, FINE_MODEL):
        raise LumenError(f"Unknown model {model}")
    return queue.enqueue(conn, pipeline.VLM_DOWNLOAD_TASK, payload={"model": model}, unique=False)


def description_of(conn: sqlite3.Connection, asset_id: int) -> AssetDescription | None:
    row = conn.execute(
        "SELECT * FROM media_descriptions WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    if row is None:
        return None
    spec = MODELS.get(row["model"])
    return AssetDescription(
        description=row["description"],
        text=row["text"],
        keywords=json.loads(row["keywords"]),
        model=row["model"],
        model_label=spec.label if spec else row["model"],
        fine=row["model"] == FINE_MODEL,
        truncated=bool(row["truncated"]),
        created_at=row["created_at"],
    )
