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
