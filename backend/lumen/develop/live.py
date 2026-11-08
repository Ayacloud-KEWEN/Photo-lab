"""Live Photo clips as pictures and as motion (ADR-037).

A Live Photo's clip can stand in for its still: one chosen frame, or a long exposure that
blends every frame after aligning them. The clip can also be rendered as a loop, a
bounce or the clip itself, with the photo's adjustments applied to every frame, for
playback and for export as MP4 or GIF.

Frames are RGB in the clip's own colour space. iPhone clips are Display P3 like the
stills, so a frame developed as a picture keeps the still's colour profile; motion
outputs (video and GIF players are not colour managed alike) are converted to sRGB.

Nothing here touches the database; the original clip is only read.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import subprocess
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import cv2
import numpy as np
import numpy.typing as npt
from PIL import Image

from lumen.develop.recipe import EditRecipe
from lumen.media.fingerprint import fingerprint_digest

if TYPE_CHECKING:
    from lumen.core.config import Settings

logger = logging.getLogger(__name__)

# Bump when long exposures or motion renders change, so cached ones are recreated.
LIVE_VERSION = 1

Array = npt.NDArray[np.float32]
Frame = npt.NDArray[np.uint8]

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_cv: Any = cv2  # OpenCV's stubs reject None for optional output arrays
_TIMEOUT = 300
# Clips whose colour tags ffmpeg rejects are read with the tags cleared (see thumbnails).
_COLOR_FIXES: tuple[list[str], ...] = (
    [],
    *(
        ["-bsf:v", f"{codec}_metadata=colour_primaries=2:transfer_characteristics=2"
                   ":matrix_coefficients=2"]
        for codec in ("h264", "hevc")
    ),
)  # fmt: skip


class LiveError(Exception):
    """The clip cannot be read or rendered."""


class LiveStopped(Exception):
    """A motion export was cancelled."""


@dataclass(frozen=True)
class Tools:
    ffmpeg: str | None
    ffprobe: str | None
    cache_dir: Path

    @classmethod
    def of(cls, settings: Settings) -> Tools:
        return cls(settings.tool("ffmpeg"), settings.tool("ffprobe"), settings.cache_dir)


@dataclass(frozen=True)
class Clip:
    """A Live Photo's motion clip on disk and how to work with it."""

    path: Path
    fingerprint: str
    tools: Tools

    def ffmpeg(self) -> str:
        if self.tools.ffmpeg is None:
            raise LiveError("ffmpeg is not available")
        return self.tools.ffmpeg


@dataclass(frozen=True)
class ClipInfo:
    width: int = 0  # upright (after the display rotation)
    height: int = 0
    duration_ms: int = 0
    frame_times_ms: tuple[int, ...] = ()
    still_ms: int | None = None  # where the still was taken, when the clip records it
    wide_gamut: bool = False  # Display P3 (iPhone) rather than sRGB/BT.709
    has_audio: bool = False

    @property
    def fps(self) -> float:
        times = self.frame_times_ms
        if len(times) < 2 or times[-1] <= times[0]:
            return 30.0
        return min(60.0, max(1.0, (len(times) - 1) * 1000 / (times[-1] - times[0])))


# --- Probing --------------------------------------------------------------------------------

_info_cache: OrderedDict[tuple[str, int, int], ClipInfo] = OrderedDict()
_info_lock = threading.Lock()


def _stat_key(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise LiveError(f"cannot read the clip: {exc}") from exc
    return (str(path), stat.st_mtime_ns, stat.st_size)


def probe(clip: Clip) -> ClipInfo:
    """Size, frame times and the still's position of ``clip`` (cached per file version)."""
    key = _stat_key(clip.path)
    with _info_lock:
        if key in _info_cache:
            _info_cache.move_to_end(key)
            return _info_cache[key]
    if clip.tools.ffprobe is None:
        raise LiveError("ffprobe is not available")
    command = [
        clip.tools.ffprobe, "-v", "error", "-of", "json",
        "-show_entries",
        "stream=index,codec_type,width,height,start_time,duration,color_primaries"
        ":stream_side_data=rotation:format=duration:packet=stream_index,pts_time",
        str(clip.path),
    ]  # fmt: skip
    output = _run(command, capture=True)
    try:
        info = parse_probe(json.loads(output))
    except (ValueError, KeyError, TypeError) as exc:
        raise LiveError(f"cannot read the clip's streams: {exc}") from exc
    with _info_lock:
        _info_cache[key] = info
        while len(_info_cache) > 64:
            _info_cache.popitem(last=False)
    return info


def parse_probe(data: Any) -> ClipInfo:
    """ffprobe's JSON (streams, format, packets) as a ``ClipInfo``."""
    streams: list[dict[str, Any]] = data.get("streams") or []
    if not isinstance(streams, list):
        raise ValueError("no streams")
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("no video stream")
    width, height = int(video["width"]), int(video["height"])
    rotation = 0
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            rotation = round(float(side["rotation"]))
    if abs(rotation) % 180 == 90:
        width, height = height, width

    # Packets before the start of the clip's edit list have negative times: they are only
    # decoded to reach the first shown frame and are never output, so they are skipped to
    # keep the times in step with the decoded frames.
    times: list[int] = []
    for packet in data.get("packets") or []:
        if packet.get("stream_index") != video.get("index") or "pts_time" not in packet:
            continue
        pts = float(packet["pts_time"])
        if pts >= -0.0005:
            times.append(max(0, round(pts * 1000)))
    times.sort()
    fmt = data.get("format")
    duration_s = fmt.get("duration") if isinstance(fmt, dict) else None
    duration_ms = int(float(duration_s or video.get("duration") or 0) * 1000)

    # iPhone clips mark the still with a metadata track holding a single, very short
    # sample: it starts where the still was taken.
    still_ms: int | None = None
    for stream in streams:
        if stream.get("codec_type") != "data":
            continue
        start, length = stream.get("start_time"), stream.get("duration")
        if start is None or length is None:
            continue
        if float(length) < 0.05 and 0 < float(start) * 1000 <= max(duration_ms, 1):
            still_ms = int(float(start) * 1000)
    return ClipInfo(
        width=width,
        height=height,
        duration_ms=duration_ms,
        frame_times_ms=tuple(times),
        still_ms=still_ms,
        wide_gamut=video.get("color_primaries") in ("smpte432", "smpte431"),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


# --- Decoding -------------------------------------------------------------------------------


def fit(width: int, height: int, edge: int | None) -> tuple[int, int]:
    """``width`` x ``height`` scaled down to at most ``edge`` on the long side."""
    if edge is None or max(width, height) <= edge:
        return width, height
    scale = edge / max(width, height)
    return max(2, round(width * scale)), max(2, round(height * scale))


def frames(clip: Clip, edge: int | None = None) -> Iterator[Frame]:
    """Every frame of ``clip``, upright, as uint8 RGB arrays at most ``edge`` px."""
    info = probe(clip)
    width, height = fit(info.width, info.height, edge)
    last_error = ""
    for fix in _COLOR_FIXES:
        produced = 0
        try:
            for frame in _decode(clip, fix, width, height):
                produced += 1
                yield frame
            return
        except LiveError as exc:
            if produced:  # failed half way: not a colour-tag problem
                raise
            last_error = str(exc)
            if "color" not in last_error.lower():
                break
    raise LiveError(last_error or "cannot decode the clip")


def _decode(clip: Clip, input_args: list[str], width: int, height: int) -> Iterator[Frame]:
    command = [
        clip.ffmpeg(), "-nostdin", "-v", "error", *input_args, "-i", str(clip.path),
        "-map", "0:v:0", "-an", "-fps_mode", "passthrough",
        "-vf", f"scale={width}:{height}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]  # fmt: skip
    size = width * height * 3
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=errors,
            creationflags=_NO_WINDOW,
        )
        assert process.stdout is not None
        try:
            while True:
                data = process.stdout.read(size)
                if len(data) < size:
                    break
                yield np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait()
        if process.returncode != 0:
            errors.seek(0)
            message = errors.read().decode("utf-8", errors="replace").strip()[:300]
            raise LiveError(f"ffmpeg could not decode the clip: {message}")


def frame_at(clip: Clip, time_ms: int, edge: int | None = None) -> Frame:
    """The frame shown at ``time_ms`` (the last one at or before it)."""
    info = probe(clip)
    times = info.frame_times_ms
    wanted = 0
    for index, start in enumerate(times):
        if start <= time_ms:
            wanted = index
    for index, frame in enumerate(frames(clip, edge)):
        if index >= wanted:
            return frame.copy()
    raise LiveError("the clip has no frames")


def to_float(frame: Frame) -> Array:
    return frame.astype(np.float32) / np.float32(255)


def to_uint8(image: Array) -> Frame:
    return (np.clip(image, 0, 1) * 255 + 0.5).astype(np.uint8)


# --- Frame analysis: the strip and the sharpest frame -----------------------------------------

STRIP_TILES = 10
STRIP_HEIGHT = 96
_ANALYSIS_EDGE = 480


@dataclass(frozen=True)
class Analysis:
    info: ClipInfo
    sharpness: tuple[float, ...]  # per frame, 0..1 relative to the sharpest
    recommended_ms: int | None
    strip: bytes  # JPEG: STRIP_TILES frames side by side, evenly spaced in time


_analysis_cache: OrderedDict[tuple[str, int, int], Analysis] = OrderedDict()
_analysis_lock = threading.Lock()


def analyse(clip: Clip) -> Analysis:
    """Sharpness of every frame, the recommended (sharpest) one and a strip of thumbnails."""
    key = _stat_key(clip.path)
    with _analysis_lock:
        if key in _analysis_cache:
            _analysis_cache.move_to_end(key)
            return _analysis_cache[key]
    info = probe(clip)
    scores: list[float] = []
    small: list[Frame] = []
    for frame in frames(clip, _ANALYSIS_EDGE):
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        scores.append(float(cv2.Laplacian(gray, cv2.CV_32F).var()))
        small.append(frame)
    if not small:
        raise LiveError("the clip has no frames")
    times = list(info.frame_times_ms[: len(small)])
    while len(times) < len(small):  # fewer packets than frames: spread evenly
        times.append(round(len(times) * 1000 / info.fps))
    best = max(scores) or 1.0
    recommended = times[int(np.argmax(scores))]

    tile_w = max(1, round(STRIP_HEIGHT * small[0].shape[1] / small[0].shape[0]))
    strip = Image.new("RGB", (tile_w * STRIP_TILES, STRIP_HEIGHT))
    for tile in range(STRIP_TILES):
        index = min(len(small) - 1, round(tile * (len(small) - 1) / max(1, STRIP_TILES - 1)))
        image = Image.fromarray(small[index]).resize(
            (tile_w, STRIP_HEIGHT), Image.Resampling.BILINEAR
        )
        strip.paste(image, (tile * tile_w, 0))
    out = io.BytesIO()
    strip.save(out, "JPEG", quality=80)

    analysis = Analysis(
        info=ClipInfo(
            width=info.width,
            height=info.height,
            duration_ms=info.duration_ms,
            frame_times_ms=tuple(times),
            still_ms=info.still_ms,
            wide_gamut=info.wide_gamut,
            has_audio=info.has_audio,
        ),
        sharpness=tuple(round(score / best, 4) for score in scores),
        recommended_ms=recommended,
        strip=out.getvalue(),
    )
    with _analysis_lock:
        _analysis_cache[key] = analysis
        while len(_analysis_cache) > 16:
            _analysis_cache.popitem(last=False)
    return analysis


# --- Long exposure --------------------------------------------------------------------------

_ALIGN_EDGE = 640
_MAX_FRAMES = 120
_GAMMA = 2.2
_TO_LINEAR = ((np.arange(256, dtype=np.float32) / 255) ** _GAMMA).astype(np.float32)
_long_lock = threading.Lock()


def long_exposure_path(clip: Clip) -> Path:
    digest = fingerprint_digest(clip.fingerprint)
    return clip.tools.cache_dir / "renditions" / digest[:2] / f"{digest}_lx{LIVE_VERSION}.png"


def long_exposure(clip: Clip) -> Array:
    """All frames of ``clip`` aligned and averaged in linear light (full size, cached)."""
    path = long_exposure_path(clip)
    with _long_lock:  # one at a time: each takes a few seconds and a lot of memory
        if not path.exists():
            image = blend_frames(clip)
            path.parent.mkdir(parents=True, exist_ok=True)
            pixels = (np.clip(image, 0, 1) * 65535 + 0.5).astype(np.uint16)
            handle, temp = tempfile.mkstemp(dir=path.parent, suffix=".png")
            os.close(handle)
            try:
                if not cv2.imwrite(temp, cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)):
                    raise LiveError("cannot save the long exposure")
                os.replace(temp, path)
            finally:
                Path(temp).unlink(missing_ok=True)
            return image
    with contextlib.suppress(OSError):
        os.utime(path)  # recently used (cache pruning)
    stored = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if stored is None:
        path.unlink(missing_ok=True)
        return long_exposure(clip)
    return cv2.cvtColor(stored, cv2.COLOR_BGR2RGB).astype(np.float32) / np.float32(65535)


def blend_frames(clip: Clip) -> Array:
    """Align every frame to the one nearest the still, then average them in linear light.

    Hand shake is removed with a similarity transform per frame (tracked corners and
    RANSAC, so moving water or traffic does not pull the alignment); frames that cannot be
    aligned are left out. Every pixel is divided by the number of frames that covered it,
    so the edges show no dark border.
    """
    info = probe(clip)
    small = [_gray(f) for f in frames(clip, _ALIGN_EDGE)]
    if not small:
        raise LiveError("the clip has no frames")
    use = _subsample(len(small), _MAX_FRAMES)
    times = info.frame_times_ms
    reference = len(small) // 2
    still = info.still_ms
    if still is not None and len(times) >= len(small):
        reference = min(range(len(small)), key=lambda i: abs(times[i] - still))
    identity = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
    transforms: dict[int, npt.NDArray[np.float32] | None] = {
        i: identity if i == reference else align(small[reference], small[i]) for i in use
    }
    aligned = [i for i in use if transforms[i] is not None]
    if len(aligned) < max(2, len(use) // 4):
        logger.info("long exposure: frames could not be aligned, blending as shot")
        transforms = dict.fromkeys(use, identity)
        aligned = list(use)

    scale = max(info.width, info.height) / max(small[0].shape[:2])
    total: Array | None = None
    count: Array | None = None
    wanted = set(aligned)
    for index, frame in enumerate(frames(clip)):
        if index not in wanted:
            continue
        matrix = transforms[index]
        assert matrix is not None
        matrix = matrix.copy()
        matrix[:, 2] *= scale
        height, width = frame.shape[:2]
        linear = _TO_LINEAR[frame]
        warped = _f32(cv2.warpAffine(
            linear, matrix, (width, height), flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0),
        ))  # fmt: skip
        cover = _f32(cv2.warpAffine(
            np.ones((height, width), np.float32), matrix, (width, height),
            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
        ))  # fmt: skip
        if total is None or count is None:
            total = np.zeros_like(warped)
            count = np.zeros_like(cover)
        total += warped
        count += cover
    if total is None or count is None:
        raise LiveError("the clip has no frames")
    mean = total / np.maximum(count, 1e-3)[..., None]
    return np.power(np.clip(mean, 0, 1), 1 / _GAMMA).astype(np.float32)


def _gray(frame: Frame) -> Frame:
    return np.asarray(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), dtype=np.uint8)


def _f32(values: object) -> Array:
    return np.asarray(values, dtype=np.float32)


def _subsample(count: int, limit: int) -> list[int]:
    if count <= limit:
        return list(range(count))
    return sorted({round(i * (count - 1) / (limit - 1)) for i in range(limit)})


def align(reference: Frame, moving: Frame) -> npt.NDArray[np.float32] | None:
    """The similarity transform that maps ``moving`` onto ``reference`` (2x3), or None."""
    corners = cv2.goodFeaturesToTrack(reference, maxCorners=400, qualityLevel=0.01, minDistance=8)
    if corners is None or len(corners) < 12:
        return None
    tracked, status, _ = _cv.calcOpticalFlowPyrLK(
        reference, moving, corners, None, winSize=(21, 21), maxLevel=4
    )
    if tracked is None:
        return None
    ok = status.ravel() == 1
    if ok.sum() < 12:
        return None
    matrix, inliers = cv2.estimateAffinePartial2D(
        tracked[ok], corners[ok], method=cv2.RANSAC, ransacReprojThreshold=2.0
    )
    if matrix is None or inliers is None or int(inliers.sum()) < 12:
        return None
    return np.asarray(matrix, dtype=np.float32)


# --- Motion: loop, bounce and the clip itself -------------------------------------------------

MotionEffect = Literal["live", "loop", "bounce"]
MotionFormat = Literal["mp4", "gif"]
PLAYBACK_EDGE = 1080
GIF_EDGE = 720
GIF_FPS = 15
_FADE_S = 0.5

# Display P3 to sRGB (linear light, D65).
_P3_TO_SRGB = np.array(
    [
        [1.2249, -0.2247, 0.0],
        [-0.0420, 1.0419, 0.0],
        [-0.0197, -0.0786, 1.0979],
    ],
    dtype=np.float32,
)


def motion_effect(recipe: EditRecipe) -> MotionEffect:
    """How a recipe's clip plays (a long exposure's clip plays as shot)."""
    effect = recipe.live_effect
    if effect == "loop" or effect == "bounce":
        return effect
    return "live"


def motion_path(clip: Clip, recipe: EditRecipe) -> Path:
    """Where the playback clip of ``recipe``'s effect and adjustments is cached."""
    digest = fingerprint_digest(clip.fingerprint)
    adjustments = recipe.without_live().content_hash() or "0"
    name = f"{digest}_{motion_effect(recipe)}{adjustments[:8]}_m{LIVE_VERSION}.mp4"
    return clip.tools.cache_dir / "renditions" / digest[:2] / name


_motion_locks: dict[Path, threading.Lock] = {}
_motion_locks_guard = threading.Lock()


def playback(clip: Clip, recipe: EditRecipe) -> Path:
    """The cached playback clip (H.264 MP4, at most 1080 px), rendered on first use."""
    path = motion_path(clip, recipe)
    with _motion_locks_guard:
        lock = _motion_locks.setdefault(path, threading.Lock())
    with lock:
        if path.exists():
            with contextlib.suppress(OSError):
                os.utime(path)
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=path.parent, suffix=".mp4")
        os.close(handle)
        try:
            render_motion(clip, recipe, Path(temp), format="mp4", edge=PLAYBACK_EDGE, audio=False)
            os.replace(temp, path)
        finally:
            Path(temp).unlink(missing_ok=True)
    return path


def render_motion(
    clip: Clip,
    recipe: EditRecipe,
    target: Path,
    *,
    format: MotionFormat,
    edge: int | None,
    audio: bool = True,
    creation_time: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Write ``clip`` with ``recipe``'s effect and adjustments to ``target`` (overwritten).

    MP4 is H.264 with the clip's sound for the "live" effect; GIF loops forever at 15 fps.
    """
    from lumen.develop import engine  # engine imports this module

    info = probe(clip)
    effect = motion_effect(recipe)
    adjustments = recipe.without_live()
    identity = adjustments.is_identity()
    fps = info.fps

    def developed() -> Iterator[Frame]:
        for frame in frames(clip, edge):
            if should_stop is not None and should_stop():
                raise LiveStopped()
            if not identity:
                frame = to_uint8(engine.render(to_float(frame), adjustments))
            yield p3_to_srgb(frame) if info.wide_gamut else frame

    sequence = _sequence(developed(), effect, fps)
    first = next(sequence, None)
    if first is None:
        raise LiveError("the clip has no frames")
    height, width = first.shape[:2]
    even_w, even_h = width - width % 2, height - height % 2

    command = [
        clip.ffmpeg(), "-nostdin", "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
        "-framerate", f"{fps:.4f}", "-i", "-",
    ]  # fmt: skip
    with_audio = format == "mp4" and audio and effect == "live" and info.has_audio
    if with_audio:
        command += ["-i", str(clip.path), "-map", "0:v:0", "-map", "1:a:0"]
    if format == "mp4":
        command += [
            "-vf", f"crop={even_w}:{even_h}:0:0,scale=out_color_matrix=bt709:out_range=tv,"
                   "format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709"
                   ":colorspace=bt709:range=tv",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-movflags", "+faststart",
        ]  # fmt: skip
        if with_audio:
            command += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
        if creation_time:
            command += ["-metadata", f"creation_time={creation_time}"]
        command += ["-f", "mp4", str(target)]
    else:
        command += [
            "-vf", f"fps={GIF_FPS},split[a][b];[a]palettegen=stats_mode=diff[p];"
                   "[b][p]paletteuse=dither=bayer:bayer_scale=4",
            "-loop", "0", "-f", "gif", str(target),
        ]  # fmt: skip

    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=errors,
            creationflags=_NO_WINDOW,
        )
        assert process.stdin is not None
        try:
            process.stdin.write(np.ascontiguousarray(first).tobytes())
            for frame in sequence:
                process.stdin.write(np.ascontiguousarray(frame).tobytes())
            process.stdin.close()
            process.wait(timeout=_TIMEOUT)
        except BaseException:
            with contextlib.suppress(OSError):
                process.stdin.close()
            process.kill()
            process.wait()
            raise
        if process.returncode != 0:
            errors.seek(0)
            message = errors.read().decode("utf-8", errors="replace").strip()[:300]
            raise LiveError(f"ffmpeg could not write the clip: {message}")


def _sequence(source: Iterator[Frame], effect: MotionEffect, fps: float) -> Iterator[Frame]:
    """The frames to write for ``effect``.

    loop: the clip without its first ``fade`` frames, its last ``fade`` frames dissolving
    into them, so the end flows into the start; bounce: forwards, then backwards.
    """
    if effect == "live":
        yield from source
        return
    if effect == "bounce":
        kept = list(source)
        yield from kept
        yield from reversed(kept[1:-1])
        return
    fade = max(1, round(_FADE_S * fps))
    head: list[Frame] = []
    tail: list[Frame] = []
    for frame in source:
        if len(head) < fade:
            head.append(frame)
            continue
        tail.append(frame)
        if len(tail) > fade:
            yield tail.pop(0)
    if len(tail) < fade:  # too short to dissolve: plays as shot
        yield from head
        yield from tail
        return
    for k, (end, start) in enumerate(zip(tail, head, strict=True)):
        weight = (k + 1) / (fade + 1)
        yield np.asarray(cv2.addWeighted(end, 1 - weight, start, weight, 0), dtype=np.uint8)


_ENCODE_STEPS = 65536
_TO_ENCODED = (
    np.power(np.arange(_ENCODE_STEPS, dtype=np.float32) / (_ENCODE_STEPS - 1), 1 / _GAMMA) * 255
    + 0.5
).astype(np.uint8)


def p3_to_srgb(frame: Frame) -> Frame:
    """Display P3 pixels as sRGB (colours outside sRGB are clipped). Table lookups keep it
    to a few milliseconds per frame."""
    linear = np.asarray(cv2.LUT(frame, _TO_LINEAR), dtype=np.float32)
    converted = np.asarray(cv2.transform(linear, _P3_TO_SRGB), dtype=np.float32)
    steps = np.clip(converted * (_ENCODE_STEPS - 1), 0, _ENCODE_STEPS - 1).astype(np.uint16)
    return np.asarray(np.take(_TO_ENCODED, steps), dtype=np.uint8)


def _run(command: list[str], *, capture: bool) -> str:
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=capture,
            timeout=_TIMEOUT,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LiveError(f"cannot run {Path(command[0]).name}: {exc}") from exc
    if completed.returncode != 0:
        message = (completed.stderr or b"").decode("utf-8", errors="replace").strip()[:300]
        raise LiveError(f"{Path(command[0]).name} failed: {message}")
    return (completed.stdout or b"").decode("utf-8", errors="replace")
