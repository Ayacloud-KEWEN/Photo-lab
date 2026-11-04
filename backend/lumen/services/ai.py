"""Local AI: status, semantic text search and similar-photo search."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from lumen.ai import pipeline
from lumen.ai.engine import device_info, get_engine, model_downloaded, torch_installed
from lumen.ai.index import index
from lumen.ai.models import MODELS, get_spec
from lumen.core.config import Settings
from lumen.core.errors import LumenError, NotFoundError
from lumen.db.connection import Database
from lumen.schemas.ai import AIStatus, CloudStatus, LocalAIStatus, ModelInfo, SemanticPage
from lumen.schemas.assets import AssetQuery
from lumen.services import assets
from lumen.services.settings import get_settings

logger = logging.getLogger(__name__)
_warming = threading.Lock()

MAX_CANDIDATES = 200_000

#: Text-to-image cosine similarity above which a result counts as a likely match.
#: SigLIP2 so400m: true matches score ~0.10-0.13, unrelated photos ~0.03-0.06
#: (measured on sample photos with Chinese and English queries).
TEXT_RELEVANCE = {"siglip2": 0.075, "open_clip": 0.2}
#: Image-to-image cosine similarity for "similar photos".
IMAGE_RELEVANCE = 0.6


class AINotReadyError(LumenError):
    status_code = 409
    code = "ai_not_ready"


def status(conn: sqlite3.Connection, settings: Settings) -> AIStatus:
    from lumen.ai import cloud

    app = get_settings(conn)
    spec = get_spec(app.ai_model)
    device = device_info(settings.ai_device)
    indexed = conn.execute(
        "SELECT COUNT(*) FROM embeddings WHERE model_id = ?", (spec.id,)
    ).fetchone()[0]
    total = conn.execute(
        """
        SELECT COUNT(*) FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
             AND c.ingest_state = 'done' AND c.fingerprint IS NOT NULL
        """
    ).fetchone()[0]
    try:
        has_key = cloud.get_api_key() is not None
    except LumenError:
        has_key = False
    return AIStatus(
        local=LocalAIStatus(
            installed=torch_installed(),
            device=device.device,  # type: ignore[arg-type]
            device_name=device.name,
            memory_gb=device.memory_gb,
            enabled=app.ai_enabled,
            model_id=spec.id,
            model_downloaded=device.available and model_downloaded(spec),
            model_loaded=get_engine().loaded_model == spec.id if device.available else False,
            indexed=int(indexed),
            total=int(total),
            models=[
                ModelInfo(
                    id=m.id,
                    display_name=m.display_name,
                    backend=m.backend,
                    multilingual=m.multilingual,
                    approx_download_gb=m.approx_download_gb,
                    downloaded=device.available and model_downloaded(m),
                )
                for m in MODELS.values()
            ],
        ),
        cloud=CloudStatus(
            enabled=app.cloud_enabled,
            provider="deepseek",
            model=app.cloud_model,
            base_url=app.cloud_base_url,
            has_key=has_key,
            include_location_default=app.cloud_include_location,
        ),
    )


def _ready_model(conn: sqlite3.Connection) -> str:
    app = get_settings(conn)
    if not app.ai_enabled:
        raise AINotReadyError("AI search is turned off in Settings")
    if not torch_installed():
        raise AINotReadyError("AI components are not installed")
    spec = get_spec(app.ai_model)
    if not model_downloaded(spec):
        raise AINotReadyError(f"Model {spec.id} has not been downloaded")
    return spec.id


def _allowed(conn: sqlite3.Connection, query: AssetQuery) -> list[int] | None:
    if not assets.has_filters(query):
        return None
    return assets.list_asset_ids(conn, query, limit=MAX_CANDIDATES)


def _page(
    conn: sqlite3.Connection, model_id: str, hits: list[tuple[int, float]], threshold: float
) -> SemanticPage:
    summaries = assets.summaries_by_ids(conn, [asset_id for asset_id, _ in hits])
    scores = dict(hits)
    ranked = [round(scores[item.id], 4) for item in summaries]
    return SemanticPage(
        items=summaries,
        scores=ranked,
        relevant_count=sum(1 for score in ranked if score >= threshold),
        model_id=model_id,
    )


def warm_up(conn: sqlite3.Connection, settings: Settings, db_path: Path) -> bool:
    """Load the model and the vectors in the background (the AI search page opened): the
    first search otherwise waits ~20 s. Returns False when the local AI is not ready."""
    try:
        model_id = _ready_model(conn)
    except LumenError:
        return False

    if not _warming.acquire(blocking=False):
        return True  # already loading

    def load() -> None:
        try:
            get_engine(settings.ai_idle_unload_s, settings.ai_device).encoder(model_id)
            with Database(db_path).session() as own:
                index.matrix(own, model_id)
        except Exception:
            logger.exception("AI warm-up failed")
        finally:
            _warming.release()

    threading.Thread(target=load, name="ai-warm-up", daemon=True).start()
    return True


def search(
    conn: sqlite3.Connection, settings: Settings, text: str, query: AssetQuery, limit: int
) -> SemanticPage:
    """Assets best matching a natural-language description (any language for SigLIP2)."""
    model_id = _ready_model(conn)
    encoder = get_engine(settings.ai_idle_unload_s, settings.ai_device).encoder(model_id)
    vector = encoder.encode_texts([text.strip()])[0]
    hits = index.search(conn, model_id, vector, limit=limit, allowed=_allowed(conn, query))
    return _page(conn, model_id, hits, TEXT_RELEVANCE.get(get_spec(model_id).backend, 0.2))


def similar(conn: sqlite3.Connection, asset_id: int, query: AssetQuery, limit: int) -> SemanticPage:
    """Assets that look like ``asset_id`` (cosine similarity of image embeddings)."""
    model_id = _ready_model(conn)
    vector = index.vector_of(conn, model_id, asset_id)
    if vector is None:
        if conn.execute("SELECT 1 FROM media_assets WHERE id = ?", (asset_id,)).fetchone() is None:
            raise NotFoundError("Asset not found", details={"id": asset_id})
        raise AINotReadyError("This photo has not been analysed by the AI model yet")
    hits = index.search(
        conn, model_id, vector, limit=limit, allowed=_allowed(conn, query), exclude=asset_id
    )
    return _page(conn, model_id, hits, IMAGE_RELEVANCE)


def pending_count(conn: sqlite3.Connection) -> int:
    return pipeline.count_pending(conn, get_settings(conn).ai_model)
