"""A portfolio's travel story, written from what the local model read in its photos.

A trip can have thousands of photos: far more than the model can take in at once. So the
story is written the way a person would write it:

1. Pick the photos that tell each day: favourites, picks, high ratings, captioned photos,
   photos with text in them (signs, menus, tickets) and sharp ones; of a burst only the
   best is kept. At most ``PER_DAY`` a day, so only those need to be read.
2. Write notes for each day, one request per day (each fits in the context).
3. Write the story from all the notes, with the chosen writer: either local model, or
   DeepSeek, which then gets the notes only (no photo, no coordinates), after the user
   has seen them.

The model does not look at the photos again: it gets what it read in each one
(description, text, keywords), with the capture times, the towns and the captions. Notes
and stories are kept like cloud analyses (``ai_analysis``), tied to the portfolio; the
notes can be reused to write the story again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from lumen.core.config import Settings
from lumen.core.errors import LumenError, NotFoundError
from lumen.db.connection import transaction, utc_now
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskContext
from lumen.vlm import describe as describing
from lumen.vlm.models import DEFAULT_MODEL, FINE_MODEL, MODELS, llama_server, models_dir
from lumen.vlm.server import ServerError

logger = logging.getLogger(__name__)

STORY_TASK = "vlm_collection_story"
PROMPT_VERSION = 2
Writer = Literal["qwen3.6-35b-a3b", "qwen3.8-27b", "deepseek"]
WRITERS: tuple[str, ...] = (DEFAULT_MODEL, FINE_MODEL, "deepseek")
# The day notes and the story need more room than reading one photo.
CONTEXT = 16_384
PER_DAY = 20
BURST_S = 90  # photos taken closer together than this are one moment
MAX_TEXT = 160
NOTE_TOKENS = 600
LANGUAGES = {"zh-CN": "简体中文", "en": "English", "fr": "français"}


class StoryError(Exception):
    """The model did not write."""


@dataclass
class Day:
    number: int
    date: str  # YYYY-MM-DD, "" for undated photos
    asset_ids: list[int]
    places: list[str] = field(default_factory=list)
    text: str = ""


# --- Starting -----------------------------------------------------------------------------


def _installed(folder: Any, model: str) -> bool:
    return llama_server(folder).is_file() and MODELS[model].downloaded(models_dir(folder))


def start(
    conn: sqlite3.Connection,
    settings: Settings,
    collection_id: int,
    language: str,
    writer: str = DEFAULT_MODEL,
    notes_from: int | None = None,
) -> int:
    """Queue the story; checks first that there is something to write about and a model."""
    from lumen.vlm.pipeline import vlm_folder

    if conn.execute("SELECT 1 FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
        raise NotFoundError("Collection not found", details={"id": collection_id})
    if not _rows(conn, collection_id):
        raise LumenError("The portfolio has no photos to write about")
    if writer not in WRITERS:
        raise LumenError(f"Unknown writer {writer}")
    folder = vlm_folder(conn, settings)
    if not _installed(folder, DEFAULT_MODEL):
        raise LumenError("The local model is not installed (download it in Settings)")
    if writer == FINE_MODEL and not _installed(folder, FINE_MODEL):
        raise LumenError(f"Model {FINE_MODEL} has not been downloaded (see Settings)")
    if notes_from is not None:
        notes_of(conn, collection_id, notes_from)  # must exist
    return queue.enqueue(
        conn,
        STORY_TASK,
        payload={
            "collection_id": collection_id, "language": language, "writer": writer,
            "notes_from": notes_from,
        },
        unique=False,
    )  # fmt: skip


# --- Picking the photos of each day ----------------------------------------------------------


def _rows(conn: sqlite3.Connection, collection_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT a.id, a.capture_time, a.rating, a.is_favorite, a.cull_flag, i.caption,
               q.score AS quality, COALESCE(d.text, '') != '' AS has_text
        FROM collection_items i
        JOIN media_assets a ON a.id = i.asset_id
        JOIN media_files c ON c.id = a.cover_file_id AND c.fingerprint IS NOT NULL
        LEFT JOIN media_quality q ON q.asset_id = a.id
        LEFT JOIN media_descriptions d ON d.asset_id = a.id
        WHERE i.collection_id = ? AND a.media_type = 'photo' AND a.cull_flag != 'reject'
        ORDER BY a.capture_time IS NULL, a.capture_time, i.position
        """,
        (collection_id,),
    ).fetchall()


def _worth(row: sqlite3.Row) -> float:
    """How much a photo tells: what the user marked first, then text and sharpness."""
    return float(
        3.0 * bool(row["is_favorite"])
        + 2.0 * (row["cull_flag"] == "pick")
        + float(row["rating"] or 0)
        + 2.0 * bool(row["caption"])
        + 1.5 * bool(row["has_text"])
        + float(row["quality"] or 0.5)
    )


def _seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None).timestamp()
    except ValueError:
        return None


def pick_days(rows: Sequence[sqlite3.Row], per_day: int = PER_DAY) -> list[Day]:
    """The photos of each day that tell it best, in capture order (undated ones last)."""
    by_date: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_date.setdefault((row["capture_time"] or "")[:10], []).append(row)
    days: list[Day] = []
    for date in sorted(by_date, key=lambda d: (d == "", d)):
        # A burst (photos seconds apart) is one moment: keep its best photo.
        moments: list[list[sqlite3.Row]] = []
        last: float | None = None
        for row in by_date[date]:
            taken = _seconds(row["capture_time"])
            if moments and taken is not None and last is not None and taken - last < BURST_S:
                moments[-1].append(row)
            else:
                moments.append([row])
            last = taken
        best = [max(moment, key=_worth) for moment in moments]
        chosen = sorted(best, key=_worth, reverse=True)[:per_day]
        keep = {int(row["id"]) for row in chosen}
        ids = [int(row["id"]) for row in by_date[date] if int(row["id"]) in keep]
        days.append(Day(number=len(days) + 1, date=date, asset_ids=ids))
    return days


# --- What the model is given -------------------------------------------------------------------


def _material(conn: sqlite3.Connection, collection_id: int, day: Day) -> list[str]:
    """One line per photo: when, where, the caption and what the model saw."""
    lines = []
    for asset_id in day.asset_ids:
        row = conn.execute(
            """
            SELECT a.capture_time, i.caption, p.city, p.city_zh,
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
        parts = []
        if row["capture_time"]:
            parts.append(row["capture_time"][11:16])
        city = row["city_zh"] or row["city"]
        if city:
            parts.append(f"地点：{city}")
            if city not in day.places:
                day.places.append(city)
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
        if len(parts) > 1:
            lines.append("- " + " · ".join(parts))
    return lines


def _header(collection: sqlite3.Row) -> str:
    header = [f"作品集：{collection['name']}"]
    if collection["place"]:
        header.append(f"地点：{collection['place']}")
    if collection["start_date"]:
        header.append(f"日期：{collection['start_date']} 至 {collection['end_date'] or ''}")
    if collection["description"]:
        header.append(f"简介：{collection['description']}")
    return "\n".join(header)


def _day_label(day: Day) -> str:
    label = f"第 {day.number} 天" + (f"（{day.date}）" if day.date else "（日期不详）")
    return label + (f" · {'、'.join(day.places)}" if day.places else "")


def note_prompt(collection: sqlite3.Row, day: Day, lines: list[str], language: str) -> str:
    return (
        _header(collection)
        + f"\n\n{_day_label(day)}，按时间列出当天有代表性的照片：\n"
        + "\n".join(lines)
        + f"\n\n请用{LANGUAGES.get(language, '简体中文')}为这一天写 100 到 200 字的旅行笔记："
        "按时间写去了哪里、看到了什么、有哪些具体的细节（照片里的文字、说明里的信息）。"
        "只根据上面的材料，不要编造；不要标题，不要客套话。"
    )


def story_length(days: int) -> int:
    """Words (Chinese characters) the story aims at: longer trips, longer stories."""
    return max(400, min(2000, 150 * days))


def story_prompt(collection: sqlite3.Row, days: Sequence[Day], language: str) -> str:
    notes = "\n\n".join(f"{_day_label(day)}\n{day.text}" for day in days if day.text)
    length = story_length(len(days))
    return (
        _header(collection)
        + "\n\n下面是这次旅行按天整理的笔记：\n\n"
        + notes
        + f"\n\n请根据这些笔记，用{LANGUAGES.get(language, '简体中文')}写一篇约 {length} 字的旅行故事，"
        "用 Markdown：第一行是 # 标题，开头一段点出这次旅行，然后按时间展开"
        "（可以用 ## 小标题按天或按地点），最后一段收尾。"
        "保留笔记里具体的细节；只根据笔记来写，不要编造没有依据的事实"
        "（人名、店名、发生的事）；语气自然、有画面感，避免空泛的套话。"
    )


def story_tokens(days: int) -> int:
    return min(6000, int(story_length(days) * 2) + 600)


# --- Talking to the model ----------------------------------------------------------------------


def chat(
    base_url: str,
    prompt: str,
    max_tokens: int,
    *,
    schema: dict[str, Any] | None = None,
    timeout: float = 1800,
) -> tuple[str, int, int]:
    """Ask the local server (OpenAI-compatible) for a text answer."""
    body = {
        "messages": [
            {"role": "system", "content": "你是 LUMEN Studio 的旅行写作助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if schema is not None:  # an answer in this JSON shape
        body["temperature"] = 0.1
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": schema},
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


# --- The task ----------------------------------------------------------------------------------


def write_story(ctx: TaskContext) -> dict[str, int]:
    from lumen.services.settings import get_settings
    from lumen.vlm import pipeline

    conn = ctx.conn
    collection_id = int(ctx.payload["collection_id"])
    language = str(ctx.payload.get("language") or "zh-CN")
    writer = str(ctx.payload.get("writer") or DEFAULT_MODEL)
    notes_from = ctx.payload.get("notes_from")
    collection = conn.execute("SELECT * FROM collections WHERE id = ?", (collection_id,)).fetchone()
    if collection is None:
        raise PermanentTaskError("The portfolio was deleted")
    folder = pipeline.vlm_folder(conn, ctx.settings)
    if not _installed(folder, DEFAULT_MODEL):
        raise PermanentTaskError("The local model is not installed (download it in Settings)")

    if notes_from is not None:
        days = notes_of(conn, collection_id, int(notes_from))
        unread: list[int] = []
    else:
        days = pick_days(_rows(conn, collection_id))
        if not days:
            raise PermanentTaskError("The portfolio has no photos to write about")
        unread = [
            asset_id
            for day in days
            for asset_id in day.asset_ids
            if conn.execute(
                "SELECT 1 FROM media_descriptions WHERE asset_id = ? AND prompt_version >= ?",
                (asset_id, describing.PROMPT_VERSION),
            ).fetchone()
            is None
        ]
    local_writer = writer != "deepseek"
    # Steps: each unread photo, each day's notes, then the story.
    total = len(unread) + (0 if notes_from is not None else len(days)) + int(local_writer)
    step = 0
    ctx.progress(0, total, force=True)

    app = get_settings(conn)
    if app.ai_enabled:
        pipeline._unload_siglip(ctx.settings)
    from lumen.vlm.session import release_warm

    release_warm()  # one model at a time
    reader = pipeline._reader_factory(folder, pipeline.GPU_RESERVE_MIB if app.ai_enabled else None)
    running: str | None = None

    def run(model: str) -> None:
        nonlocal running
        if running == model:
            return
        reader.stop()
        try:
            reader.start(model, CONTEXT)
        except ServerError as exc:
            raise PermanentTaskError(f"The local model could not start: {exc}") from exc
        running = model

    tokens = [0, 0]
    try:
        if notes_from is None:
            run(DEFAULT_MODEL)
            for asset_id in unread:
                ctx.progress(step, total)
                pipeline._read_one(ctx, reader, asset_id, DEFAULT_MODEL)
                step += 1
            for day in days:
                ctx.progress(step, total, force=True)
                lines = _material(conn, collection_id, day)
                if lines:
                    try:
                        day.text, used, wrote = reader.write(
                            note_prompt(collection, day, lines, language), NOTE_TOKENS
                        )
                    except StoryError as exc:
                        raise PermanentTaskError(str(exc)) from exc
                    tokens[0] += used
                    tokens[1] += wrote
                step += 1
        if not any(day.text for day in days):
            raise PermanentTaskError("The model found nothing to write about in these photos")
        if not local_writer:
            # DeepSeek writes the story once the user has seen what it will get.
            analysis_id = _store(conn, collection_id, language, days, "notes", "", DEFAULT_MODEL,
                                 notes_markdown(days), tokens)  # fmt: skip
            ctx.progress(total, total, force=True)
            return {"analysis_id": analysis_id, "days": len(days), "read": len(unread)}
        run(writer)
        ctx.progress(step, total, force=True)
        try:
            text, used, wrote = reader.write(
                story_prompt(collection, days, language), story_tokens(len(days))
            )
        except StoryError as exc:
            raise PermanentTaskError(str(exc)) from exc
        tokens[0] += used
        tokens[1] += wrote
    finally:
        reader.stop()

    analysis_id = _store(conn, collection_id, language, days, "story", "local", writer, text,
                         tokens)  # fmt: skip
    ctx.progress(total, total, force=True)
    logger.info(
        "travel story written",
        extra={"collection_id": collection_id, "days": len(days), "writer": writer},
    )
    return {"analysis_id": analysis_id, "days": len(days), "read": len(unread)}


def notes_markdown(days: Sequence[Day]) -> str:
    return "\n\n".join(f"### {_day_label(day)}\n\n{day.text}" for day in days if day.text)


# --- Keeping notes and stories ---------------------------------------------------------------


def _store(
    conn: sqlite3.Connection,
    collection_id: int,
    language: str,
    days: Sequence[Day],
    stage: Literal["notes", "story"],
    provider: str,
    model: str,
    text: str,
    tokens: Sequence[int | None],
) -> int:
    data = {
        "collection_id": collection_id,
        "stage": stage,
        "writer": model if provider != "deepseek" else "deepseek",
        "days": [asdict(day) for day in days],
    }
    # Unique per run: writing again gives another version.
    key = hashlib.sha256(f"story:{collection_id}:{model}:{utc_now()}:{text}".encode()).hexdigest()
    ids = [asset_id for day in days for asset_id in day.asset_ids]
    with transaction(conn):
        cursor = conn.execute(
            """
            INSERT INTO ai_analysis (kind, provider, model, prompt_version, language, cache_key,
                                     vision, result, data, input_tokens, output_tokens, created_at)
            VALUES ('story', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                provider or "local", model, PROMPT_VERSION, language, key, text, json.dumps(data),
                tokens[0], tokens[1], utc_now(),
            ),
        )  # fmt: skip
        analysis_id = int(cursor.lastrowid or 0)
        conn.executemany(
            "INSERT OR IGNORE INTO ai_analysis_assets (analysis_id, asset_id, position) "
            "VALUES (?, ?, ?)",
            [(analysis_id, asset_id, i) for i, asset_id in enumerate(ids)],
        )
    return analysis_id


def notes_of(conn: sqlite3.Connection, collection_id: int, analysis_id: int) -> list[Day]:
    """The day notes kept with a story (or with notes waiting for the cloud)."""
    row = conn.execute(
        "SELECT data FROM ai_analysis WHERE id = ? AND kind = 'story' AND data IS NOT NULL "
        "AND json_extract(data, '$.collection_id') = ?",
        (analysis_id, collection_id),
    ).fetchone()
    days = json.loads(row["data"]).get("days") if row is not None else None
    if not days:
        raise NotFoundError("No day notes for this story", details={"id": analysis_id})
    return [Day(**day) for day in days]


def write_with_cloud(conn: sqlite3.Connection, collection_id: int, analysis_id: int) -> int:
    """Write the story with DeepSeek from kept day notes (text only: no photo, no place
    coordinates). The user has seen the notes; returns the new story's id."""
    from lumen.ai.cloud import client
    from lumen.services.settings import get_settings

    collection = conn.execute("SELECT * FROM collections WHERE id = ?", (collection_id,)).fetchone()
    if collection is None:
        raise NotFoundError("Collection not found", details={"id": collection_id})
    days = notes_of(conn, collection_id, analysis_id)
    language = str(
        conn.execute("SELECT language FROM ai_analysis WHERE id = ?", (analysis_id,)).fetchone()[0]
    )
    deepseek = client(get_settings(conn))
    response = deepseek.chat(
        [
            {"role": "system", "content": "你是 LUMEN Studio 的旅行写作助手。"},
            {"role": "user", "content": story_prompt(collection, days, language)},
        ],
        story_tokens(len(days)),
    )
    logger.info("travel story written in the cloud", extra={"collection_id": collection_id})
    return _store(conn, collection_id, language, days, "story", "deepseek", deepseek.model,
                  response.text.strip(), [response.input_tokens, response.output_tokens])  # fmt: skip
