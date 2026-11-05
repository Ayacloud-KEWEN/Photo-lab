"""Photo quality (ADR-025): sharpness and exposure, measured on the 2048 px preview.

Sharpness compares second and first derivatives at the strongest 0.5% of edges: a blurred
edge spreads its gradient, so the Laplacian there is small relative to the gradient. Photos
with no real edges (an even wall) are left neutral rather than called blurry, and images
smaller than 1600 px (received or downloaded pictures, soft because of their size) are
never flagged. Exposure is the share of clipped highlights and crushed shadows;
screenshots and graphics (PNG) are not judged on it. Calibrated on the user's library
(480 phone photos): the ratio is 0.28 at the 2nd percentile and 0.41 at the median, and
accidental shots score about 0.23. Shallow-focus close-ups can score as low, so flags are
suggestions for the user to confirm.
"""

from __future__ import annotations

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from lumen.db.connection import transaction, utc_now
from lumen.media import thumbnails
from lumen.tasks.runner import TaskContext

logger = logging.getLogger(__name__)

QUALITY_TASK = "quality_score_assets"
VERSION = 1
BATCH_SIZE = 64
_SIZE = 1024
BLURRY_RATIO = 0.25
_RATIO_RANGE = (0.18, 0.55)  # mapped to sharpness 0..1
_NEUTRAL_SHARPNESS = 0.6  # no edges to judge
_MIN_EDGE_SHARE = 0.001
_MIN_JUDGED_EDGE = 1600  # px


@dataclass(frozen=True)
class Quality:
    sharpness: float
    exposure: float
    highlights: float
    shadows: float
    score: float
    flags: tuple[str, ...]


def measure(gray: np.ndarray, *, judge_exposure: bool = True) -> Quality:
    """Quality of an 8-bit grayscale image."""
    h, w = gray.shape
    judge_sharpness = max(h, w) >= _MIN_JUDGED_EDGE
    scale = _SIZE / max(h, w)
    if scale < 1:
        gray = cv2.resize(gray, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    image = gray.astype(np.float32)
    gx = cv2.Sobel(image, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(image, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(gx, gy)
    laplacian = np.abs(cv2.Laplacian(image, cv2.CV_32F, ksize=3))
    edges = magnitude >= max(float(np.percentile(magnitude, 99.5)), 20.0)

    flags: list[str] = []
    if float(edges.mean()) < _MIN_EDGE_SHARE:
        sharpness = _NEUTRAL_SHARPNESS
    else:
        ratio = float(laplacian[edges].mean() / magnitude[edges].mean())
        low, high = _RATIO_RANGE
        sharpness = float(np.clip((ratio - low) / (high - low), 0.0, 1.0))
        if ratio < BLURRY_RATIO and judge_sharpness:
            flags.append("blurry")

    highlights = float((gray >= 250).mean())
    shadows = float((gray <= 5).mean())
    exposure = 1.0
    if judge_exposure:
        exposure = float(
            np.clip(1 - 2 * max(0.0, highlights - 0.05) - 2 * max(0.0, shadows - 0.10), 0, 1)
        )
        mean = float(gray.mean())
        if highlights > 0.35 and mean > 200:
            flags.append("overexposed")
        if shadows > 0.45 and mean < 30:
            flags.append("underexposed")
    score = round(0.7 * sharpness + 0.3 * exposure, 4)
    return Quality(
        round(sharpness, 4), round(exposure, 4), round(highlights, 4), round(shadows, 4),
        score, tuple(flags),
    )  # fmt: skip


def measure_file(path: Path, *, judge_exposure: bool = True) -> Quality | None:
    data = np.fromfile(str(path), dtype=np.uint8) if path.is_file() else None
    gray = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE) if data is not None else None
    return None if gray is None else measure(gray, judge_exposure=judge_exposure)


# Photos whose cover was measured with another method or content (or never).
_PENDING = """
    FROM media_assets a
    JOIN media_files c ON c.id = a.cover_file_id
         AND c.ingest_state = 'done' AND c.status = 'present' AND c.fingerprint IS NOT NULL
    LEFT JOIN media_quality q ON q.asset_id = a.id
    WHERE a.media_type = 'photo'
      AND (q.asset_id IS NULL OR q.version != ? OR q.fingerprint != c.fingerprint)
"""


def measure_preview(cache_dir: Path, fingerprint: str, extension: str) -> Quality | None:
    """Quality of a photo from its preview file (PNG: screenshots, not judged on exposure)."""
    preview = thumbnails.rendition_paths(cache_dir, fingerprint).preview
    return measure_file(preview, judge_exposure=extension != "png")


def store_quality(
    conn: sqlite3.Connection, asset_id: int, fingerprint: str, quality: Quality | None, now: str
) -> None:
    """Record a measurement (None: the preview could not be read). Call in a transaction."""
    values = (
        (None,) * 5 + ("",)
        if quality is None
        else (
            quality.sharpness, quality.exposure, quality.highlights,
            quality.shadows, quality.score, ",".join(quality.flags),
        )
    )  # fmt: skip
    conn.execute(
        """
        INSERT INTO media_quality (asset_id, fingerprint, version, sharpness,
            exposure, highlights, shadows, score, flags, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (asset_id) DO UPDATE SET
            fingerprint = excluded.fingerprint, version = excluded.version,
            sharpness = excluded.sharpness, exposure = excluded.exposure,
            highlights = excluded.highlights, shadows = excluded.shadows,
            score = excluded.score, flags = excluded.flags,
            updated_at = excluded.updated_at
        """,
        (asset_id, fingerprint, VERSION, *values, now),
    )


def needs_scoring(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute(f"SELECT EXISTS (SELECT 1 {_PENDING})", (VERSION,)).fetchone()[0])


def score_assets(ctx: TaskContext) -> dict[str, int]:
    conn = ctx.conn
    total = conn.execute(f"SELECT COUNT(*) {_PENDING}", (VERSION,)).fetchone()[0]
    done = 0
    workers = ctx.settings.ingest_workers
    with ThreadPoolExecutor(workers, thread_name_prefix="quality") as pool:
        while True:
            ctx.check()
            rows = conn.execute(
                f"SELECT a.id, c.fingerprint, c.extension {_PENDING} ORDER BY a.id LIMIT ?",
                (VERSION, BATCH_SIZE),
            ).fetchall()
            if not rows:
                break

            def one(row: sqlite3.Row) -> Quality | None:
                return measure_preview(ctx.settings.cache_dir, row[1], row[2])

            results = list(pool.map(one, rows))
            now = utc_now()
            with transaction(conn):
                for row, quality in zip(rows, results, strict=True):
                    store_quality(conn, row[0], row[1], quality, now)
            done += len(rows)
            ctx.progress(done, max(total, done))
    return {"scored": done}
