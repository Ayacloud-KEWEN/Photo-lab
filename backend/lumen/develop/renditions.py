"""Thumbnails and previews of edited photos, cached next to the unedited ones.

They are named after the developed file's fingerprint *and* the recipe hash, so every
version of an edit has its own files and undoing an edit finds its renditions again.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from lumen.develop import engine
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


def full_rendition_path(cache_dir: Path, fingerprint: str, recipe_hash: str) -> Path:
    """The full-size rendition (``recipe_hash`` '' for the unedited photo)."""
    digest = fingerprint_digest(fingerprint)
    edit = f"_e{recipe_hash}" if recipe_hash else ""
    return cache_dir / "renditions" / digest[:2] / f"{digest}{edit}_f{engine.DEVELOP_VERSION}.jpg"


def render_full(source: Path, media_format: MediaFormat, recipe: EditRecipe, target: Path) -> None:
    """Develop ``source`` at full size into ``target`` (skipped if it exists), keeping the
    original's colour profile so the browser shows its colours faithfully."""
    if target.exists():
        return
    image = engine.develop(source, media_format, recipe, None, cache=False)
    thumbnails.save_jpeg(
        image,
        target,
        quality=FULL_QUALITY,
        icc_profile=engine.source_icc_profile(source, media_format),
    )


def render_edited(
    source: Path, media_format: MediaFormat, recipe: EditRecipe, target: thumbnails.Rendition
) -> None:
    """Develop ``source`` with ``recipe`` into ``target`` (skips work if both exist)."""
    if target.exists():
        return
    preview = engine.develop(source, media_format, recipe, thumbnails.PREVIEW_EDGE)
    thumbnails.save_jpeg(preview, target.preview)
    thumb = preview.copy()
    thumb.thumbnail((thumbnails.THUMB_EDGE, thumbnails.THUMB_EDGE), Image.Resampling.LANCZOS)
    thumbnails.save_jpeg(thumb, target.thumb)
