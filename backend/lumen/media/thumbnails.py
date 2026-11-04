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
        image = decode_still(source)
    else:
        raise RenderError(f"cannot render {media_format.kind} files")

    preview = _fit(image, PREVIEW_EDGE)
    save_jpeg(preview, target.preview)
    save_jpeg(_fit(preview, THUMB_EDGE), target.thumb)


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


def decode_still(source: Path, edge: int | None = PREVIEW_EDGE) -> Image.Image:
    """An oriented RGB image, decoded at no less than ``edge`` (full size if ``None``)."""
    try:
        with Image.open(source) as opened:
            if opened.format == "JPEG" and edge is not None:
                # Let libjpeg decode at reduced scale: much faster for large files.
                opened.draft("RGB", (edge, edge))
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


# Some exported videos (e.g. from messaging apps) carry reserved colour codes, which
# ffmpeg's filter graph rejects ("Invalid color space"). Retry with them rewritten to
# "unspecified" by a bitstream filter on the input; a filter for another codec just fails.
_COLOR_FIXES = tuple(
    ["-bsf:v", f"{codec}_metadata=colour_primaries=2:transfer_characteristics=2"
               ":matrix_coefficients=2"]
    for codec in ("h264", "hevc")
)  # fmt: skip


# Seek ~1s in to skip black lead-in frames; fall back to the first frame for short clips.
_POSTER_SEEKS = ("1", "0")


def video_frame_at(source: Path, ffmpeg: str, seconds: float, timeout: float = 120) -> Image.Image:
    """The (upright) frame shown at ``seconds`` into the video."""
    return _video_frame(source, ffmpeg, timeout, seeks=(f"{max(0.0, seconds):.3f}",))


def _video_frame(
    source: Path, ffmpeg: str, timeout: float = 120, *, seeks: tuple[str, ...] = _POSTER_SEEKS
) -> Image.Image:
    frame, stderr = _grab_frame(source, ffmpeg, [], timeout, seeks)
    if frame is None and b"Invalid color space" in stderr:
        for fix in _COLOR_FIXES:
            frame, _ = _grab_frame(source, ffmpeg, fix, timeout, seeks)
            if frame is not None:
                break
    if frame is None:
        # The first lines name the cause; the rest is ffmpeg unwinding.
        message = stderr.decode("utf-8", errors="replace").strip()[:300]
        raise RenderError(f"ffmpeg could not extract a frame: {message}")
    return frame


def _grab_frame(
    source: Path, ffmpeg: str, input_args: list[str], timeout: float, seeks: tuple[str, ...]
) -> tuple[Image.Image | None, bytes]:
    """Return the frame at the first position that works, or ``None`` and ffmpeg's error
    output."""
    stderr = b""
    # No stdin: ffmpeg polls it for keys, and on Windows that blocks for as long as the
    # backend's stdin watcher has a read pending on the inherited pipe (until the timeout).
    for seek in seeks:
        command = [
            ffmpeg, "-nostdin", "-v", "error", "-ss", seek, *input_args, "-i", str(source),
            "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
        ]  # fmt: skip
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderError("ffmpeg timed out") from exc
        if completed.returncode == 0 and completed.stdout:
            with Image.open(io.BytesIO(completed.stdout)) as frame:
                return _to_rgb(frame), b""
        stderr = completed.stderr
    return None, stderr


def save_jpeg(
    image: Image.Image,
    target: Path,
    *,
    quality: int = JPEG_QUALITY,
    icc_profile: bytes | None = None,
) -> None:
    """Write ``image`` to ``target`` atomically (never a half-written file)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    extra = {"icc_profile": icc_profile} if icc_profile else {}
    try:
        with os.fdopen(handle, "wb") as out:
            image.save(out, "JPEG", quality=quality, optimize=True, progressive=True, **extra)
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
