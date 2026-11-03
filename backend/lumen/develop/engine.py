"""The develop renderer: decode an original once, then apply recipes to it quickly.

Images are float32 RGB arrays in [0, 1], in sRGB (gamma-encoded) space. Light-like
adjustments (exposure, white balance) are gains; with a 2.2 power curve a linear-light
gain ``g`` is exactly a gain of ``g ** (1 / 2.2)`` on encoded values, so no conversion
to linear light is needed. Local adjustments (shadows, highlights, clarity) use a blurred
luminance computed at reduced size, which keeps a render to roughly 100 ms at 1600 px.
"""

from __future__ import annotations

import functools
import math
import threading
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
from PIL import Image

from lumen.develop.recipe import EditRecipe
from lumen.media import thumbnails
from lumen.media.formats import MediaFormat

# Bump when rendering changes, so cached edited renditions are recreated.
DEVELOP_VERSION = 1

Array = npt.NDArray[np.float32]

_GAMMA = 1 / 2.2
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


class DevelopError(Exception):
    pass


# --- Decoding -------------------------------------------------------------------------------

_CACHE_SIZE = 6
_cache: OrderedDict[tuple[str, int, int, int | None], Array] = OrderedDict()
_cache_lock = threading.Lock()


def load_base(source: Path, media_format: MediaFormat, edge: int | None) -> Array:
    """The oriented original, at most ``edge`` px on its long side (``None``: full size).

    Recently used bases stay in memory, so moving a slider never decodes the file again.
    The result is shared: callers must not modify it.
    """
    try:
        stat = source.stat()
    except OSError as exc:
        raise DevelopError(f"cannot read original: {exc}") from exc
    key = (str(source), stat.st_mtime_ns, stat.st_size, edge)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    base = _decode(source, media_format, edge)
    if edge is not None and max(base.shape[:2]) > edge:
        base = _resize(base, edge)
    base.setflags(write=False)
    with _cache_lock:
        _cache[key] = base
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return base


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _decode(source: Path, media_format: MediaFormat, edge: int | None) -> Array:
    if media_format.kind == "raw":
        return _decode_raw(source, edge)
    if media_format.kind in ("jpeg", "heic", "png", "tiff"):
        try:
            image = thumbnails.decode_still(source, edge)
        except thumbnails.RenderError as exc:
            raise DevelopError(str(exc)) from exc
        return np.asarray(image, dtype=np.float32) / np.float32(255)
    raise DevelopError(f"cannot develop {media_format.kind} files")


def _decode_raw(source: Path, edge: int | None) -> Array:
    """Demosaic with the camera's white balance (LibRaw applies the orientation)."""
    import rawpy

    try:
        with rawpy.imread(str(source)) as raw:
            long_side = max(raw.sizes.width, raw.sizes.height)
            half = edge is not None and long_side // 2 >= edge
            rgb = raw.postprocess(use_camera_wb=True, half_size=half, output_bps=16)
    except (rawpy.LibRawError, OSError, ValueError) as exc:
        raise DevelopError(f"cannot decode RAW file: {exc}") from exc
    return rgb.astype(np.float32) / np.float32(65535)


def _resize(image: Array, edge: int) -> Array:
    height, width = image.shape[:2]
    scale = edge / max(height, width)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return _f32(cv2.resize(image, size, interpolation=cv2.INTER_AREA))


def _f32(values: object) -> Array:
    """Typed view of an OpenCV result (already float32: no copy)."""
    return np.asarray(values, dtype=np.float32)


# --- Rendering ------------------------------------------------------------------------------


def render(base: Array, recipe: EditRecipe) -> Array:
    """Apply ``recipe`` to ``base`` (not modified); returns a new array in [0, 1]."""
    image = _geometry(base, recipe)
    image = _tone(image, recipe)
    image = _color(image, recipe)
    image = _detail(image, recipe)
    image = _vignette(image, recipe.vignette / 100)
    np.clip(image, 0, 1, out=image)
    return image


def to_image(image: Array) -> Image.Image:
    return Image.fromarray((image * 255 + 0.5).astype(np.uint8), "RGB")


HISTOGRAM_BINS = 64


def histogram(image: Image.Image) -> list[list[int]]:
    """Pixel counts per channel (R, G, B) in ``HISTOGRAM_BINS`` equal bins."""
    pixels = np.asarray(image)
    return [
        [
            int(count)
            for count in cv2.calcHist([pixels], [channel], None, [HISTOGRAM_BINS], [0, 256]).ravel()
        ]
        for channel in range(3)
    ]


def develop(
    source: Path, media_format: MediaFormat, recipe: EditRecipe, edge: int | None
) -> Image.Image:
    return to_image(render(load_base(source, media_format, edge), recipe))


def _geometry(image: Array, recipe: EditRecipe) -> Array:
    if recipe.rotate:
        image = np.rot90(image, k=-recipe.rotate)
    if recipe.flip_horizontal:
        image = image[:, ::-1]
    if recipe.straighten:
        image = _straighten(np.ascontiguousarray(image), recipe.straighten)
    if recipe.crop is not None:
        height, width = image.shape[:2]
        crop = recipe.crop
        left, top = round(crop.x * width), round(crop.y * height)
        right = max(left + 1, min(width, round((crop.x + crop.width) * width)))
        bottom = max(top + 1, min(height, round((crop.y + crop.height) * height)))
        image = image[top:bottom, left:right]
    # Always a fresh array: later steps work in place.
    return np.array(image, dtype=np.float32, copy=True, order="C")


def straighten_scale(width: int, height: int, degrees: float) -> float:
    """Zoom needed after rotating by ``degrees`` so that no empty corners show."""
    angle = math.radians(abs(degrees))
    cos, sin = math.cos(angle), math.sin(angle)
    return max((width * cos + height * sin) / width, (width * sin + height * cos) / height)


def _straighten(image: Array, degrees: float) -> Array:
    height, width = image.shape[:2]
    scale = straighten_scale(width, height, degrees)
    # OpenCV's positive angle is counter-clockwise; the recipe's is clockwise.
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), -degrees, scale)
    return _f32(
        cv2.warpAffine(
            image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT
        )
    )


def _luminance(image: Array) -> Array:
    return _f32(cv2.transform(image, _LUMA.reshape(1, 3)))


def _per_pixel(values: Array) -> Array:
    """A single-channel array repeated across RGB (much faster than broadcasting)."""
    return _f32(cv2.merge([values, values, values]))


def _smooth(values: Array, radius_fraction: float) -> Array:
    """A wide Gaussian blur, computed at reduced size (fast at any radius)."""
    height, width = values.shape[:2]
    factor = max(1, min(height, width) // 128)
    small = cv2.resize(
        values, (max(1, width // factor), max(1, height // factor)), interpolation=cv2.INTER_AREA
    )
    sigma = max(0.5, radius_fraction * max(height, width) / factor)
    blurred = cv2.GaussianBlur(small, (0, 0), sigma)
    return _f32(cv2.resize(blurred, (width, height), interpolation=cv2.INTER_LINEAR))


def _white_balance(temperature: float, tint: float) -> Array:
    """Per-channel linear-light gains, normalised to keep luminance unchanged."""
    gains = np.array(
        [2 ** (0.35 * temperature), 2 ** (-0.3 * tint), 2 ** (-0.35 * temperature)],
        dtype=np.float32,
    )
    normalised: Array = gains / float(gains @ _LUMA)
    return normalised


def _tone(image: Array, recipe: EditRecipe) -> Array:
    # Exposure, white balance and levels are one affine step per channel.
    gains = _white_balance(recipe.temperature / 100, recipe.tint / 100) * np.float32(
        2**recipe.exposure
    )
    black = -0.12 * recipe.blacks / 100  # below 0 lifts the blacks
    white = 1 - 0.25 * recipe.whites / 100  # below 1 brightens the whites
    scale = (gains**_GAMMA) / np.float32(white - black)
    if not np.allclose(scale, 1) or black:
        image *= scale
        image -= np.float32(black / (white - black))

    if recipe.shadows or recipe.highlights:
        local = _smooth(_luminance(image), 0.02)
        np.clip(local, 0, 1, out=local)
        shadow_mask = np.square(np.clip(1 - local * 2, 0, 1))
        highlight_mask = np.square(np.clip(local * 2 - 1, 0, 1))
        stops = (1.2 * recipe.shadows / 100) * shadow_mask
        stops += (1.2 * recipe.highlights / 100) * highlight_mask
        image *= _per_pixel(np.exp2(stops * _GAMMA))

    np.clip(image, 0, 1, out=image)
    if recipe.contrast:
        # Blend towards (or away from) a smoothstep S-curve pivoting at mid-grey.
        amount = np.float32(recipe.contrast / 100)
        image += amount * (image * image * (3 - 2 * image) - image)
    return image


def _color(image: Array, recipe: EditRecipe) -> Array:
    if not (recipe.saturation or recipe.vibrance):
        return image
    luma = _per_pixel(_luminance(image))
    factor = np.full(image.shape[:2], 1 + recipe.saturation / 100, dtype=np.float32)
    if recipe.vibrance:
        # Vibrance acts mostly on muted colours, sparing ones already saturated.
        saturation = cv2.cvtColor(np.clip(image, 0, 1), cv2.COLOR_RGB2HSV)[..., 1]
        factor *= 1 + (recipe.vibrance / 100) * (1 - saturation)
    image -= luma
    image *= _per_pixel(factor)
    image += luma
    return image


def _detail(image: Array, recipe: EditRecipe) -> Array:
    if recipe.clarity:
        luma = _luminance(image)
        detail = luma - _smooth(luma, 0.015)
        midtones = 1 - np.square(np.clip(luma, 0, 1) * 2 - 1)
        image += _per_pixel((0.8 * recipe.clarity / 100) * detail * midtones)
    if recipe.sharpness:
        blurred = cv2.GaussianBlur(image, (0, 0), 1.0)
        image += np.float32(1.5 * recipe.sharpness / 100) * (image - blurred)
    return image


def _vignette(image: Array, amount: float) -> Array:
    if not amount:
        return image
    image *= _per_pixel(1 + np.float32(0.8 * amount) * _vignette_ramp(*image.shape[:2]))
    return image


@functools.lru_cache(maxsize=4)
def _vignette_ramp(height: int, width: int) -> Array:
    """0 in the centre rising smoothly to 1 in the corners (cached: sliders reuse it)."""
    ys = np.linspace(-1, 1, height, dtype=np.float32)[:, None]
    xs = np.linspace(-1, 1, width, dtype=np.float32)[None, :]
    radius = np.sqrt((xs * xs + ys * ys) / 2)
    ramp = np.clip((radius - 0.35) / 0.65, 0, 1)
    smooth = _f32(ramp * ramp * (3 - 2 * ramp))
    smooth.setflags(write=False)
    return smooth
