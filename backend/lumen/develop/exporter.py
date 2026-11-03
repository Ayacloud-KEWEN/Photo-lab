"""Export developed photos as new JPEG files.

Exports are new files in a folder the user chose; an existing file is never replaced
(a free name such as ``IMG_0001 (2).jpg`` is used instead) and originals are only read.
"""

from __future__ import annotations

import itertools
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from lumen.develop import engine
from lumen.develop.recipe import EditRecipe
from lumen.media.formats import MediaFormat
from lumen.media.metadata import ExifToolSession


@dataclass(frozen=True)
class ExportOptions:
    long_edge: int | None = None  # None: full size
    quality: int = 90
    include_metadata: bool = True
    include_location: bool = False


def decode_edge(recipe: EditRecipe, long_edge: int | None) -> int | None:
    """How large to decode so that, after cropping, at least ``long_edge`` px remain."""
    if long_edge is None or recipe.straighten:
        return None  # straightening zooms in: decode everything
    crop = recipe.crop
    fraction = min(crop.width, crop.height) if crop is not None else 1.0
    return math.ceil(long_edge / fraction)


def reserve_path(folder: Path, stem: str, extension: str = ".jpg") -> Path:
    """Create an empty ``stem.jpg`` (or ``stem (2).jpg``, …) that did not exist before."""
    for number in itertools.count(1):
        name = f"{stem}{extension}" if number == 1 else f"{stem} ({number}){extension}"
        path = folder / name
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            continue
        return path
    raise AssertionError("unreachable")


def export_photo(
    source: Path,
    media_format: MediaFormat,
    recipe: EditRecipe,
    folder: Path,
    options: ExportOptions,
    exiftool: ExifToolSession | None,
) -> Path:
    """Develop ``source`` with ``recipe`` into a new JPEG in ``folder``; returns its path."""
    image = engine.develop(
        source, media_format, recipe, decode_edge(recipe, options.long_edge), cache=False
    )
    if options.long_edge is not None and max(image.size) > options.long_edge:
        image.thumbnail((options.long_edge, options.long_edge), Image.Resampling.LANCZOS)
    icc_profile = engine.source_icc_profile(source, media_format)

    target = reserve_path(folder, source.stem)
    handle, temp_name = tempfile.mkstemp(dir=folder, prefix=".lumen-", suffix=".jpg")
    try:
        with os.fdopen(handle, "wb") as out:
            image.save(
                out,
                "JPEG",
                quality=options.quality,
                subsampling=0 if options.quality >= 90 else 2,  # 4:4:4 for high quality
                optimize=True,
                progressive=True,
                **({"icc_profile": icc_profile} if icc_profile else {}),
            )
        if options.include_metadata and exiftool is not None:
            exiftool.copy_metadata(
                source,
                Path(temp_name),
                width=image.width,
                height=image.height,
                include_location=options.include_location,
            )
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return target
