"""Background tasks: download the model, then embed and label every asset.

Images come from the cached 400px thumbnails (the models work at 224-384px), so
originals and RAW files are never decoded again.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from lumen.ai import labels as vocab
from lumen.ai.encoders import Encoder
from lumen.ai.engine import (
    DOWNLOAD_PATTERNS,
    cache_dir,
    download_size,
    get_engine,
    model_downloaded,
    torch_installed,
)
from lumen.ai.index import index
from lumen.ai.models import ModelSpec, get_spec
from lumen.db.connection import transaction, utc_now
from lumen.library.search import reindex_assets
from lumen.library.tags import get_or_create_tag
from lumen.media import thumbnails
from lumen.services.settings import get_settings
from lumen.tasks.runner import PermanentTaskError, TaskContext

logger = logging.getLogger(__name__)

AI_INDEX_TASK = "ai_index_assets"
AI_DOWNLOAD_TASK = "ai_download_model"
BATCH_SIZE = 32

_label_cache: dict[str, np.ndarray] = {}


def _directory_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.stat(os.path.join(root, name), follow_symlinks=False).st_size
    return total


def download_model(ctx: TaskContext) -> None:
    settings = get_settings(ctx.conn)
    spec = get_spec(str(ctx.payload.get("model_id") or settings.ai_model))
    if not torch_installed():
        raise PermanentTaskError("AI components are not installed (pip install -e .[ai])")

    if not model_downloaded(spec):
        if spec.backend == "siglip2":
            _download_hf(ctx, spec)
        else:
            # open_clip fetches its weights the first time the model is created.
            get_engine().encoder(spec.id)

    if settings.ai_enabled and settings.ai_model == spec.id:
        ctx.enqueue(AI_INDEX_TASK)


def _download_hf(ctx: TaskContext, spec: ModelSpec) -> None:
    import huggingface_hub

    total = download_size(spec)
    repo_dir = Path(cache_dir()) / f"models--{spec.name.replace('/', '--')}"
    error: list[BaseException] = []

    def run() -> None:
        try:
            huggingface_hub.snapshot_download(spec.name, allow_patterns=DOWNLOAD_PATTERNS)
        except BaseException as exc:  # reported on the task
            error.append(exc)

    worker = threading.Thread(target=run, name="model-download", daemon=True)
    worker.start()
    logger.info("model download started", extra={"model": spec.id, "bytes": total})
    while worker.is_alive():
        worker.join(1.0)
        # Blobs are content-addressed, so the folder size tracks progress (incl. partial files).
        ctx.progress(min(_directory_size(repo_dir), total), total)
    if error:
        raise error[0]
    ctx.progress(total, total, force=True)


def _label_matrix(encoder: Encoder) -> np.ndarray:
    """Average prompt embedding per label, for the current vocabulary."""
    key = f"{encoder.spec.id}:{vocab.LABELS_VERSION}"
    if key not in _label_cache:
        rows = []
        for prompts in vocab.prompts():
            vectors = encoder.encode_texts(prompts)
            mean = vectors.mean(axis=0)
            rows.append(mean / np.linalg.norm(mean))
        _label_cache[key] = np.stack(rows).astype(np.float32)
    return _label_cache[key]


def choose_labels(encoder: Encoder, vectors: np.ndarray) -> list[list[tuple[str, float]]]:
    """For each image vector, the (label, confidence) pairs to apply."""
    logits = (vectors @ _label_matrix(encoder).T) * encoder.logit_scale
    shares = np.exp(logits - logits.max(axis=1, keepdims=True))
    shares /= shares.sum(axis=1, keepdims=True)
    chosen: list[list[tuple[str, float]]] = []
    for row in shares:
        order = np.argsort(-row)[: vocab.MAX_LABELS]
        chosen.append(
            [
                (vocab.LABELS[i].name, float(row[i]))
                for i in order
                if row[i] >= vocab.SHARE_THRESHOLD
            ]
        )
    return chosen


def _pending(conn: sqlite3.Connection, model_id: str, after: int, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT a.id, c.fingerprint
        FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
             AND c.ingest_state = 'done' AND c.fingerprint IS NOT NULL
        LEFT JOIN embeddings e ON e.asset_id = a.id AND e.model_id = ?
        WHERE a.id > ?
          AND (e.asset_id IS NULL OR e.fingerprint != c.fingerprint OR e.labels_version < ?)
        ORDER BY a.id
        LIMIT ?
        """,
        (model_id, after, vocab.LABELS_VERSION, limit),
    ).fetchall()


def count_pending(conn: sqlite3.Connection, model_id: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
             AND c.ingest_state = 'done' AND c.fingerprint IS NOT NULL
        LEFT JOIN embeddings e ON e.asset_id = a.id AND e.model_id = ?
        WHERE e.asset_id IS NULL OR e.fingerprint != c.fingerprint OR e.labels_version < ?
        """,
        (model_id, vocab.LABELS_VERSION),
    ).fetchone()
    return int(row[0])


def index_assets(ctx: TaskContext) -> None:
    settings = get_settings(ctx.conn)
    if not settings.ai_enabled:
        return
    spec = get_spec(settings.ai_model)
    if not torch_installed():
        raise PermanentTaskError("AI components are not installed (pip install -e .[ai])")
    if not model_downloaded(spec):
        raise PermanentTaskError(f"Model {spec.id} has not been downloaded")

    total = count_pending(ctx.conn, spec.id)
    if total == 0:
        return
    engine = get_engine(ctx.settings.ai_idle_unload_s, ctx.settings.ai_device)
    encoder = engine.encoder(spec.id)
    done = 0
    last_id = 0
    started = time.monotonic()
    ctx.progress(0, total, force=True)

    while True:
        rows = _pending(ctx.conn, spec.id, last_id, BATCH_SIZE)
        if not rows:
            break
        last_id = int(rows[-1]["id"])
        batch: list[tuple[int, str, Image.Image]] = []
        for row in rows:
            image = _load_thumbnail(ctx, row["fingerprint"])
            if image is not None:
                batch.append((int(row["id"]), row["fingerprint"], image))
        if batch:
            vectors = encoder.encode_images([image for _, _, image in batch])
            chosen = choose_labels(encoder, vectors)
            _store(ctx.conn, spec.id, batch, vectors, chosen)
            index.invalidate(spec.id)
        engine.touch()
        done += len(rows)
        ctx.progress(done, max(total, done))

    logger.info(
        "ai indexing finished",
        extra={
            "model": spec.id,
            "assets": done,
            "seconds": round(time.monotonic() - started, 1),
            "device": encoder.device,
        },
    )


def _load_thumbnail(ctx: TaskContext, fingerprint: str) -> Image.Image | None:
    paths = thumbnails.rendition_paths(ctx.settings.cache_dir, fingerprint)
    for path in (paths.thumb, paths.preview):
        try:
            with Image.open(path) as image:
                return image.convert("RGB")
        except OSError:
            continue
    logger.warning("no rendition for ai indexing", extra={"fingerprint": fingerprint})
    return None


def _store(
    conn: sqlite3.Connection,
    model_id: str,
    batch: list[tuple[int, str, Image.Image]],
    vectors: np.ndarray,
    chosen: list[list[tuple[str, float]]],
) -> None:
    now = utc_now()
    tag_ids: dict[str, int] = {}
    with transaction(conn):
        for (asset_id, fingerprint, _), vector, labels in zip(batch, vectors, chosen, strict=True):
            if (
                conn.execute("SELECT 1 FROM media_assets WHERE id = ?", (asset_id,)).fetchone()
                is None
            ):
                continue  # deleted meanwhile
            conn.execute(
                """
                INSERT INTO embeddings
                    (asset_id, model_id, fingerprint, dim, vector, labels_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (asset_id, model_id) DO UPDATE SET
                    fingerprint = excluded.fingerprint, dim = excluded.dim,
                    vector = excluded.vector, labels_version = excluded.labels_version,
                    created_at = excluded.created_at
                """,
                (
                    asset_id, model_id, fingerprint, int(vector.shape[0]),
                    vector.astype(np.float16).tobytes(), vocab.LABELS_VERSION, now,
                ),
            )  # fmt: skip
            # AI labels are replaced; tags from the user or from files are left alone.
            conn.execute("DELETE FROM media_tags WHERE asset_id = ? AND source = 'ai'", (asset_id,))
            for name, confidence in labels:
                if name not in tag_ids:
                    tag_ids[name] = get_or_create_tag(conn, name)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO media_tags
                        (asset_id, tag_id, source, confidence, created_at)
                    VALUES (?, ?, 'ai', ?, ?)
                    """,
                    (asset_id, tag_ids[name], round(confidence, 4), now),
                )
        reindex_assets(conn, [asset_id for asset_id, _, _ in batch])
