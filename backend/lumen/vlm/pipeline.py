"""Background tasks: read photos with the local vision-language model, and download it.

Reading a photo takes seconds (not milliseconds like the SigLIP index), so the library is
read in order of interest and the task runs at background priority, giving way to
scans, imports and exports (ADR-030):

1. photos the user asked for (the "fine" requests with the slower, careful model first);
2. favourites, 3+ stars, photos in collections and photos taken in the last 30 days
   (taken, not imported: a library imported this week would be "recent" as a whole);
3. photos SigLIP thinks contain text (signs, menus, tickets, documents);
4. with the "all" scope, the rest of the library, newest first.

The model runs in a llama-server process started for the task and stopped after it.
SigLIP is unloaded first and llama.cpp keeps room for it (``GPU_RESERVE_MIB``), so a
search while photos are being read still finds memory on the GPU.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from PIL import Image

from lumen.core.config import Settings
from lumen.db.connection import transaction, utc_now
from lumen.library.search import reindex_assets
from lumen.tasks.runner import PermanentTaskError, TaskContext
from lumen.vlm import describe as describing
from lumen.vlm.models import (
    DEFAULT_MODEL,
    FINE_MODEL,
    LLAMA_DOWNLOADS,
    MODELS,
    llama_dir,
    llama_server,
    models_dir,
)
from lumen.vlm.server import LlamaServer, ServerError

logger = logging.getLogger(__name__)

VLM_TASK = "vlm_describe_assets"
VLM_DOWNLOAD_TASK = "vlm_download"
RECENT_DAYS = 30
TEXT_QUERY = "a photo with readable text: a sign, a menu, a ticket, a document or a screenshot"
TEXT_CANDIDATES = 20_000
# GPU memory llama.cpp leaves free for SigLIP (AI search) while it runs.
GPU_RESERVE_MIB = 3072


def vlm_folder(conn: sqlite3.Connection, settings: Settings) -> Path:
    from lumen.services.settings import get_settings

    configured = get_settings(conn).vlm_folder
    return Path(configured) if configured else settings.data_dir / "vlm"


# --- The model as the task uses it (tests replace it) ----------------------------------------


class Reader(Protocol):
    def start(self, model_id: str) -> None: ...
    def read(self, image: Image.Image) -> describing.Description: ...
    def stop(self) -> None: ...


class LlamaReader:
    def __init__(self, folder: Path, reserve_mib: int | None) -> None:
        self.folder = folder
        self.reserve_mib = reserve_mib
        self.server: LlamaServer | None = None

    def start(self, model_id: str) -> None:
        spec = MODELS[model_id]
        files = spec.files(models_dir(self.folder))
        if self.reserve_mib:
            files = dataclasses.replace(
                files, args=(*files.args, "--fit-target", str(self.reserve_mib))
            )
        log = self.folder / "logs" / f"{model_id}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.server = LlamaServer(llama_server(self.folder), files, log_path=log)
        self.server.start()

    def read(self, image: Image.Image) -> describing.Description:
        assert self.server is not None
        return describing.describe(self.server.url, image)

    def stop(self) -> None:
        if self.server is not None:
            self.server.stop()
            self.server = None


ReaderFactory = Callable[[Path, int | None], Reader]
_reader_factory: ReaderFactory = LlamaReader


def set_reader_factory(factory: ReaderFactory | None) -> None:
    """Tests: read photos with a fake model."""
    global _reader_factory
    _reader_factory = factory or LlamaReader


# --- What to read, in order --------------------------------------------------------------------

_READABLE = """
    FROM media_assets a
    JOIN media_files c ON c.id = a.cover_file_id
         AND c.status = 'present' AND c.ingest_state = 'done' AND c.fingerprint IS NOT NULL
    JOIN storage_roots r ON r.id = c.storage_root_id AND r.status != 'offline'
    LEFT JOIN media_descriptions d ON d.asset_id = a.id
    WHERE a.media_type = 'photo'
"""
_NOT_READ = f"(d.asset_id IS NULL OR d.prompt_version < {describing.PROMPT_VERSION})"


def requested(conn: sqlite3.Connection, *, fine: bool) -> list[int]:
    """Photos the user asked to have read with the default (or the fine) model."""
    return [
        int(row[0])
        for row in conn.execute(
            f"SELECT a.id {_READABLE} AND a.id IN "
            "(SELECT asset_id FROM vlm_requests WHERE fine = ?) "
            "ORDER BY (SELECT requested_at FROM vlm_requests q WHERE q.asset_id = a.id), a.id",
            (int(fine),),
        )
    ]


def library_order(
    conn: sqlite3.Connection, scope: str, text_ranked: list[int] | None = None
) -> list[int]:
    """Photos not read yet, most interesting first (tiers 2-4 above)."""
    since = (datetime.now(UTC) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    priority = [
        int(row[0])
        for row in conn.execute(
            f"""
            SELECT a.id {_READABLE} AND {_NOT_READ}
              AND (a.is_favorite = 1 OR a.rating >= 3 OR a.capture_time >= ?
                   OR EXISTS (SELECT 1 FROM collection_items ci WHERE ci.asset_id = a.id))
            ORDER BY a.is_favorite DESC, a.rating DESC, a.capture_time DESC, a.id DESC
            """,
            (since,),
        )
    ]
    rest = [
        int(row[0])
        for row in conn.execute(
            f"SELECT a.id {_READABLE} AND {_NOT_READ} ORDER BY a.capture_time DESC, a.id DESC"
        )
    ]
    unread = set(rest)  # the ranking may be older than the last photos read
    ranked = [asset_id for asset_id in text_ranked or [] if asset_id in unread]
    order = list(dict.fromkeys([*priority, *ranked]))
    if scope == "all":
        order = list(dict.fromkeys([*order, *rest]))
    return order


def _text_ranked(conn: sqlite3.Connection, settings: Settings) -> list[int]:
    """Unread photos SigLIP finds likely to contain text (empty without the local AI)."""
    from lumen.ai.engine import get_engine, model_downloaded, torch_installed
    from lumen.ai.index import index
    from lumen.ai.models import get_spec
    from lumen.services.ai import TEXT_RELEVANCE
    from lumen.services.settings import get_settings

    app = get_settings(conn)
    spec = get_spec(app.ai_model)
    if not (app.ai_enabled and torch_installed() and model_downloaded(spec)):
        return []
    unread = [int(row[0]) for row in conn.execute(f"SELECT a.id {_READABLE} AND {_NOT_READ}")]
    if not unread:
        return []
    try:
        engine = get_engine(settings.ai_idle_unload_s, settings.ai_device)
        vector = engine.encoder(spec.id).encode_texts([TEXT_QUERY])[0]
        hits = index.search(conn, spec.id, vector, limit=TEXT_CANDIDATES, allowed=unread)
    except Exception:  # the ranking is a nicety: never stop reading because of it
        logger.exception("could not rank photos with text")
        return []
    threshold = TEXT_RELEVANCE.get(spec.backend, 0.2)
    return [asset_id for asset_id, score in hits if score >= threshold]


def _unload_siglip(settings: Settings) -> None:
    """Free the GPU for llama.cpp (SigLIP reloads on the next search, in the room left)."""
    from lumen.ai.engine import get_engine

    get_engine(settings.ai_idle_unload_s, settings.ai_device).unload()


# --- The task ---------------------------------------------------------------------------------


def describe_assets(ctx: TaskContext) -> dict[str, int]:
    from lumen.services.settings import get_settings

    conn = ctx.conn
    app = get_settings(conn)
    if not app.vlm_enabled and not _request_ids(conn):
        return {"described": 0}
    folder = vlm_folder(conn, ctx.settings)
    if not llama_server(folder).is_file():
        raise PermanentTaskError("llama.cpp is not installed (download it in Settings)")
    ranked = _text_ranked(conn, ctx.settings) if app.vlm_enabled else []
    if app.ai_enabled:
        _unload_siglip(ctx.settings)
    reader = _reader_factory(folder, GPU_RESERVE_MIB if app.ai_enabled else None)
    running: str | None = None
    described = failed = 0
    try:
        while True:
            plan = _plan(conn, app.vlm_enabled, app.vlm_scope, ranked)
            total = sum(len(ids) for _, ids in plan)
            if total == 0:
                break
            for model_id, ids in plan:
                if ids and not MODELS[model_id].downloaded(models_dir(folder)):
                    raise PermanentTaskError(f"Model {model_id} has not been downloaded")
            known = _request_ids(conn)
            done = 0
            ctx.progress(0, total, force=True)
            asked_more = False
            for model_id, ids in plan:
                if not ids:
                    continue
                if running != model_id:
                    reader.stop()
                    try:
                        reader.start(model_id)
                    except ServerError as exc:
                        raise PermanentTaskError(f"The local model could not start: {exc}") from exc
                    running = model_id
                for asset_id in ids:
                    ctx.progress(done, total)
                    if _request_ids(conn) - known:  # the user asked for more: those first
                        asked_more = True
                        break
                    outcome = _read_one(ctx, reader, asset_id, model_id)
                    described += outcome == "ok"
                    failed += outcome == "failed"
                    done += 1
                if asked_more:
                    break
            if not asked_more:
                ctx.progress(done, total, force=True)
                break
    finally:
        reader.stop()
    logger.info("photos read by the local model", extra={"described": described, "failed": failed})
    return {"described": described, "failed": failed}


def _request_ids(conn: sqlite3.Connection) -> set[int]:
    return {int(row[0]) for row in conn.execute("SELECT asset_id FROM vlm_requests")}


def _plan(
    conn: sqlite3.Connection, enabled: bool, scope: str, ranked: list[int]
) -> list[tuple[str, list[int]]]:
    """(model, photos) to read now: what the user asked for with the careful model, then
    with the default model what they asked for and (when enabled) the library in order."""
    fine_ids = requested(conn, fine=True)
    default_ids = requested(conn, fine=False)
    if enabled:
        default_ids = list(dict.fromkeys([*default_ids, *library_order(conn, scope, ranked)]))
    fine_set = set(fine_ids)
    return [(FINE_MODEL, fine_ids), (DEFAULT_MODEL, [i for i in default_ids if i not in fine_set])]


def _read_one(ctx: TaskContext, reader: Reader, asset_id: int, model_id: str) -> str:
    from lumen.services.assets import RenditionUnavailableError, rendition_path

    row = ctx.conn.execute(
        "SELECT c.fingerprint FROM media_assets a JOIN media_files c ON c.id = a.cover_file_id "
        "WHERE a.id = ?",
        (asset_id,),
    ).fetchone()
    if row is None:
        return "skipped"  # deleted meanwhile
    try:
        path = rendition_path(
            ctx.conn, ctx.settings.cache_dir, asset_id, "preview",
            ffmpeg=ctx.settings.tool("ffmpeg"), ffprobe=ctx.settings.tool("ffprobe"),
        )  # fmt: skip
        with Image.open(path) as opened:
            image = opened.convert("RGB")
    except (RenditionUnavailableError, OSError) as exc:
        logger.warning("no image to read", extra={"asset_id": asset_id, "error": str(exc)})
        return "skipped"
    try:
        result = reader.read(image)
    except describing.DescribeError as exc:
        # Stored empty, so a photo the model cannot read is not retried on every run.
        logger.warning("photo not read", extra={"asset_id": asset_id, "error": str(exc)})
        result = describing.Description("", "", (), 0, 0, 0.0)
        store(ctx.conn, asset_id, row["fingerprint"], model_id, result)
        return "failed"
    store(ctx.conn, asset_id, row["fingerprint"], model_id, result)
    return "ok"


def store(
    conn: sqlite3.Connection,
    asset_id: int,
    fingerprint: str,
    model_id: str,
    result: describing.Description,
) -> None:
    with transaction(conn):
        if conn.execute("SELECT 1 FROM media_assets WHERE id = ?", (asset_id,)).fetchone() is None:
            return
        conn.execute(
            """
            INSERT INTO media_descriptions (asset_id, fingerprint, model, prompt_version,
                description, text, keywords, truncated, seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (asset_id) DO UPDATE SET
                fingerprint = excluded.fingerprint, model = excluded.model,
                prompt_version = excluded.prompt_version, description = excluded.description,
                text = excluded.text, keywords = excluded.keywords,
                truncated = excluded.truncated, seconds = excluded.seconds,
                created_at = excluded.created_at
            """,
            (
                asset_id, fingerprint, model_id, describing.PROMPT_VERSION, result.description,
                result.text, json.dumps(list(result.keywords), ensure_ascii=False),
                int(result.truncated), round(result.seconds, 2), utc_now(),
            ),
        )  # fmt: skip
        # A careful reading asked for meanwhile is still to do after a default one.
        conn.execute(
            "DELETE FROM vlm_requests WHERE asset_id = ? AND (fine = 0 OR ?)",
            (asset_id, int(model_id == FINE_MODEL)),
        )
        reindex_assets(conn, [asset_id])


def request(conn: sqlite3.Connection, asset_ids: list[int], *, fine: bool) -> int:
    """Put photos first in line (again, if already read); returns how many were queued."""
    now = utc_now()
    queued = 0
    with transaction(conn):
        for asset_id in dict.fromkeys(asset_ids):
            photo = conn.execute(
                "SELECT 1 FROM media_assets WHERE id = ? AND media_type = 'photo'", (asset_id,)
            ).fetchone()
            if photo is None:
                continue
            conn.execute(
                "INSERT INTO vlm_requests (asset_id, fine, requested_at) VALUES (?, ?, ?) "
                "ON CONFLICT (asset_id) DO UPDATE SET fine = excluded.fine, "
                "requested_at = excluded.requested_at",
                (asset_id, int(fine), now),
            )
            # Read again even if read before (e.g. now with the fine model).
            conn.execute(
                "UPDATE media_descriptions SET prompt_version = 0 WHERE asset_id = ?", (asset_id,)
            )
            queued += 1
    return queued


# --- Downloading llama.cpp and a model -----------------------------------------------------------

_CHUNK = 4 * 1024 * 1024


def download(ctx: TaskContext) -> dict[str, str]:
    """Download llama.cpp (if missing) and the model in ``payload["model"]``, resumably."""
    model_id = str(ctx.payload.get("model", DEFAULT_MODEL))
    if model_id not in MODELS:
        raise PermanentTaskError(f"Unknown model {model_id}")
    spec = MODELS[model_id]
    folder = vlm_folder(ctx.conn, ctx.settings)
    jobs: list[tuple[str, Path]] = []
    if not llama_server(folder).is_file():
        jobs += [(url, llama_dir(folder) / Path(url).name) for url in LLAMA_DOWNLOADS]
    target = models_dir(folder) / spec.folder
    jobs += [
        (f"https://huggingface.co/{spec.repo}/resolve/main/{name}", target / name)
        for name in spec.file_names()
        if not (target / name).is_file()
    ]
    sizes = [_remote_size(url) for url, _ in jobs]
    total = sum(sizes)
    done = 0
    ctx.progress(0, total // 1_000_000, force=True)
    for (url, path), size in zip(jobs, sizes, strict=True):
        done = _fetch(ctx, url, path, size, done, total)
    for zipped in sorted(llama_dir(folder).glob("*.zip")):
        with zipfile.ZipFile(zipped) as archive:
            archive.extractall(llama_dir(folder))
        zipped.unlink()
    if not llama_server(folder).is_file():
        raise PermanentTaskError("llama-server.exe is missing from the llama.cpp download")
    return {"model": model_id}


def _remote_size(url: str) -> int:
    request_ = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request_, timeout=60) as response:
            return int(response.headers.get("Content-Length") or 0)
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def _fetch(ctx: TaskContext, url: str, path: Path, size: int, done: int, total: int) -> int:
    """Download ``url`` to ``path`` (resuming a ``.part`` file); returns bytes done overall."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    try:
        request_ = urllib.request.Request(url, headers=headers)
        with (
            urllib.request.urlopen(request_, timeout=60) as response,
            part.open("ab" if have and response.status == 206 else "wb") as out,
        ):
            if response.status != 206:
                have = 0
            while chunk := response.read(_CHUNK):
                out.write(chunk)
                have += len(chunk)
                ctx.progress((done + have) // 1_000_000, max(total, done + have) // 1_000_000)
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"download failed ({Path(url).name}): {exc}") from exc  # retried
    if size and have < size:
        raise RuntimeError(f"download incomplete ({Path(url).name})")
    part.replace(path)
    return done + have
