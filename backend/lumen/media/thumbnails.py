"""Thumbnail and preview rendering.

Originals are only ever opened for reading. Output goes to the cache directory,
named after the file's content fingerprint, written atomically.
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps

from lumen.media.fingerprint import fingerprint_digest
from lumen.media.formats import MediaFormat

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover - HEIC support is optional at import time
    pass

# Very large panoramas are legitimate photos, not decompression bombs.
Image.MAX_IMAGE_PIXELS = 600_000_000

THUMB_EDGE = 400  # grid tiles (sharp at 200px on 2x displays)
PREVIEW_EDGE = 2048  # full-screen viewing before loading the original
JPEG_QUALITY = 82
RENDERER_VERSION = 1

Variant = Literal["thumb", "preview"]

# Identical files (duplicates) share renditions: render each fingerprint once at a time.
_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(path, threading.Lock())


class RenderError(Exception):
    pass


@dataclass(frozen=True)
class Rendition:
    thumb: Path
    preview: Path

    def exists(self) -> bool:
        return self.thumb.exists() and self.preview.exists()


def rendition_paths(cache_dir: Path, fingerprint: str) -> Rendition:
    digest = fingerprint_digest(fingerprint)
    folder = cache_dir / "renditions" / digest[:2]
    return Rendition(
        thumb=folder / f"{digest}_t{RENDERER_VERSION}.jpg",
        preview=folder / f"{digest}_p{RENDERER_VERSION}.jpg",
    )


def render(
    source: Path,
    media_format: MediaFormat,
    target: Rendition,
    *,
    ffmpeg: str | None,
) -> None:
    """Create the thumbnail and preview for ``source`` (skips work if both exist)."""
    if target.exists():
        return
    lock = _lock_for(target.thumb)
    with lock:
        if not target.exists():
            _render(source, media_format, target, ffmpeg=ffmpeg)
    with _locks_guard:
        _locks.pop(target.thumb, None)


def _render(
    source: Path, media_format: MediaFormat, target: Rendition, *, ffmpeg: str | None
) -> None:
    if media_format.kind == "video":
        if not ffmpeg:
            raise RenderError("ffmpeg is not available")
        image = _video_frame(source, ffmpeg)
    elif media_format.kind == "raw":
        image = _raw_image(source)
    elif media_format.kind in ("jpeg", "heic", "png", "tiff"):
        image = _still_image(source)
    else:
        raise RenderError(f"cannot render {media_format.kind} files")

    preview = _fit(image, PREVIEW_EDGE)
    _save_jpeg(preview, target.preview)
    _save_jpeg(_fit(preview, THUMB_EDGE), target.thumb)


def _fit(image: Image.Image, edge: int) -> Image.Image:
    if max(image.size) <= edge:
        return image
    copy = image.copy()
    copy.thumbnail((edge, edge), Image.Resampling.LANCZOS, reducing_gap=3.0)
    return copy


def _to_rgb(image: Image.Image) -> Image.Image:
    """Return a fully loaded RGB copy (safe to use after the source file is closed)."""
    if image.mode == "RGB":
        return image.copy()
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (19, 19, 19))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    if image.mode in ("I;16", "I;16B", "I;16L", "I"):
        return image.point(lambda value: value / 256).convert("RGB")
    return image.convert("RGB")


def _still_image(source: Path) -> Image.Image:
    try:
        with Image.open(source) as opened:
            if opened.format == "JPEG":
                # Let libjpeg decode at reduced scale: much faster for large files.
                opened.draft("RGB", (PREVIEW_EDGE, PREVIEW_EDGE))
            oriented = ImageOps.exif_transpose(opened)
            return _to_rgb(oriented)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise RenderError(f"cannot decode image: {exc}") from exc


_FLIP_TO_ROTATION = {3: 180, 5: 90, 6: 270}  # LibRaw flip -> PIL counter-clockwise degrees


def _raw_image(source: Path) -> Image.Image:
    import rawpy

    try:
        with rawpy.imread(str(source)) as raw:
            flip = int(getattr(raw.sizes, "flip", 0) or 0)
            embedded = _embedded_preview(raw)
            if embedded is not None and max(embedded.size) >= THUMB_EDGE:
                rotation = _FLIP_TO_ROTATION.get(flip)
                return embedded.rotate(rotation, expand=True) if rotation else embedded
            # No usable embedded preview: demosaic at half size (already oriented).
            rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
            return Image.fromarray(rgb)
    except (rawpy.LibRawError, OSError, ValueError) as exc:
        raise RenderError(f"cannot decode RAW file: {exc}") from exc


def _embedded_preview(raw: object) -> Image.Image | None:
    import rawpy

    try:
        thumb = raw.extract_thumb()  # type: ignore[attr-defined]
    except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
        return None
    try:
        if thumb.format == rawpy.ThumbFormat.JPEG:
            with Image.open(io.BytesIO(thumb.data)) as opened:
                opened.draft("RGB", (PREVIEW_EDGE, PREVIEW_EDGE))
                return _to_rgb(opened)
        if thumb.format == rawpy.ThumbFormat.BITMAP:
            return Image.fromarray(thumb.data).convert("RGB")
    except (OSError, ValueError):
        return None
    return None


def _video_frame(source: Path, ffmpeg: str, timeout: float = 120) -> Image.Image:
    # Seek ~1s in to skip black lead-in frames; fall back to the first frame for short clips.
    for seek in ("1", "0"):
        command = [
            ffmpeg, "-v", "error", "-ss", seek, "-i", str(source),
            "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
        ]  # fmt: skip
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderError("ffmpeg timed out") from exc
        if completed.returncode == 0 and completed.stdout:
            with Image.open(io.BytesIO(completed.stdout)) as frame:
                return _to_rgb(frame)
    raise RenderError(f"ffmpeg could not extract a frame: {completed.stderr[-300:]!r}")


def _save_jpeg(image: Image.Image, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            image.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
