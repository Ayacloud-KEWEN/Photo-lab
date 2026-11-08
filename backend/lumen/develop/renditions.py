"""Thumbnails and previews of edited photos, cached next to the unedited ones.

They are named after the developed file's fingerprint *and* the recipe hash, so every
version of an edit has its own files and undoing an edit finds its renditions again.
"""

from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path

from PIL import Image

from lumen.develop import engine, live
from lumen.develop.recipe import EditRecipe
from lumen.media import thumbnails
from lumen.media.fingerprint import fingerprint_digest
from lumen.media.formats import MediaFormat


def edited_rendition_paths(
    cache_dir: Path, fingerprint: str, recipe_hash: str
) -> thumbnails.Rendition:
    digest = fingerprint_digest(fingerprint)
    folder = cache_dir / "renditions" / digest[:2]
    stem = f"{digest}_e{recipe_hash}"
    return thumbnails.Rendition(
        thumb=folder / f"{stem}_t{engine.DEVELOP_VERSION}.jpg",
        preview=folder / f"{stem}_p{engine.DEVELOP_VERSION}.jpg",
    )


FULL_QUALITY = 90
# Full-size renditions are 2-6 MB each: keep the most recently used ones within this.
FULL_CACHE_LIMIT = 2 * 1024**3
# Full-size photos, long exposures and Live Photo playback clips (ADR-037).
_FULL_NAME = re.compile(
    r"[0-9a-f]+(?:(?:_e[0-9a-f]+)?_f\d+\.jpg|_lx\d+\.png|_(?:live|loop|bounce)[0-9a-f]+_m\d+\.mp4)"
)


def full_rendition_path(cache_dir: Path, fingerprint: str, recipe_hash: str) -> Path:
    """The full-size rendition (``recipe_hash`` '' for the unedited photo)."""
    digest = fingerprint_digest(fingerprint)
    edit = f"_e{recipe_hash}" if recipe_hash else ""
    return cache_dir / "renditions" / digest[:2] / f"{digest}{edit}_f{engine.DEVELOP_VERSION}.jpg"


def render_full(
    source: Path,
    media_format: MediaFormat,
    recipe: EditRecipe,
    target: Path,
    *,
    motion: live.Clip | None = None,
) -> None:
    """Develop ``source`` at full size into ``target`` (skipped if it exists), keeping the
    original's colour profile so the browser shows its colours faithfully."""
    if target.exists():
        return
    image = engine.develop(source, media_format, recipe, None, cache=False, motion=motion)
    thumbnails.save_jpeg(
        image,
        target,
        quality=FULL_QUALITY,
        icc_profile=engine.icc_profile(source, media_format, recipe, motion),
    )


def touch(path: Path) -> None:
    """Mark a cached rendition as just used (pruning removes the least recently used)."""
    with contextlib.suppress(OSError):
        os.utime(path)


def prune_full_renditions(
    cache_dir: Path, limit: int = FULL_CACHE_LIMIT, *, keep: Path | None = None
) -> int:
    """Delete the least recently used full-size renditions beyond ``limit`` bytes (never
    ``keep``); returns how many were deleted. Other renditions are small and stay."""
    entries: list[tuple[float, int, Path]] = []
    for path in (cache_dir / "renditions").glob("*/*_*"):
        if not _FULL_NAME.fullmatch(path.name):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, path))
    total = sum(size for _, size, _ in entries)
    removed = 0
    for _, size, path in sorted(entries):  # oldest first
        if total <= limit:
            break
        if keep is not None and path == keep:
            continue
        try:
            path.unlink()
        except OSError:  # e.g. being served right now: next time
            continue
        total -= size
        removed += 1
    return removed


def render_edited(
    source: Path,
    media_format: MediaFormat,
    recipe: EditRecipe,
    target: thumbnails.Rendition,
    *,
    motion: live.Clip | None = None,
) -> None:
    """Develop ``source`` with ``recipe`` into ``target`` (skips work if both exist)."""
    if target.exists():
        return
    preview = engine.develop(source, media_format, recipe, thumbnails.PREVIEW_EDGE, motion=motion)
    thumbnails.save_jpeg(preview, target.preview)
    thumb = preview.copy()
    thumb.thumbnail((thumbnails.THUMB_EDGE, thumbnails.THUMB_EDGE), Image.Resampling.LANCZOS)
    thumbnails.save_jpeg(thumb, target.thumb)
