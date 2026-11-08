"""Asking the model about one photo: the prompt, the answer's JSON schema and parsing.

One request per photo returns everything (reading the image is the slow part):
a short Chinese description, the text visible in the photo as written, and keywords.
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from PIL import Image

# Bump when the prompt or schema changes, so stored results can be recomputed.
PROMPT_VERSION = 1
# Long side of the image sent to the model: enough to read signs and menus.
IMAGE_EDGE = 1280
MAX_TOKENS = 1536

PROMPT = """请仔细看这张照片，用 JSON 回答：
- description：一到两句中文，客观描述画面里有什么（人物、动作、地点类型、主要物体、天气或时间），不要猜测人物身份，不要写感受。
- text：照片中能读出的文字，按原文（保留原来的语言和大小写）逐行抄写，用换行分隔；看不清的不要猜；没有文字就写空字符串。
- keywords：5 到 10 个中文关键词（场景、物体、活动），不要重复 description 里的长句。"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "text": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
    },
    "required": ["description", "text", "keywords"],
    "additionalProperties": False,
}


class DescribeError(Exception):
    """The model did not answer, or not in the expected form."""


@dataclass(frozen=True)
class Description:
    description: str
    text: str
    keywords: tuple[str, ...]
    prompt_tokens: int
    output_tokens: int
    seconds: float
    truncated: bool = False  # the answer hit the length limit (text may be incomplete)


def encode_image(image: Image.Image, edge: int = IMAGE_EDGE) -> str:
    """A JPEG data URL of ``image`` at most ``edge`` px on its long side."""
    copy = image.convert("RGB")
    copy.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    copy.save(out, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def request_body(image_url: str) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "photo", "schema": SCHEMA},
        },
        # Qwen's hybrid models would otherwise think aloud first (slow, and not needed).
        "chat_template_kwargs": {"enable_thinking": False},
    }


def describe(base_url: str, image: Image.Image, *, timeout: float = 300) -> Description:
    """Ask the server at ``base_url`` (OpenAI-compatible) about ``image``."""
    body = json.dumps(request_body(encode_image(image))).encode()
    request = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise DescribeError(f"the model did not answer: {exc}") from exc
    seconds = time.perf_counter() - started
    return parse_answer(answer, seconds)


def parse_answer(answer: dict[str, Any], seconds: float) -> Description:
    try:
        choice = answer["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DescribeError(f"unexpected answer: {str(answer)[:200]}") from exc
    truncated = choice.get("finish_reason") == "length"
    try:
        data = json.loads(content)
    except (TypeError, ValueError) as exc:
        salvaged = _salvage(content) if truncated and isinstance(content, str) else None
        if salvaged is None:
            raise DescribeError(f"unexpected answer: {str(content)[:200]}") from exc
        data = salvaged
    if not isinstance(data, dict):
        raise DescribeError("the answer is not an object")
    usage = answer.get("usage") or {}
    keywords = data.get("keywords") or []
    return Description(
        description=str(data.get("description") or "").strip(),
        text=_without_repeats(str(data.get("text") or "")).strip(),
        keywords=tuple(
            dict.fromkeys(str(k).strip() for k in keywords if isinstance(k, str) and k.strip())
        ),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        seconds=seconds,
        truncated=truncated,
    )


_FIELD = r'"{name}"\s*:\s*"((?:[^"\\]|\\.)*)'


def _salvage(content: str) -> dict[str, Any] | None:
    """The fields of an answer cut off at the length limit (usually while copying long or
    repeated text): the description if it is complete, and the text up to the cut."""
    description = re.search(_FIELD.format(name="description") + '"', content)
    if description is None:
        return None
    text = re.search(_FIELD.format(name="text"), content)
    return {
        "description": _unescape(description.group(1)),
        "text": _unescape(text.group(1)) if text else "",
        "keywords": [],
    }


def _unescape(value: str) -> str:
    value = value.rstrip("\\")  # a cut in the middle of an escape
    try:
        return str(json.loads(f'"{value}"'))
    except ValueError:
        return value


def _without_repeats(text: str, limit: int = 2) -> str:
    """Drop lines the model wrote more than ``limit`` times (a copying loop)."""
    seen: dict[str, int] = {}
    kept = []
    for line in text.splitlines():
        key = line.strip()
        seen[key] = seen.get(key, 0) + 1
        if not key or seen[key] <= limit:
            kept.append(line)
    return "\n".join(kept)
