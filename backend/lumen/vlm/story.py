"""A portfolio's travel story, written on this computer by the local model.

The model does not look at the photos again: it gets what it already read in each one
(description, text, keywords), with the capture times, the towns and the captions, in
order. Photos it has not read yet are read first. The story is kept like a cloud
analysis (``ai_analysis``, provider ``local``), tied to the portfolio.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any

from lumen.core.config import Settings
from lumen.core.errors import LumenError, NotFoundError
from lumen.db.connection import transaction, utc_now
from lumen.library.trips import spread
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskContext
from lumen.vlm import describe as describing
from lumen.vlm.models import DEFAULT_MODEL, MODELS, llama_server, models_dir
from lumen.vlm.server import ServerError

logger = logging.getLogger(__name__)

STORY_TASK = "vlm_collection_story"
PROVIDER = "local"
PROMPT_VERSION = 1
# Photos given to the model (spread over the trip when there are more).
MAX_PHOTOS = 80
MAX_TEXT = 160
MAX_TOKENS = 2048

LANGUAGES = {"zh-CN": "简体中文", "en": "English", "fr": "français"}


class StoryError(Exception):
    """The model did not write a story."""


def start(conn: sqlite3.Connection, settings: Settings, collection_id: int, language: str) -> int:
    """Queue the story; checks first that there is something to write about and a model."""
    from lumen.vlm.pipeline import vlm_folder

    if conn.execute("SELECT 1 FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
        raise NotFoundError("Collection not found", details={"id": collection_id})
    if not _photo_ids(conn, collection_id):
        raise LumenError("The portfolio has no photos to write about")
    folder = vlm_folder(conn, settings)
    if not llama_server(folder).is_file() or not MODELS[DEFAULT_MODEL].downloaded(
        models_dir(folder)
    ):
        raise LumenError("The local model is not installed (download it in Settings)")
    return queue.enqueue(
        conn,
        STORY_TASK,
        payload={"collection_id": collection_id, "language": language},
        unique=False,
    )


def _photo_ids(conn: sqlite3.Connection, collection_id: int) -> list[int]:
    """The portfolio's photos in capture order (undated ones last, in portfolio order)."""
    return [
        int(row[0])
        for row in conn.execute(
            """
            SELECT a.id FROM collection_items i
            JOIN media_assets a ON a.id = i.asset_id
            JOIN media_files c ON c.id = a.cover_file_id AND c.fingerprint IS NOT NULL
            WHERE i.collection_id = ? AND a.media_type = 'photo'
            ORDER BY a.capture_time IS NULL, a.capture_time, i.position
            """,
            (collection_id,),
        )
    ]


def _material(conn: sqlite3.Connection, collection_id: int, ids: Sequence[int]) -> list[str]:
    """One line per photo: when, where, the caption and what the model saw."""
    lines = []
    for number, asset_id in enumerate(ids, start=1):
        row = conn.execute(
            """
            SELECT a.capture_time, i.caption, p.city, p.city_zh, p.city_fr, p.country_code,
                   d.description, d.text, d.keywords
            FROM media_assets a
            JOIN collection_items i ON i.asset_id = a.id AND i.collection_id = ?
            LEFT JOIN media_places p ON p.asset_id = a.id
            LEFT JOIN media_descriptions d ON d.asset_id = a.id
            WHERE a.id = ?
            """,
            (collection_id, asset_id),
        ).fetchone()
        if row is None:
            continue
        parts = [f"{number}."]
        if row["capture_time"]:
            parts.append(row["capture_time"][:16].replace("T", " "))
        city = row["city_zh"] or row["city"]
        if city:
            parts.append(f"地点：{city}")
        if row["caption"]:
            parts.append(f"说明：{row['caption']}")
        if row["description"]:
            parts.append(f"画面：{row['description']}")
        text = " / ".join(line.strip() for line in (row["text"] or "").splitlines() if line.strip())
        if text:
            parts.append(f"文字：{text[:MAX_TEXT]}")
        keywords = json.loads(row["keywords"]) if row["keywords"] else []
        if keywords:
            parts.append("关键词：" + "、".join(keywords[:8]))
        lines.append(" · ".join(parts))
    return lines


def _prompt(collection: sqlite3.Row, lines: list[str], language: str) -> str:
    header = [f"作品集：{collection['name']}"]
    if collection["place"]:
        header.append(f"地点：{collection['place']}")
    if collection["start_date"]:
        header.append(f"日期：{collection['start_date']} – {collection['end_date'] or ''}")
    if collection["description"]:
        header.append(f"简介：{collection['description']}")
    return (
        "\n".join(header)
        + "\n\n下面按拍摄时间列出这次旅行的照片（每行一张：时间、地点、说明、画面内容、"
        "照片里的文字）：\n"
        + "\n".join(lines)
        + f"\n\n请用{LANGUAGES.get(language, '简体中文')}写一篇 300 到 500 字的旅行故事，"
        "用 Markdown：第一行是 # 标题，之后按时间顺序分几段（可以用 ## 小标题按天或按地点）。"
        "只根据上面的时间、地点、说明和画面内容来写，不要编造没有依据的具体事实"
        "（人名、店名、发生的事）；语气自然、有画面感。"
    )


def chat(base_url: str, prompt: str, *, timeout: float = 900) -> tuple[str, int, int]:
    """Ask the local server (OpenAI-compatible) for a text answer."""
    body = {
        "messages": [
            {"role": "system", "content": "你是 LUMEN Studio 的旅行写作助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": MAX_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer: dict[str, Any] = json.loads(response.read())
        text = str(answer["choices"][0]["message"]["content"] or "").strip()
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise StoryError(f"the model did not answer: {exc}") from exc
    if not text:
        raise StoryError("the model wrote nothing")
    usage = answer.get("usage") or {}
    return text, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


def write_story(ctx: TaskContext) -> dict[str, int]:
    from lumen.services.settings import get_settings
    from lumen.vlm import pipeline

    conn = ctx.conn
    collection_id = int(ctx.payload["collection_id"])
    language = str(ctx.payload.get("language") or "zh-CN")
    collection = conn.execute("SELECT * FROM collections WHERE id = ?", (collection_id,)).fetchone()
    if collection is None:
        raise PermanentTaskError("The portfolio was deleted")
    folder = pipeline.vlm_folder(conn, ctx.settings)
    if not llama_server(folder).is_file():
        raise PermanentTaskError("llama.cpp is not installed (download it in Settings)")
    if not MODELS[DEFAULT_MODEL].downloaded(models_dir(folder)):
        raise PermanentTaskError(f"Model {DEFAULT_MODEL} has not been downloaded")
    ids = spread(_photo_ids(conn, collection_id), MAX_PHOTOS)
    if not ids:
        raise PermanentTaskError("The portfolio has no photos to write about")
    unread = [
        asset_id
        for asset_id in ids
        if conn.execute(
            "SELECT 1 FROM media_descriptions WHERE asset_id = ? AND prompt_version >= ?",
            (asset_id, describing.PROMPT_VERSION),
        ).fetchone()
        is None
    ]
    # Steps: each unread photo, then the story itself.
    total = len(unread) + 1
    ctx.progress(0, total, force=True)

    app = get_settings(conn)
    if app.ai_enabled:
        pipeline._unload_siglip(ctx.settings)
    reader = pipeline._reader_factory(folder, pipeline.GPU_RESERVE_MIB if app.ai_enabled else None)
    try:
        try:
            reader.start(DEFAULT_MODEL)
        except ServerError as exc:
            raise PermanentTaskError(f"The local model could not start: {exc}") from exc
        for done, asset_id in enumerate(unread):
            ctx.progress(done, total)
            pipeline._read_one(ctx, reader, asset_id, DEFAULT_MODEL)
        ctx.progress(len(unread), total, force=True)
        prompt = _prompt(collection, _material(conn, collection_id, ids), language)
        try:
            text, prompt_tokens, output_tokens = reader.write(prompt)
        except StoryError as exc:
            raise PermanentTaskError(str(exc)) from exc
    finally:
        reader.stop()

    analysis_id = _store(conn, collection_id, language, ids, prompt, text, prompt_tokens,
                         output_tokens)  # fmt: skip
    ctx.progress(total, total, force=True)
    logger.info("travel story written", extra={"collection_id": collection_id, "photos": len(ids)})
    return {"analysis_id": analysis_id, "photos": len(ids), "read": len(unread)}


def _store(
    conn: sqlite3.Connection,
    collection_id: int,
    language: str,
    ids: Sequence[int],
    prompt: str,
    text: str,
    prompt_tokens: int,
    output_tokens: int,
) -> int:
    # Unique per run: writing again gives another version of the story.
    key = hashlib.sha256(f"{PROVIDER}:{prompt}:{utc_now()}".encode()).hexdigest()
    with transaction(conn):
        cursor = conn.execute(
            """
            INSERT INTO ai_analysis (kind, provider, model, prompt_version, language, cache_key,
                                     vision, result, data, input_tokens, output_tokens, created_at)
            VALUES ('story', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                PROVIDER, DEFAULT_MODEL, PROMPT_VERSION, language, key, text,
                json.dumps({"collection_id": collection_id}), prompt_tokens, output_tokens,
                utc_now(),
            ),
        )  # fmt: skip
        analysis_id = int(cursor.lastrowid or 0)
        conn.executemany(
            "INSERT INTO ai_analysis_assets (analysis_id, asset_id, position) VALUES (?, ?, ?)",
            [(analysis_id, asset_id, i) for i, asset_id in enumerate(ids)],
        )
    return analysis_id
