"""Playback copies of videos the app's web view cannot play (AVI, MTS, WMV, MPEG...).

An H.264 / AAC MP4, at most 1080 px on its long side, with the index first (so playback
starts at once and seeks), cached by the original's fingerprint. The original is only
read. Made on first play, by a task that reports its progress.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from lumen.media.fingerprint import fingerprint_digest

logger = logging.getLogger(__name__)

EDGE = 1080
VERSION = 1


class PlaybackError(Exception):
    """ffmpeg could not convert the video."""


def playback_path(cache_dir: Path, fingerprint: str) -> Path:
    digest = fingerprint_digest(fingerprint)
    return cache_dir / "playback" / digest[:2] / f"{digest}_v{VERSION}.mp4"


def command(ffmpeg: str, source: Path, target: Path) -> list[str]:
    # Long side at most EDGE (never enlarged), even sizes for H.264.
    scale = (
        f"scale='if(gt(iw,ih),min({EDGE},iw),-2)':'if(gt(iw,ih),-2,min({EDGE},ih))',"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p"
    )
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?", "-vf", scale,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2",
        "-movflags", "+faststart", "-progress", "pipe:1", "-nostats",
        "-f", "mp4", str(target),
    ]  # fmt: skip


def convert(
    ffmpeg: str,
    source: Path,
    target: Path,
    duration_ms: int | None,
    on_progress: Callable[[float], None] = lambda _: None,
) -> None:
    """Write the playback copy (atomically); ``on_progress`` gets 0..1 when the length is known."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part.mp4")
    process = subprocess.Popen(
        command(ffmpeg, source, partial),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert process.stdout is not None and process.stderr is not None
    try:
        for line in process.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and duration_ms and value.isdigit():
                on_progress(min(1.0, int(value) / 1000 / duration_ms))
        error = process.stderr.read()
        if process.wait() != 0:
            raise PlaybackError(
                error.strip().splitlines()[-1] if error.strip() else "ffmpeg failed"
            )
        os.replace(partial, target)
    except BaseException:
        process.kill()
        process.wait()
        partial.unlink(missing_ok=True)
        raise
