"""Exporting edited videos (and single frames) with FFmpeg.

Like photo exports, the results are new files in a folder the user chose; nothing is
ever replaced and the original is only read. All ffmpeg runs have no stdin (see
``lumen.media.thumbnails``) and can be stopped while they run.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image

from lumen.develop import lut
from lumen.develop.exporter import reserve_path
from lumen.develop.recipe import VideoRecipe
from lumen.media import thumbnails

VideoMode = Literal["copy", "h264"]

# Rotations clockwise, as filters for re-encoding.
_TURNS = {1: "transpose=clock", 2: "transpose=clock,transpose=clock", 3: "transpose=cclock"}


class VideoExportError(Exception):
    pass


class VideoExportStopped(Exception):
    """``should_stop`` asked to stop; ffmpeg was ended and nothing was kept."""


@dataclass(frozen=True)
class VideoOptions:
    mode: VideoMode = "copy"
    include_metadata: bool = True
    include_location: bool = False


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.3f}"


def probe_rotation(ffprobe: str | None, source: Path) -> int:
    """The display rotation stored in the file (degrees counter-clockwise, as ffmpeg)."""
    if not ffprobe:
        return 0
    completed = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream_side_data=rotation", "-of", "csv=p=0", str(source),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )  # fmt: skip
    for line in completed.stdout.split():
        try:
            return round(float(line.strip(",")))
        except ValueError:
            continue
    return 0


def effective_mode(recipe: VideoRecipe, options: VideoOptions) -> str:
    """A LUT changes the pixels, so the video is re-encoded whatever the option says."""
    return "h264" if recipe.lut and recipe.lut_strength > 0 else options.mode


def lut_filters(recipe: VideoRecipe) -> list[str]:
    """ffmpeg filters grading with the recipe's LUT (mixed in at its strength)."""
    if not recipe.lut or recipe.lut_strength <= 0:
        return []
    lut_id, _space = lut.split_ref(recipe.lut)
    # Inside a filter graph the drive letter's colon must be escaped.
    path = (lut.store_folder() / f"{lut_id}.cube").as_posix().replace(":", "\\:")
    graded = f"lut3d=file='{path}'"
    if recipe.lut_strength >= 100:
        return [graded]
    opacity = f"{recipe.lut_strength / 100:.3f}"
    return [
        f"split[lumen_a][lumen_b];[lumen_b]{graded}[lumen_g];"
        f"[lumen_g][lumen_a]blend=all_mode=normal:all_opacity={opacity}"
    ]


def grade_frame(image: Image.Image, recipe: VideoRecipe) -> Image.Image:
    """A frame of the video with the recipe's LUT (video frames are Rec.709)."""
    if not recipe.lut or recipe.lut_strength <= 0:
        return image
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32) / np.float32(255)
    graded = lut.grade(pixels, recipe.lut, recipe.lut_strength / 100, "srgb")
    return Image.fromarray((np.clip(graded, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def build_command(
    ffmpeg: str,
    source: Path,
    target: Path,
    recipe: VideoRecipe,
    options: VideoOptions,
    *,
    stored_rotation: int = 0,
) -> list[str]:
    """The ffmpeg command line for one export (exposed for tests)."""
    command = [ffmpeg, "-nostdin", "-v", "error", "-y"]
    mode = effective_mode(recipe, options)
    if mode == "copy" and recipe.rotate:
        # Without re-encoding, rotation is metadata: the stored one turned further.
        angle = (stored_rotation - 90 * recipe.rotate + 180) % 360 - 180
        command += ["-display_rotation:v:0", str(angle)]
    if recipe.trim_start_ms:
        command += ["-ss", _seconds(recipe.trim_start_ms)]
    command += ["-i", str(source)]
    if recipe.trim_end_ms is not None:
        command += ["-t", _seconds(recipe.trim_end_ms - recipe.trim_start_ms)]
    command += ["-map", "0:v:0"]
    if not recipe.mute:
        command += ["-map", "0:a:0?"]  # the main track; not spatial audio or data tracks

    if mode == "copy":
        command += ["-c", "copy"]
    else:
        filters = [_TURNS[recipe.rotate]] if recipe.rotate else []
        filters += lut_filters(recipe)
        filters.append("format=yuv420p")  # 8-bit 4:2:0, playable everywhere
        command += [
            "-vf", ",".join(filters),
            "-c:v", "libx264", "-crf", "20", "-preset", "medium",
            "-c:a", "aac", "-b:a", "192k",
        ]  # fmt: skip

    if not options.include_metadata:
        command += ["-map_metadata", "-1", "-movflags", "+faststart"]
    else:
        # Keep QuickTime keys (make, model, creation date) as well as the standard ones.
        command += ["-map_metadata", "0", "-movflags", "+faststart+use_metadata_tags"]
        if not options.include_location:
            command += ["-metadata", "location=", "-metadata", "location-eng="]
            command += ["-metadata", "com.apple.quicktime.location.ISO6709="]
    command.append(str(target))
    return command


def export_video(
    source: Path,
    recipe: VideoRecipe,
    folder: Path,
    options: VideoOptions,
    *,
    ffmpeg: str,
    ffprobe: str | None,
    should_stop: Callable[[], bool],
    stem: str | None = None,
) -> Path:
    """Write the edited video as a new file in ``folder``; returns its path.

    Copying keeps the original quality and container (cut points snap to keyframes);
    H.264 re-encodes to an MP4 that plays everywhere.
    """
    mode = effective_mode(recipe, options)
    extension = source.suffix.lower() if mode == "copy" else ".mp4"
    target = reserve_path(folder, stem or source.stem, extension)
    handle, temp_name = tempfile.mkstemp(dir=folder, prefix=".lumen-", suffix=extension)
    os.close(handle)
    try:
        rotation = probe_rotation(ffprobe, source) if mode == "copy" else 0
        command = build_command(
            ffmpeg, source, Path(temp_name), recipe, options, stored_rotation=rotation
        )
        _run(command, should_stop)
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return target


def _run(command: list[str], should_stop: Callable[[], bool]) -> None:
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=errors,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            while process.poll() is None:
                if should_stop():
                    process.kill()
                    process.wait()
                    raise VideoExportStopped()
                time.sleep(0.25)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        if process.returncode != 0:
            errors.seek(0)
            message = errors.read().decode("utf-8", errors="replace").strip()[:300]
            raise VideoExportError(f"ffmpeg failed: {message}")


def export_frame(
    source: Path,
    recipe: VideoRecipe,
    time_ms: int,
    folder: Path,
    *,
    ffmpeg: str,
    quality: int = 92,
) -> Path:
    """Save the frame at ``time_ms`` (turned like the video) as a new JPEG in ``folder``."""
    image = thumbnails.video_frame_at(source, ffmpeg, time_ms / 1000)
    if recipe.rotate:
        image = image.rotate(-90 * recipe.rotate, expand=True)
    image = grade_frame(image, recipe)
    seconds = time_ms // 1000
    target = reserve_path(folder, f"{source.stem}_{seconds // 60:02d}-{seconds % 60:02d}", ".jpg")
    try:
        with target.open("wb") as out:
            image.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target
