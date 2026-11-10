"""Asking the library in plain language, answered by the local model.

The model cannot take in the library, and would invent answers if asked to. So:

1. Understand: the model turns the question into filters (dates, country, town, camera,
   lens, rating, favourite, media type), keywords to look for in what it read in the
   photos, something to look for by image content, and what kind of answer is wanted
   (photos, a count, a ranking).
2. Look up: the program applies them (the library filters, the search over what was
   read, the AI search when it is set up) and counts in SQL.
3. Answer: the model writes a short answer from the counts and from what it read in the
   best matching photos, citing them by number.

The model is kept running for a few minutes afterwards, so a follow-up question starts
at once.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from collections.abc import Sequence
from datetime import date
from typing import Any

from pydantic import ValidationError

from lumen.core.config import Settings
from lumen.core.errors import NotFoundError
from lumen.db.connection import transaction, utc_now
from lumen.library.search import like_pattern
from lumen.schemas.ask import AskAnswer, AskCount, AskList, AskPlan, AskStats
from lumen.schemas.assets import AssetQuery
from lumen.services import assets
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskContext
from lumen.vlm import session
from lumen.vlm.story import LANGUAGES, StoryError

logger = logging.getLogger(__name__)

ASK_TASK = "vlm_ask_library"
KEEP_WARM_S = 300
MAX_MATCHES = 500
SHOWN = 60
MATERIAL = 40
MAX_TEXT = 100

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["photos", "count", "top"]},
        "date_from": {"type": "string"},
        "date_to": {"type": "string"},
        "country": {"type": "string"},
        "city": {"type": "string"},
        "camera": {"type": "string"},
        "lens": {"type": "string"},
        "min_rating": {"type": "integer", "minimum": 0, "maximum": 5},
        "favorite": {"type": "boolean"},
        "media_type": {"type": "string", "enum": ["", "photo", "video"]},
        "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "visual": {"type": "string"},
        "group_by": {
            "type": "string",
            "enum": ["", "city", "country", "year", "month", "camera", "lens"],
        },
    },
    "required": ["intent", "keywords", "visual", "group_by"],
    "additionalProperties": False,
}


# --- Asking ---------------------------------------------------------------------------------


def ask(conn: sqlite3.Connection, settings: Settings, question: str, language: str) -> AskAnswer:
    session.require_installed(conn, settings)
    with transaction(conn):
        question_id = int(
            conn.execute(
                "INSERT INTO library_questions (question, language, created_at) VALUES (?, ?, ?)",
                (question.strip(), language, utc_now()),
            ).lastrowid
            or 0
        )
    task_id = queue.enqueue(conn, ASK_TASK, payload={"question_id": question_id}, unique=False)
    with transaction(conn):
        conn.execute(
            "UPDATE library_questions SET task_id = ? WHERE id = ?", (task_id, question_id)
        )
    return get(conn, question_id)


def _to_model(conn: sqlite3.Connection, row: sqlite3.Row, *, items: bool) -> AskAnswer:
    ids = json.loads(row["asset_ids"])
    return AskAnswer(
        id=row["id"],
        question=row["question"],
        language=row["language"],
        status=row["status"],
        task_id=row["task_id"],
        plan=AskPlan.model_validate_json(row["plan"]) if row["plan"] else None,
        stats=AskStats.model_validate_json(row["stats"]) if row["stats"] else None,
        answer=row["answer"],
        items=_in_order(conn, ids[:SHOWN]) if items else [],
        asset_ids=ids,
        error=row["error"],
        created_at=row["created_at"],
    )


def _in_order(conn: sqlite3.Connection, ids: Sequence[int]) -> list[Any]:
    found = {s.id: s for s in assets.summaries_by_ids(conn, list(ids))}
    return [found[i] for i in ids if i in found]


def get(conn: sqlite3.Connection, question_id: int) -> AskAnswer:
    row = conn.execute("SELECT * FROM library_questions WHERE id = ?", (question_id,)).fetchone()
    if row is None:
        raise NotFoundError("Question not found", details={"id": question_id})
    return _to_model(conn, row, items=True)


def history(conn: sqlite3.Connection, limit: int = 50) -> AskList:
    rows = conn.execute(
        "SELECT * FROM library_questions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return AskList(items=[_to_model(conn, row, items=False) for row in rows])


def delete(conn: sqlite3.Connection, question_id: int) -> None:
    with transaction(conn):
        if not conn.execute("DELETE FROM library_questions WHERE id = ?", (question_id,)).rowcount:
            raise NotFoundError("Question not found", details={"id": question_id})


# --- 1. Understanding the question -------------------------------------------------------------


def _context(conn: sqlite3.Connection) -> str:
    """What the library holds, so the model maps the question onto it."""
    facets = assets.facets(conn)
    countries = "、".join(
        f"{c.country_code}={c.name.zh or c.name.name}" for c in facets.places[:40]
    )
    cameras = "、".join(v.value for v in facets.cameras[:20])
    lenses = "、".join(v.value for v in facets.lenses[:20])
    years = "、".join(v.value for v in facets.years[:30])
    return (
        f"今天是 {date.today().isoformat()}。\n"
        f"图库里的国家（代码=名称）：{countries or '无'}\n"
        f"相机：{cameras or '无'}\n镜头：{lenses or '无'}\n年份：{years or '无'}"
    )


def plan_prompt(conn: sqlite3.Connection, question: str) -> str:
    return (
        f"{_context(conn)}\n\n"
        f"用户对自己的照片图库提问：「{question}」\n\n"
        "把问题转成查询条件，用 JSON 回答：\n"
        "- intent：photos（找照片）、count（问数量）、top（问最多/排名）\n"
        "- date_from / date_to：YYYY-MM-DD，date_to 不含当天（“去年”是去年 1 月 1 日到今年 1 月 1 日）；没有就空字符串\n"
        "- country：上面列出的国家代码；city：城市名（原文）；camera / lens：上面列出的名称里最接近的；没有就空字符串\n"
        "- min_rating：0 到 5；favorite：只要收藏的照片时为 true\n"
        "- media_type：photo、video 或空字符串\n"
        "- keywords：要在照片的描述和照片里的文字中查找的词（中文，写成可能出现的说法，如“拉面”“面条”）；"
        "地点、时间、相机已经放在上面的字段里，不要重复\n"
        "- visual：要按画面内容搜索的简短描述（如“海边日落”）；不需要就空字符串\n"
        "- group_by：intent 为 top 或需要分组统计时，按 city、country、year、month、camera 或 lens 分组；否则空字符串"
    )


def parse_plan(answer: str) -> AskPlan:
    try:
        data = json.loads(answer)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        data["keywords"] = [str(k).strip() for k in data.get("keywords") or [] if str(k).strip()]
        return AskPlan.model_validate(data)
    except (ValueError, ValidationError) as exc:
        raise PermanentTaskError(f"The question was not understood: {exc}") from exc


# --- 2. Looking it up ---------------------------------------------------------------------------


def _closest(values: Sequence[str], wanted: str) -> str | None:
    """The facet value matching what the model wrote (exact, else containing it)."""
    lowered = wanted.lower().strip()
    if not lowered:
        return None
    for value in values:
        if value.lower() == lowered:
            return value
    return next((value for value in values if lowered in value.lower()), None)


def _place_id(conn: sqlite3.Connection, city: str) -> int | None:
    pattern = like_pattern(city.strip())
    row = conn.execute(
        r"""
        SELECT place_id, COUNT(*) AS n FROM media_places
        WHERE city LIKE ? ESCAPE '\' OR city_zh LIKE ? ESCAPE '\' OR city_fr LIKE ? ESCAPE '\'
        GROUP BY place_id ORDER BY n DESC LIMIT 1
        """,
        (pattern, pattern, pattern),
    ).fetchone()
    return int(row["place_id"]) if row else None


def query_of(conn: sqlite3.Connection, plan: AskPlan) -> AssetQuery:
    """The library filters of the plan; what cannot be matched is dropped from the plan."""
    facets = assets.facets(conn)
    camera = _closest([v.value for v in facets.cameras], plan.camera)
    lens = _closest([v.value for v in facets.lenses], plan.lens)
    countries = {c.country_code for c in facets.places}
    country = plan.country.upper() if plan.country.upper() in countries else None
    place_id = _place_id(conn, plan.city) if plan.city else None
    plan.camera, plan.lens = camera or "", lens or ""
    plan.country = country or ""
    if plan.city and place_id is None:
        plan.keywords = [*plan.keywords, plan.city]  # an unknown town: look for its name
        plan.city = ""

    def day(value: str) -> str | None:
        try:
            return date.fromisoformat(value[:10]).isoformat() if value else None
        except ValueError:
            return None

    plan.date_from, plan.date_to = day(plan.date_from) or "", day(plan.date_to) or ""
    return AssetQuery(
        date_from=plan.date_from or None,
        date_to=plan.date_to or None,
        country=country,
        place_id=place_id,
        camera=camera,
        lens=lens,
        min_rating=plan.min_rating or None,
        favorite=True if plan.favorite else None,
        media_type=plan.media_type or None,
    )


def _with_keywords(conn: sqlite3.Connection, ids: list[int], keywords: Sequence[str]) -> list[int]:
    """Those of ``ids`` whose search text (what was read, tags, names) has any keyword."""
    if not keywords or not ids:
        return ids
    found: set[int] = set()
    likes = " OR ".join(r"body LIKE ? ESCAPE '\'" for _ in keywords)
    patterns = [like_pattern(k) for k in keywords]
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        found.update(
            int(r[0])
            for r in conn.execute(
                f"SELECT rowid FROM asset_search WHERE rowid IN ({','.join('?' * len(chunk))}) "
                f"AND ({likes})",
                (*chunk, *patterns),
            )
        )
    return [i for i in ids if i in found]


def _visual(
    ctx: TaskContext, text: str, query: AssetQuery, candidates: list[int]
) -> list[int] | None:
    """Photos looking like ``text`` (AI search), or None when it is not set up."""
    from lumen.services import ai

    if not text or not candidates:
        return None
    try:
        page = ai.search(ctx.conn, ctx.settings, text, query, limit=MAX_MATCHES)
    except Exception as exc:  # not installed, not indexed, out of memory...
        logger.info("AI search not used for a question", extra={"error": str(exc)})
        return None
    allowed = set(candidates)
    return [item.id for item in page.items[: page.relevant_count] if item.id in allowed]


def _described(conn: sqlite3.Connection, ids: Sequence[int]) -> int:
    count = 0
    for start in range(0, len(ids), 500):
        chunk = list(ids[start : start + 500])
        count += conn.execute(
            f"SELECT COUNT(*) FROM media_descriptions WHERE description != '' "
            f"AND asset_id IN ({','.join('?' * len(chunk))})",
            chunk,
        ).fetchone()[0]
    return int(count)


_GROUPS = {
    "city": "SELECT COALESCE(p.city_zh, p.city) FROM media_places p WHERE p.asset_id = a.id",
    "country": "SELECT p.country_code FROM media_places p WHERE p.asset_id = a.id",
    "year": "SELECT substr(a.capture_time, 1, 4)",
    "month": "SELECT substr(a.capture_time, 1, 7)",
    "camera": "SELECT m.camera_model FROM media_metadata m WHERE m.file_id = a.cover_file_id",
    "lens": "SELECT m.lens_model FROM media_metadata m WHERE m.file_id = a.cover_file_id",
}


def _groups(conn: sqlite3.Connection, ids: Sequence[int], group_by: str) -> list[AskCount]:
    if group_by not in _GROUPS or not ids:
        return []
    counts: Counter[str] = Counter()
    for start in range(0, len(ids), 500):
        chunk = list(ids[start : start + 500])
        for row in conn.execute(
            f"SELECT ({_GROUPS[group_by]}) AS label FROM media_assets a "
            f"WHERE a.id IN ({','.join('?' * len(chunk))})",
            chunk,
        ):
            if row["label"]:
                counts[str(row["label"])] += 1
    return [AskCount(label=label, count=n) for label, n in counts.most_common(10)]


def look_up(ctx: TaskContext, plan: AskPlan) -> tuple[list[int], AskStats]:
    conn = ctx.conn
    query = query_of(conn, plan)
    candidates = assets.list_asset_ids(conn, query, limit=200_000)
    matches = _with_keywords(conn, candidates, plan.keywords)
    wanted = plan.visual or (" ".join(plan.keywords) if not matches else "")
    visual = _visual(ctx, wanted, query, candidates)
    if visual is not None:
        if plan.keywords and matches:
            seen = set(matches)
            matches = matches + [i for i in visual if i not in seen]
        else:
            matches = visual
    times = [
        r[0]
        for r in conn.execute(
            f"SELECT capture_time FROM media_assets WHERE capture_time IS NOT NULL AND id IN "
            f"({','.join('?' * min(len(matches), 900))})",
            matches[:900],
        )
    ] if matches else []  # fmt: skip
    stats = AskStats(
        total=len(matches),
        described=_described(conn, candidates[:20_000]),
        first=min(times) if times else None,
        last=max(times) if times else None,
        groups=_groups(conn, matches, plan.group_by),
        visual_used=visual is not None,
    )
    return matches[:MAX_MATCHES], stats


# --- 3. Answering -------------------------------------------------------------------------------


def _material(conn: sqlite3.Connection, ids: Sequence[int]) -> list[str]:
    lines = []
    for number, asset_id in enumerate(ids[:MATERIAL], start=1):
        row = conn.execute(
            """
            SELECT a.capture_time, p.city, p.city_zh, d.description, d.text
            FROM media_assets a
            LEFT JOIN media_places p ON p.asset_id = a.id
            LEFT JOIN media_descriptions d ON d.asset_id = a.id
            WHERE a.id = ?
            """,
            (asset_id,),
        ).fetchone()
        if row is None:
            continue
        parts = [f"[{number}]"]
        if row["capture_time"]:
            parts.append(row["capture_time"][:10])
        if row["city_zh"] or row["city"]:
            parts.append(row["city_zh"] or row["city"])
        if row["description"]:
            parts.append(row["description"])
        text = " / ".join(line.strip() for line in (row["text"] or "").splitlines() if line.strip())
        if text:
            parts.append(f"文字：{text[:MAX_TEXT]}")
        lines.append(" ".join(parts))
    return lines


def answer_prompt(
    question: str, plan: AskPlan, stats: AskStats, lines: Sequence[str], language: str
) -> str:
    understood = {k: v for k, v in plan.model_dump().items() if v not in ("", [], 0, False, None)}
    groups = "、".join(f"{g.label} {g.count} 张" for g in stats.groups)
    facts = [
        f"符合条件的照片和视频：{stats.total} 张",
        f"时间范围：{stats.first[:10]} 至 {stats.last[:10]}" if stats.first and stats.last else "",
        f"分组统计（前 10）：{groups}" if groups else "",
        f"候选照片里已被本地模型识别过内容的：{stats.described} 张" if plan.keywords else "",
    ]
    return (
        f"用户对自己的照片图库提问：「{question}」\n"
        f"程序对问题的理解：{json.dumps(understood, ensure_ascii=False)}\n\n"
        "程序查到的结果：\n" + "\n".join(f for f in facts if f)
        + ("\n\n最相关的照片（编号、日期、地点、画面、照片里的文字）：\n" + "\n".join(lines) if lines else "")
        + f"\n\n请用{LANGUAGES.get(language, '简体中文')}简短回答（不超过 200 字，可用 Markdown 列表）。"
        "数字以上面的统计为准；提到具体照片时用 [编号] 引用；"
        "只根据上面的结果回答，结果不足以回答时直接说明，不要编造。"
    )  # fmt: skip


# --- The task -----------------------------------------------------------------------------------


def answer_question(ctx: TaskContext) -> dict[str, int]:
    conn = ctx.conn
    question_id = int(ctx.payload["question_id"])
    row = conn.execute("SELECT * FROM library_questions WHERE id = ?", (question_id,)).fetchone()
    if row is None:
        return {"matches": 0}  # deleted meanwhile
    try:
        ctx.progress(0, 3, force=True)
        with session.local_model(ctx, keep_warm_s=KEEP_WARM_S) as reader:
            try:
                raw, _, _ = reader.write(
                    plan_prompt(conn, row["question"]), 600, schema=PLAN_SCHEMA
                )
            except StoryError as exc:
                raise PermanentTaskError(str(exc)) from exc
            plan = parse_plan(raw)
            ctx.progress(1, 3, force=True)
            matches, stats = look_up(ctx, plan)
            with transaction(conn):
                conn.execute(
                    "UPDATE library_questions SET plan = ?, stats = ?, asset_ids = ? WHERE id = ?",
                    (plan.model_dump_json(), stats.model_dump_json(), json.dumps(matches),
                     question_id),
                )  # fmt: skip
            ctx.progress(2, 3, force=True)
            prompt = answer_prompt(
                row["question"], plan, stats, _material(conn, matches), row["language"]
            )
            try:
                text, _, _ = reader.write(prompt, 900)
            except StoryError as exc:
                raise PermanentTaskError(str(exc)) from exc
    except PermanentTaskError as exc:
        with transaction(conn):
            conn.execute(
                "UPDATE library_questions SET status = 'failed', error = ? WHERE id = ?",
                (str(exc), question_id),
            )
        raise
    with transaction(conn):
        conn.execute(
            "UPDATE library_questions SET status = 'done', answer = ? WHERE id = ?",
            (text, question_id),
        )
    ctx.progress(3, 3, force=True)
    return {"matches": len(matches)}
