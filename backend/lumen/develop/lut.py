"""3D LUTs (.cube): reading them, applying them to developed pictures (ADR-039).

A LUT in a recipe is named ``<content id>.<colour space>``: the first 16 hex digits of
the file's SHA-256, and the space the LUT expects (``rec709`` or ``p3``). The space is
part of the name so that changing it later does not change photos already edited.

Pictures are gamma-encoded RGB in [0, 1], in their own space (Display P3 for iPhones,
sRGB/Rec.709 otherwise). When the LUT expects the other space the picture is converted,
the LUT applied, and the result converted back, so the colour profile written on export
does not change. Interpolation is trilinear.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
import numpy.typing as npt

Array = npt.NDArray[np.float32]
LutSpace = Literal["rec709", "p3"]
Gamut = Literal["srgb", "p3"]
LutKind = Literal["look", "log", "transform"]

MAX_SIZE = 129
_GAMMA = np.float32(2.2)


class LutError(Exception):
    """The file is not a usable 3D LUT, or the LUT is missing."""


@dataclass(eq=False)
class Cube:
    title: str | None
    size: int
    table: Array  # (size, size, size, 3), indexed [b][g][r] like the file (red fastest)
    domain_min: tuple[float, float, float]
    domain_max: tuple[float, float, float]
    # The table on each torch device, made on first use.
    volumes: dict[str, Any] = field(default_factory=dict, repr=False)


_NUMBER = re.compile(r"^[-+.0-9]")


def parse_cube(data: bytes) -> Cube:
    """A 3D LUT in Adobe/Resolve .cube format (1D LUTs are not supported)."""
    text = data.decode("utf-8", errors="replace")
    title: str | None = None
    size: int | None = None
    lo, hi = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    values: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if _NUMBER.match(line):
            values.extend(line.split()[:3])
            continue
        key, _, rest = line.partition(" ")
        key = key.upper()
        rest = rest.strip()
        try:
            if key == "TITLE":
                title = rest.strip('"') or None
            elif key == "LUT_3D_SIZE":
                size = int(rest)
            elif key == "LUT_1D_SIZE":
                raise LutError("1D LUTs are not supported (only 3D .cube LUTs)")
            elif key == "DOMAIN_MIN":
                lo = _triple(rest)
            elif key == "DOMAIN_MAX":
                hi = _triple(rest)
            elif key == "LUT_3D_INPUT_RANGE":
                a, b = (float(v) for v in rest.split()[:2])
                lo, hi = (a, a, a), (b, b, b)
        except ValueError as exc:
            raise LutError(f"bad {key} line: {raw.strip()}") from exc
    if size is None:
        raise LutError("not a 3D LUT (no LUT_3D_SIZE)")
    if not 2 <= size <= MAX_SIZE:
        raise LutError(f"unsupported LUT size {size}")
    expected = size**3 * 3
    if len(values) != expected:
        raise LutError(f"{len(values) // 3} entries, expected {size**3}")
    try:
        table = np.array(values, dtype=np.float32).reshape(size, size, size, 3)
    except ValueError as exc:
        raise LutError("the table has values that are not numbers") from exc
    if any(h <= low for low, h in zip(lo, hi, strict=True)):
        raise LutError("DOMAIN_MAX must be above DOMAIN_MIN")
    return Cube(title, size, table, lo, hi)


def _triple(text: str) -> tuple[float, float, float]:
    a, b, c = (float(v) for v in text.split()[:3])
    return a, b, c


def content_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


# What the name says the LUT expects. LUTs for log footage (camera log curves, or
# conversions "to Rec709") give harsh results on finished photos and videos.
_LOG = re.compile(
    r"(?<![a-z])log(?![a-z])|log-?c|s-?log|sl2sg3|alog|apple ?log|f-?log|v-?log|"
    r"cinestyle|cinelike|pre-lut|\bto[ _]?rec\.?709|\bto[ _]v709|lc-709|cine\+709|slog2-709",
    re.IGNORECASE,
)
_TRANSFORM = re.compile(r"2020[ _-]?to[ _-]?(rec)?[ _-]?709", re.IGNORECASE)


def kind_of(name: str) -> LutKind:
    if _TRANSFORM.search(name):
        return "transform"
    if _LOG.search(name):
        return "log"
    return "look"


# --- Applying -------------------------------------------------------------------------------


# Pixels per torch call (bounds the memory of the sampling grid on large exports).
_TORCH_CHUNK = 4_000_000
_torch_state: tuple[Any, str] | bool | None = False  # False: not tried yet


def _torch() -> tuple[Any, str] | None:
    """torch and the device to use (the GPU when there is one), if torch is installed."""
    global _torch_state
    if _torch_state is False:
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            _torch_state = (torch, device)
        except ImportError:
            _torch_state = None
    return _torch_state  # type: ignore[return-value]


def apply_cube(image: Array, cube: Cube) -> Array:
    """``image`` (H, W, 3) through ``cube`` with trilinear interpolation.

    torch's ``grid_sample`` does it on the GPU in ~7 ms for a 1600 px preview (127 ms on
    the CPU); without torch, numpy takes ~0.6 s.
    """
    backend = _torch()
    if backend is not None:
        try:
            return _apply_torch(image, cube, *backend)
        except RuntimeError:  # e.g. the GPU is out of memory: numpy still works
            pass
    return _apply_numpy(image, cube)


def _apply_torch(image: Array, cube: Cube, torch: Any, device: str) -> Array:
    import torch.nn.functional as functional

    volume = _volume(cube, torch, device)
    lo = np.array(cube.domain_min, dtype=np.float32)
    span = np.array(cube.domain_max, dtype=np.float32) - lo
    pixels = image.reshape(-1, 3)
    out = np.empty_like(pixels)
    with torch.no_grad():
        for start in range(0, len(pixels), _TORCH_CHUNK):
            part = (pixels[start : start + _TORCH_CHUNK] - lo) / span
            grid = torch.from_numpy(np.ascontiguousarray(part)).to(device)
            grid = (grid.clamp(0, 1) * 2 - 1).reshape(1, 1, -1, 1, 3)
            sampled = functional.grid_sample(
                volume, grid, mode="bilinear", padding_mode="border", align_corners=True
            )
            out[start : start + len(part)] = sampled.reshape(3, -1).T.cpu().numpy()
    return out.reshape(image.shape)


def _apply_numpy(image: Array, cube: Cube) -> Array:
    size = cube.size
    lo = np.array(cube.domain_min, dtype=np.float32)
    span = np.array(cube.domain_max, dtype=np.float32) - lo
    pixels = image.reshape(-1, 3)
    x = np.clip((pixels - lo) / span, 0, 1) * np.float32(size - 1)
    i0 = np.minimum(x.astype(np.int32), size - 2)
    f = x - i0.astype(np.float32)
    flat = cube.table.reshape(-1, 3)
    # Flat index of the lower corner: (b * size + g) * size + r.
    base = (i0[:, 2] * size + i0[:, 1]) * size + i0[:, 0]
    fr, fg, fb = f[:, 0:1], f[:, 1:2], f[:, 2:3]
    step_r, step_g, step_b = 1, size, size * size

    def at(offset: int) -> Array:
        return np.asarray(flat[base + offset], dtype=np.float32)

    c00 = at(0) * (1 - fr) + at(step_r) * fr
    c10 = at(step_g) * (1 - fr) + at(step_g + step_r) * fr
    c01 = at(step_b) * (1 - fr) + at(step_b + step_r) * fr
    c11 = at(step_b + step_g) * (1 - fr) + at(step_b + step_g + step_r) * fr
    c0 = c00 * (1 - fg) + c10 * fg
    c1 = c01 * (1 - fg) + c11 * fg
    out = c0 * (1 - fb) + c1 * fb
    return np.asarray(out.reshape(image.shape), dtype=np.float32)


# Linear-light primaries conversions (D65).
_P3_TO_709 = np.array(
    [[1.2249, -0.2247, 0.0], [-0.0420, 1.0419, 0.0], [-0.0197, -0.0786, 1.0979]],
    dtype=np.float32,
)
_709_TO_P3 = np.linalg.inv(_P3_TO_709).astype(np.float32)


def _apply_all_torch(
    image: Array, cube: Cube, into: Array | None, strength: float, torch: Any, device: str
) -> Array:
    """``apply`` on the torch device in one go (conversions, LUT, residual, mix)."""
    import torch.nn.functional as functional

    volume = _volume(cube, torch, device)
    lo = torch.tensor(cube.domain_min, device=device)
    span = torch.tensor(cube.domain_max, device=device) - lo
    pixels = image.reshape(-1, 3)
    out = np.empty_like(pixels)

    def spow(values: Any, power: float) -> Any:
        return torch.sign(values) * values.abs().pow(power)

    def convert(values: Any, matrix: Array) -> Any:
        linear = spow(values, float(_GAMMA))
        return spow(linear @ torch.from_numpy(matrix.T.copy()).to(device), float(1 / _GAMMA))

    with torch.no_grad():
        for start in range(0, len(pixels), _TORCH_CHUNK):
            original = torch.from_numpy(np.ascontiguousarray(pixels[start : start + _TORCH_CHUNK]))
            original = original.to(device)
            work = convert(original, into) if into is not None else original
            inside = work.clamp(0, 1)
            grid = (((inside - lo) / span).clamp(0, 1) * 2 - 1).reshape(1, 1, -1, 1, 3)
            sampled = functional.grid_sample(
                volume, grid, mode="bilinear", padding_mode="border", align_corners=True
            )
            graded = sampled.reshape(3, -1).T + (work - inside)
            if into is not None:
                graded = convert(graded, np.linalg.inv(into).astype(np.float32))
            if strength < 1:
                graded = original + (graded - original) * strength
            out[start : start + len(graded)] = graded.cpu().numpy()
    return out.reshape(image.shape)


def _volume(cube: Cube, torch: Any, device: str) -> Any:
    volume = cube.volumes.get(device)
    if volume is None:
        # (1, 3, D=b, H=g, W=r): grid_sample's x, y, z are then r, g, b.
        table = np.ascontiguousarray(cube.table.transpose(3, 0, 1, 2))
        volume = torch.from_numpy(table)[None].to(device)
        cube.volumes[device] = volume
    return volume


def _spow(values: Array, power: float) -> Array:
    """Sign-preserving power (colours outside the target gamut have negative parts)."""
    return np.asarray(np.sign(values) * cv2.pow(np.abs(values), power), dtype=np.float32)


def _convert(image: Array, matrix: Array) -> Array:
    """Between P3 and Rec.709 primaries, without clipping what falls outside."""
    linear = _spow(image, float(_GAMMA))
    return _spow(np.asarray(cv2.transform(linear, matrix), dtype=np.float32), float(1 / _GAMMA))


def apply(image: Array, cube: Cube, space: LutSpace, gamut: Gamut, strength: float) -> Array:
    """``image`` (in ``gamut``) graded by ``cube`` (expecting ``space``), mixed in at
    ``strength`` (0-1).

    What lies outside the LUT's input range (a P3 colour beyond Rec.709) goes through
    unchanged, added back after the LUT: a vivid flower keeps its colour, and a LUT that
    changes nothing changes nothing.
    """
    if strength <= 0:
        return image
    p3_picture = gamut == "p3"
    p3_lut = space == "p3"
    into = (
        _P3_TO_709
        if p3_picture and not p3_lut
        else _709_TO_P3
        if p3_lut and not p3_picture
        else None
    )
    backend = _torch()
    if backend is not None:
        try:
            return _apply_all_torch(image, cube, into, strength, *backend)
        except RuntimeError:  # e.g. the GPU is out of memory: numpy still works
            pass
    work = image
    if p3_picture and not p3_lut:
        work = _convert(image, _P3_TO_709)
    elif p3_lut and not p3_picture:
        work = _convert(image, _709_TO_P3)
    inside = np.clip(work, 0, 1)
    graded = apply_cube(inside, cube) + (work - inside)
    if p3_picture and not p3_lut:
        graded = _convert(graded, _709_TO_P3)
    elif p3_lut and not p3_picture:
        graded = _convert(graded, _P3_TO_709)
    if strength >= 1:
        return graded
    return np.asarray(image + (graded - image) * np.float32(strength), dtype=np.float32)


# --- The LUT store ----------------------------------------------------------------------------

_folder: Path | None = None
_cache: OrderedDict[str, Cube] = OrderedDict()
_lock = threading.Lock()
_ID = re.compile(r"^([0-9a-f]{16})\.(rec709|p3)$")


def configure(folder: Path) -> None:
    """Where imported LUTs are kept (``<id>.cube``); set when the backend starts."""
    global _folder
    with _lock:
        _folder = folder
        _cache.clear()


def store_folder() -> Path:
    if _folder is None:
        raise LutError("the LUT folder is not configured")
    return _folder


def split_ref(ref: str) -> tuple[str, LutSpace]:
    """``<id>.<space>`` as a recipe stores it."""
    match = _ID.match(ref)
    if match is None:
        raise LutError(f"not a LUT reference: {ref}")
    return match.group(1), match.group(2)  # type: ignore[return-value]


def ref_of(lut_id: str, space: LutSpace) -> str:
    return f"{lut_id}.{space}"


def load(lut_id: str) -> Cube:
    with _lock:
        if lut_id in _cache:
            _cache.move_to_end(lut_id)
            return _cache[lut_id]
    path = store_folder() / f"{lut_id}.cube"
    try:
        cube = parse_cube(path.read_bytes())
    except OSError as exc:
        raise LutError(f"LUT {lut_id} is missing") from exc
    with _lock:
        _cache[lut_id] = cube
        while len(_cache) > 24:
            _cache.popitem(last=False)
    return cube


def grade(image: Array, ref: str, strength: float, gamut: Gamut) -> Array:
    """``image`` with the LUT a recipe refers to."""
    lut_id, space = split_ref(ref)
    return apply(image, load(lut_id), space, gamut, strength)
