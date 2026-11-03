"""Opt-in cloud analysis with DeepSeek (OpenAI-compatible chat completions API).

Privacy rules enforced here:
- the API key lives in the OS credential store (Windows Credential Manager), never
  in the database, settings or logs;
- nothing is sent unless the request carries ``confirmed=True`` (the UI shows the
  user exactly what will be uploaded first);
- images are reduced copies of the cached previews; GPS is sent only on request.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image

from lumen.core.errors import LumenError, NotFoundError
from lumen.db.connection import transaction, utc_now
from lumen.media import thumbnails
from lumen.schemas.ai import (
    KIND_LIMITS,
    AnalysisResult,
    CloudPreview,
    CloudPreviewItem,
    CloudRequest,
    CloudTestResult,
)
from lumen.schemas.settings import AppSettings

logger = logging.getLogger(__name__)

PROVIDER = "deepseek"
KEYRING_SERVICE = "LUMEN Studio"
KEYRING_USER = "deepseek-api-key"
PROMPT_VERSION = 1
TIMEOUT_S = 180

#: Long edge of uploaded images. DeepSeek reportedly caps each image at ~384 tokens,
#: so larger uploads only cost bandwidth.
IMAGE_EDGE = {"describe": 1024, "critique": 1024, "select_best": 768, "story": 640}
MAX_TOKENS = {"describe": 700, "critique": 1400, "select_best": 1400, "story": 1800}
VISION_PROBE = "What is the main colour of this image? Answer with one English word."
LANGUAGE_NAMES = {"zh-CN": "简体中文", "en": "English", "fr": "français"}


class CloudError(LumenError):
    status_code = 502
    code = "cloud_error"


class CloudNotConfiguredError(LumenError):
    status_code = 409
    code = "cloud_not_configured"


class VisionUnsupportedError(LumenError):
    status_code = 422
    code = "vision_unsupported"


# ---------------------------------------------------------------- API key


def _keyring() -> Any:
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - keyring is part of the ai extra
        raise CloudNotConfiguredError("Credential storage is unavailable") from exc
    return keyring


def get_api_key() -> str | None:
    value = _keyring().get_password(KEYRING_SERVICE, KEYRING_USER)
    return str(value) if value else None


def set_api_key(api_key: str) -> None:
    _keyring().set_password(KEYRING_SERVICE, KEYRING_USER, api_key.strip())


def delete_api_key() -> None:
    try:
        _keyring().delete_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception as exc:  # keyring raises PasswordDeleteError if absent
        logger.debug("no api key to delete", extra={"error": str(exc)})


# ---------------------------------------------------------------- HTTP client


@dataclass
class ChatResponse:
    text: str
    input_tokens: int | None
    output_tokens: int | None


class DeepSeekClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            if exc.code in (401, 403):
                raise CloudNotConfiguredError("The API key was rejected") from exc
            if exc.code == 400 and re.search(r"image|vision|multimodal|content type", detail, re.I):
                raise VisionUnsupportedError(
                    f"Model {self.model} does not accept images", details={"detail": detail}
                ) from exc
            raise CloudError(
                f"DeepSeek returned HTTP {exc.code}", details={"detail": detail}
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudError(f"Cannot reach {urlparse(self.base_url).netloc}: {exc}") from exc

    def list_models(self) -> list[str]:
        payload = self._request("GET", "/models")
        return sorted(str(item.get("id")) for item in payload.get("data", []) if item.get("id"))

    def chat(self, messages: list[dict[str, Any]], max_tokens: int) -> ChatResponse:
        payload = self._request(
            "POST",
            "/chat/completions",
            {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.7,
                "stream": False,
            },
        )
        try:
            text = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise CloudError("Unexpected response from DeepSeek") from exc
        usage = payload.get("usage") or {}
        return ChatResponse(text, usage.get("prompt_tokens"), usage.get("completion_tokens"))


def client(settings: AppSettings) -> DeepSeekClient:
    if not settings.cloud_enabled:
        raise CloudNotConfiguredError("Cloud analysis is turned off in Settings")
    api_key = get_api_key()
    if not api_key:
        raise CloudNotConfiguredError("No DeepSeek API key has been saved")
    return DeepSeekClient(settings.cloud_base_url, api_key, settings.cloud_model)


def _data_url(image: Image.Image, edge: int) -> str:
    copy = image.convert("RGB")
    copy.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def test_connection(settings: AppSettings, api_key: str | None = None) -> CloudTestResult:
    """Check the key, list models, and see whether the model accepts an image."""
    key = api_key or get_api_key()
    if not key:
        return CloudTestResult(ok=False, message="No API key", vision=None)
    deepseek = DeepSeekClient(settings.cloud_base_url, key, settings.cloud_model)
    try:
        models = deepseek.list_models()
    except LumenError as exc:
        return CloudTestResult(ok=False, message=exc.message, vision=None)
    probe = Image.new("RGB", (64, 64), (220, 20, 20))
    try:
        answer = deepseek.chat(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _data_url(probe, 64)}},
                        {"type": "text", "text": VISION_PROBE},
                    ],
                }
            ],
            max_tokens=10,
        )
    except VisionUnsupportedError:
        return CloudTestResult(
            ok=True, models=models, vision=False,
            message=f"Connected. Model {settings.cloud_model} does not accept images.",
        )  # fmt: skip
    except LumenError as exc:
        return CloudTestResult(ok=False, models=models, vision=None, message=exc.message)
    vision = "red" in answer.text.lower()
    return CloudTestResult(
        ok=True,
        models=models,
        vision=vision,
        message=f"Connected. Model {settings.cloud_model} "
        + ("accepts images." if vision else f"answered without seeing the image: {answer.text!r}"),
    )


# ---------------------------------------------------------------- requests


@dataclass
class _Photo:
    asset_id: int
    fingerprint: str
    fields: dict[str, str]
    labels: list[str]


def _photos(conn: sqlite3.Connection, request: CloudRequest) -> list[_Photo]:
    low, high = KIND_LIMITS[request.kind]
    ids = list(dict.fromkeys(request.asset_ids))
    if not low <= len(ids) <= high:
        raise LumenError(f"{request.kind} needs between {low} and {high} photos")
    photos: list[_Photo] = []
    for asset_id in ids:
        row = conn.execute(
            """
            SELECT a.capture_time, c.fingerprint, m.camera_make, m.camera_model, m.lens_model,
                   m.focal_length_mm, m.aperture, m.exposure_time_s, m.iso,
                   l.latitude, l.longitude
            FROM media_assets a
            JOIN media_files c ON c.id = a.cover_file_id
            LEFT JOIN media_metadata m ON m.file_id = c.id
            LEFT JOIN media_locations l ON l.asset_id = a.id
            WHERE a.id = ?
            """,
            (asset_id,),
        ).fetchone()
        if row is None or not row["fingerprint"]:
            raise NotFoundError("Asset not found or not processed", details={"id": asset_id})
        fields: dict[str, str] = {}
        if row["capture_time"]:
            fields["captured"] = row["capture_time"].replace("T", " ")
        camera = " ".join(p for p in (row["camera_make"], row["camera_model"]) if p)
        if camera:
            fields["camera"] = camera
        if row["lens_model"]:
            fields["lens"] = row["lens_model"]
        exposure = []
        if row["focal_length_mm"]:
            exposure.append(f"{row['focal_length_mm']:g}mm")
        if row["aperture"]:
            exposure.append(f"f/{row['aperture']:g}")
        if row["exposure_time_s"]:
            t = row["exposure_time_s"]
            exposure.append(f"1/{round(1 / t)}s" if t < 1 else f"{t:g}s")
        if row["iso"]:
            exposure.append(f"ISO {row['iso']}")
        if exposure:
            fields["exposure"] = " ".join(exposure)
        if request.include_location and row["latitude"] is not None:
            fields["location"] = f"{row['latitude']:.5f}, {row['longitude']:.5f}"
        labels = [
            str(r[0])
            for r in conn.execute(
                "SELECT t.name FROM media_tags mt JOIN tags t ON t.id = mt.tag_id "
                "WHERE mt.asset_id = ? ORDER BY mt.source, t.name_key",
                (asset_id,),
            )
        ]
        photos.append(_Photo(asset_id, row["fingerprint"], fields, labels))
    return photos


def _cache_key(request: CloudRequest, model: str, photos: list[_Photo]) -> str:
    material = json.dumps(
        {
            "provider": PROVIDER,
            "model": model,
            "prompt": PROMPT_VERSION,
            "kind": request.kind,
            "language": request.language,
            "location": request.include_location,
            "text_only": request.text_only,
            "photos": [p.fingerprint for p in photos],
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()


def preview(conn: sqlite3.Connection, settings: AppSettings, request: CloudRequest) -> CloudPreview:
    photos = _photos(conn, request)
    cached = (
        conn.execute(
            "SELECT 1 FROM ai_analysis WHERE cache_key = ?",
            (_cache_key(request, settings.cloud_model, photos),),
        ).fetchone()
        is not None
    )
    items = []
    for photo in photos:
        fields = dict(photo.fields)
        if request.text_only and photo.labels:
            fields["labels"] = ", ".join(photo.labels)
        items.append(
            CloudPreviewItem(
                asset_id=photo.asset_id,
                rendition_version=photo.fingerprint.split(":")[-1][:16],
                fields=fields,
            )
        )
    return CloudPreview(
        provider="deepseek",
        model=settings.cloud_model,
        host=urlparse(settings.cloud_base_url).netloc,
        items=items,
        image_max_edge=None if request.text_only else IMAGE_EDGE[request.kind],
        cached=cached,
    )


def _instructions(kind: str, count: int, language: str, text_only: bool) -> str:
    lang = LANGUAGE_NAMES.get(language, "English")
    seeing = (
        "You cannot see the photos: you only get their metadata and automatically detected "
        "labels. Say so briefly and base everything on that information. "
        if text_only
        else ""
    )
    common = f"Answer in {lang}, formatted as Markdown. {seeing}"
    if kind == "describe":
        return (
            common + "Describe this photograph: subject, setting, light, mood and notable "
            "details, in two short paragraphs. Do not invent facts that are not visible."
        )
    if kind == "critique":
        return (
            common + "You are an experienced photography mentor. Critique this photo with "
            "short sections on composition, light, exposure and colour, subject and story, "
            f"and 3 concrete suggestions (section headings in {lang}). Use the camera settings "
            "when they explain something. Be specific, honest and encouraging."
        )
    if kind == "select_best":
        return (
            common + f"These {count} photos are numbered 1 to {count} in the order given. "
            "Pick the strongest photo for a portfolio. Start your answer with one line of JSON "
            'exactly like {"best": 2, "ranking": [2, 1, 3]} covering every photo, then '
            "explain the choice and briefly note each photo's main strength or weakness."
        )
    return (
        common + "Write a short travel story (300-500 words) with a title, based on these "
        "photos in chronological order and their dates (and places, when given). Do not "
        "invent specific facts that the photos or metadata do not support."
    )


def _messages(
    conn: sqlite3.Connection, cache_dir: Path, request: CloudRequest, photos: list[_Photo]
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for number, photo in enumerate(photos, start=1):
        lines = [f"Photo {number}"] + [f"{key}: {value}" for key, value in photo.fields.items()]
        if request.text_only and photo.labels:
            lines.append("labels: " + ", ".join(photo.labels))
        content.append({"type": "text", "text": "\n".join(lines)})
        if not request.text_only:
            target = thumbnails.rendition_paths(cache_dir, photo.fingerprint)
            source = target.preview if target.preview.exists() else target.thumb
            with Image.open(source) as image:
                url = _data_url(image, IMAGE_EDGE[request.kind])
            content.append({"type": "image_url", "image_url": {"url": url}})
    content.append(
        {
            "type": "text",
            "text": _instructions(request.kind, len(photos), request.language, request.text_only),
        }
    )
    return [
        {"role": "system", "content": "You are the photography assistant of LUMEN Studio."},
        {"role": "user", "content": content},
    ]


_JSON_LINE = re.compile(r"\{[^{}]*\"best\"[^{}]*\}")


def _structured(kind: str, text: str, count: int) -> tuple[str, dict[str, Any] | None]:
    """For select_best, pull the leading JSON out of the answer."""
    if kind != "select_best":
        return text, None
    match = _JSON_LINE.search(text)
    if not match:
        return text, None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return text, None
    best = data.get("best")
    ranking = [n for n in data.get("ranking", []) if isinstance(n, int) and 1 <= n <= count]
    if not isinstance(best, int) or not 1 <= best <= count:
        return text, None
    remaining = (text[: match.start()] + text[match.end() :]).strip().strip("`").strip()
    return remaining or text, {"best": best, "ranking": ranking}


def _row_to_result(conn: sqlite3.Connection, row: sqlite3.Row, cached: bool) -> AnalysisResult:
    asset_ids = [
        int(r[0])
        for r in conn.execute(
            "SELECT asset_id FROM ai_analysis_assets WHERE analysis_id = ? ORDER BY position",
            (row["id"],),
        )
    ]
    return AnalysisResult(
        id=row["id"],
        kind=row["kind"],
        provider=row["provider"],
        model=row["model"],
        language=row["language"],
        vision=bool(row["vision"]),
        cached=cached,
        result=row["result"],
        data=json.loads(row["data"]) if row["data"] else None,
        asset_ids=asset_ids,
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        created_at=row["created_at"],
    )


def analyze(
    conn: sqlite3.Connection, settings: AppSettings, cache_dir: Path, request: CloudRequest
) -> AnalysisResult:
    photos = _photos(conn, request)
    key = _cache_key(request, settings.cloud_model, photos)
    existing = conn.execute("SELECT * FROM ai_analysis WHERE cache_key = ?", (key,)).fetchone()
    if existing is not None:
        return _row_to_result(conn, existing, cached=True)

    deepseek = client(settings)
    logger.info(
        "cloud analysis",
        extra={
            "kind": request.kind,
            "model": deepseek.model,
            "photos": len(photos),
            "images": 0 if request.text_only else len(photos),
            "location": request.include_location,
        },
    )
    response = deepseek.chat(_messages(conn, cache_dir, request, photos), MAX_TOKENS[request.kind])
    text, data = _structured(request.kind, response.text.strip(), len(photos))

    with transaction(conn):
        cursor = conn.execute(
            """
            INSERT INTO ai_analysis (kind, provider, model, prompt_version, language, cache_key,
                                     vision, result, data, input_tokens, output_tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.kind, PROVIDER, deepseek.model, PROMPT_VERSION, request.language, key,
                0 if request.text_only else 1, text,
                json.dumps(data) if data is not None else None,
                response.input_tokens, response.output_tokens, utc_now(),
            ),
        )  # fmt: skip
        analysis_id = int(cursor.lastrowid or 0)
        conn.executemany(
            "INSERT INTO ai_analysis_assets (analysis_id, asset_id, position) VALUES (?, ?, ?)",
            [(analysis_id, photo.asset_id, i) for i, photo in enumerate(photos)],
        )
    row = conn.execute("SELECT * FROM ai_analysis WHERE id = ?", (analysis_id,)).fetchone()
    return _row_to_result(conn, row, cached=False)


def analyses_for_asset(conn: sqlite3.Connection, asset_id: int) -> list[AnalysisResult]:
    rows = conn.execute(
        """
        SELECT a.* FROM ai_analysis a
        JOIN ai_analysis_assets x ON x.analysis_id = a.id
        WHERE x.asset_id = ?
        ORDER BY a.id DESC
        """,
        (asset_id,),
    ).fetchall()
    return [_row_to_result(conn, row, cached=True) for row in rows]
