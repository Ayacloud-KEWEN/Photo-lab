"""Caption drafts: one short line per photo of a portfolio, by the local model.

The model does not look at the photo again: it gets what it read in it (description,
text, keywords), where and when it was taken, and the captions next to it for the tone.
Photos are sent in batches; the answer is one numbered line per photo. Drafts are kept
apart (``collection_items.caption_draft``) until the user accepts them.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Sequence

from lumen.core.config import Settings
from lumen.core.errors import LumenError, NotFoundError
from lumen.db.connection import transaction
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskContext
from lumen.vlm import session
from lumen.vlm.story import LANGUAGES, StoryError

logger = logging.getLogger(__name__)

CAPTION_TASK = "vlm_caption_drafts"
BATCH = 10
MAX_TEXT = 120
TOKENS_PER_CAPTION = 80
_LINE = re.compile(r"^\s*(\d+)\s*[.、:：)）]\s*(.+?)\s*$")


def start(
    conn: sqlite3.Connection,
    settings: Settings,
    collection_id: int,
    asset_ids: list[int] | None,
    language: str,
) -> int:
    if conn.execute("SELECT 1 FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
        raise NotFoundError("Collection not found", details={"id": collection_id})
    if not _targets(conn, collection_id, asset_ids):
        raise LumenError("Every photo already has a caption")
    session.require_installed(conn, settings)
    return queue.enqueue(
        conn,
        CAPTION_TASK,
        payload={"collection_id": collection_id, "asset_ids": asset_ids, "language": language},
        unique=False,
    )


def _targets(
    conn: sqlite3.Connection, collection_id: int, asset_ids: list[int] | None
) -> list[int]:
    """Photos to caption, in the portfolio's order: the ones asked for, else those
    without a caption or a draft."""
    rows = conn.execute(
        """
        SELECT a.id, i.caption, i.caption_draft FROM collection_items i
        JOIN media_assets a ON a.id = i.asset_id
        JOIN media_files c ON c.id = a.cover_file_id AND c.fingerprint IS NOT NULL
        WHERE i.collection_id = ? AND a.media_type = 'photo'
        ORDER BY i.position, i.added_at
        """,
        (collection_id,),
    ).fetchall()
    if asset_ids is not None:
        wanted = set(asset_ids)
        return [int(r["id"]) for r in rows if int(r["id"]) in wanted]
    return [int(r["id"]) for r in rows if not r["caption"] and not r["caption_draft"]]


def _line(conn: sqlite3.Connection, collection_id: int, asset_id: int) -> str:
    row = conn.execute(
        """
        SELECT a.capture_time, p.city, p.city_zh, d.description, d.text, d.keywords
        FROM media_assets a
        LEFT JOIN media_places p ON p.asset_id = a.id
        LEFT JOIN media_descriptions d ON d.asset_id = a.id
        WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    parts = []
    if row["capture_time"]:
        parts.append(row["capture_time"][:16].replace("T", " "))
    if row["city_zh"] or row["city"]:
        parts.append(f"地点：{row['city_zh'] or row['city']}")
    if row["description"]:
        parts.append(f"画面：{row['description']}")
    text = " / ".join(line.strip() for line in (row["text"] or "").splitlines() if line.strip())
    if text:
        parts.append(f"文字：{text[:MAX_TEXT]}")
    keywords = json.loads(row["keywords"]) if row["keywords"] else []
    if keywords:
        parts.append("关键词：" + "、".join(keywords[:6]))
    return " · ".join(parts) or "（没有可用的信息）"


def _examples(conn: sqlite3.Connection, collection_id: int) -> list[str]:
    """A few captions the user wrote, so drafts follow their tone."""
    return [
        str(r[0])
        for r in conn.execute(
            "SELECT caption FROM collection_items WHERE collection_id = ? AND caption != '' "
            "ORDER BY position LIMIT 5",
            (collection_id,),
        )
    ]


def prompt(
    collection: sqlite3.Row, lines: Sequence[str], examples: Sequence[str], language: str
) -> str:
    header = f"作品集：{collection['name']}" + (
        f"（{collection['place']}）" if collection["place"] else ""
    )
    style = (
        "\n\n作者自己写过的说明（参考语气和长度）：\n" + "\n".join(f"- {e}" for e in examples)
        if examples
        else ""
    )
    numbered = "\n".join(f"{n}. {line}" for n, line in enumerate(lines, start=1))
    return (
        f"{header}{style}\n\n下面是 {len(lines)} 张照片，每行一张：拍摄时间、地点、画面内容、照片里的文字：\n"
        + numbered
        + f"\n\n请用{LANGUAGES.get(language, '简体中文')}为每张照片写一句说明（中文不超过 30 字），"
        "像摄影师写的图说：具体、有画面感，可以点出地点或照片里的文字；不要以“这张照片”开头，"
        "不要编造没有依据的内容。"
        f"只输出 {len(lines)} 行，格式为“编号. 说明”，不要别的内容。"
    )


def parse(answer: str, count: int) -> dict[int, str]:
    """Numbered lines of the answer, by number (1-based); others are ignored."""
    found: dict[int, str] = {}
    for raw in answer.splitlines():
        match = _LINE.match(raw)
        if match and 1 <= int(match.group(1)) <= count:
            text = match.group(2).strip().strip("“”\"'")
            if text:
                found.setdefault(int(match.group(1)), text)
    return found


def write_drafts(ctx: TaskContext) -> dict[str, int]:
    conn = ctx.conn
    collection_id = int(ctx.payload["collection_id"])
    language = str(ctx.payload.get("language") or "zh-CN")
    collection = conn.execute("SELECT * FROM collections WHERE id = ?", (collection_id,)).fetchone()
    if collection is None:
        raise PermanentTaskError("The portfolio was deleted")
    targets = _targets(conn, collection_id, ctx.payload.get("asset_ids"))
    if not targets:
        return {"drafted": 0, "read": 0}
    to_read = session.unread(conn, targets)
    batches = [targets[i : i + BATCH] for i in range(0, len(targets), BATCH)]
    total = len(to_read) + len(batches)
    ctx.progress(0, total, force=True)
    examples = _examples(conn, collection_id)
    drafted = 0
    with session.local_model(ctx) as reader:
        step = session.read_photos(ctx, reader, to_read, 0, total)
        for batch in batches:
            ctx.progress(step, total, force=True)
            lines = [_line(conn, collection_id, asset_id) for asset_id in batch]
            try:
                answer, _, _ = reader.write(  # type: ignore[attr-defined]
                    prompt(collection, lines, examples, language), TOKENS_PER_CAPTION * len(batch)
                )
            except StoryError as exc:
                raise PermanentTaskError(str(exc)) from exc
            captions = parse(answer, len(batch))
            with transaction(conn):
                for number, asset_id in enumerate(batch, start=1):
                    if number in captions:
                        drafted += conn.execute(
                            "UPDATE collection_items SET caption_draft = ? "
                            "WHERE collection_id = ? AND asset_id = ?",
                            (captions[number], collection_id, asset_id),
                        ).rowcount
            step += 1
    ctx.progress(total, total, force=True)
    logger.info(
        "caption drafts written", extra={"collection_id": collection_id, "drafted": drafted}
    )
    return {"drafted": drafted, "read": len(to_read)}
