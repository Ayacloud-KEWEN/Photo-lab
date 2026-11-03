"""Technical metadata extraction (ExifTool for stills and videos, FFprobe for video streams).

The ``parse_*`` functions are pure and turn raw tool output into ``Metadata``.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Any

logger = logging.getLogger(__name__)

EXTRACTOR = "exiftool+ffprobe"

# Tags requested from ExifTool (output keys are "<Group0>:<Tag>" because of -G).
EXIFTOOL_TAGS = [
    "EXIF:DateTimeOriginal",
    "EXIF:OffsetTimeOriginal",
    "EXIF:CreateDate",
    "XMP:DateTimeOriginal",
    "XMP:DateCreated",
    "QuickTime:CreationDate",
    "QuickTime:CreateDate",
    "QuickTime:MediaCreateDate",
    "EXIF:Make",
    "EXIF:Model",
    "QuickTime:Make",
    "QuickTime:Model",
    "EXIF:LensModel",
    "Composite:LensID",
    "EXIF:FocalLength",
    "EXIF:FNumber",
    "EXIF:ExposureTime",
    "EXIF:ISO",
    "EXIF:Orientation",
    "Composite:ImageSize",
    "File:ImageWidth",
    "File:ImageHeight",
    "Composite:GPSLatitude",
    "Composite:GPSLongitude",
    "Composite:GPSAltitude",
    "QuickTime:Duration",
    # Apple's Live Photo pairing id: same value in the still and its motion clip.
    "MakerNotes:ContentIdentifier",
    "QuickTime:ContentIdentifier",
    # Read-only imports of other tools' work (Lightroom, Bridge, Windows Photos).
    "XMP:Rating",
    "EXIF:Rating",
    "XMP:Subject",
    "IPTC:Keywords",
]


@dataclass
class Metadata:
    width: int | None = None
    height: int | None = None
    orientation: int | None = None
    duration_ms: int | None = None
    capture_time: str | None = None  # local wall-clock time, "YYYY-MM-DDTHH:MM:SS"
    camera_make: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    focal_length_mm: float | None = None
    aperture: float | None = None
    exposure_time_s: float | None = None
    iso: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    video_codec: str | None = None
    frame_rate: float | None = None
    keywords: list[str] = field(default_factory=list)
    xmp_rating: int | None = None  # -1 = rejected, 0..5 stars
    content_identifier: str | None = None  # Live Photo pairing id (upper-case UUID)
    raw: dict[str, Any] = field(default_factory=dict)

    def raw_json(self) -> str:
        return json.dumps(self.raw, ensure_ascii=False, default=str, sort_keys=True)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------- value helpers

_DATE = re.compile(
    r"^(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$"
)


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _positive_int(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number > 0 else None


def _parse_date(value: object) -> tuple[datetime, bool] | None:
    """Parse an EXIF/QuickTime/XMP date. Returns (datetime, has_explicit_zone)."""
    text = _text(value)
    if not text or text.startswith("0000"):
        return None
    match = _DATE.match(text)
    if not match:
        return None
    year, month, day, hour, minute, second, zone = match.groups()
    try:
        moment = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))
    except ValueError:
        return None
    if moment.year < 1900:
        return None
    if zone:
        if zone == "Z":
            return moment.replace(tzinfo=UTC), True
        hours, minutes = int(zone[1:3]), int(zone[-2:])
        sign = 1 if zone[0] == "+" else -1
        offset = timezone(sign * timedelta(hours=hours, minutes=minutes))
        return moment.replace(tzinfo=offset), True
    return moment, False


def _wall_clock(moment: datetime) -> str:
    return moment.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")


def _utc_to_local_wall_clock(moment: datetime) -> str:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return _wall_clock(aware.astimezone())


def _keywords(record: Mapping[str, Any]) -> list[str]:
    seen: dict[str, str] = {}
    for key in ("XMP:Subject", "IPTC:Keywords"):
        value = record.get(key)
        values = value if isinstance(value, list) else [value] if value is not None else []
        for item in values:
            text = _text(item)
            if text and len(text) <= 100:
                seen.setdefault(text.casefold(), text)
    return list(seen.values())


def _rating(record: Mapping[str, Any]) -> int | None:
    for key in ("XMP:Rating", "EXIF:Rating"):
        value = _number(record.get(key))
        if value is not None and -1 <= value <= 5:
            return int(value)
    return None


def _capture_time(record: Mapping[str, Any]) -> str | None:
    # Wall-clock dates written by the camera, in order of reliability.
    for key in (
        "EXIF:DateTimeOriginal",
        "XMP:DateTimeOriginal",
        "QuickTime:CreationDate",  # Apple "Keys" date, includes the zone
        "XMP:DateCreated",
        "EXIF:CreateDate",
    ):
        parsed = _parse_date(record.get(key))
        if parsed:
            return _wall_clock(parsed[0])
    # QuickTime CreateDate/MediaCreateDate are UTC by specification.
    for key in ("QuickTime:CreateDate", "QuickTime:MediaCreateDate"):
        parsed = _parse_date(record.get(key))
        if parsed:
            return _utc_to_local_wall_clock(parsed[0])
    return None


def _dimensions(record: Mapping[str, Any]) -> tuple[int | None, int | None]:
    size = _text(record.get("Composite:ImageSize"))
    if size:
        match = re.match(r"^(\d+)\D+(\d+)$", size)
        if match:
            return int(match.group(1)), int(match.group(2))
    return _positive_int(record.get("File:ImageWidth")), _positive_int(
        record.get("File:ImageHeight")
    )


# ---------------------------------------------------------------- parsers


def parse_exiftool(record: Mapping[str, Any]) -> Metadata:
    """Normalize one ExifTool JSON record (run with ``-G -n``)."""
    width, height = _dimensions(record)
    orientation = _positive_int(record.get("EXIF:Orientation"))
    if orientation is not None and not 1 <= orientation <= 8:
        orientation = None
    if orientation in (5, 6, 7, 8) and width and height:
        width, height = height, width  # store displayed dimensions

    latitude = _number(record.get("Composite:GPSLatitude"))
    longitude = _number(record.get("Composite:GPSLongitude"))
    if (
        latitude is None
        or longitude is None
        or not (-90 <= latitude <= 90 and -180 <= longitude <= 180)
        or (latitude == 0 and longitude == 0)
    ):
        latitude = longitude = None

    duration = _number(record.get("QuickTime:Duration"))
    lens = _text(record.get("Composite:LensID")) or _text(record.get("EXIF:LensModel"))
    if lens and lens.lower() in {"unknown", "0", "n/a"}:
        lens = None
    iso = _number(record.get("EXIF:ISO"))
    content_identifier = _text(record.get("MakerNotes:ContentIdentifier")) or _text(
        record.get("QuickTime:ContentIdentifier")
    )

    return Metadata(
        width=width,
        height=height,
        orientation=orientation,
        duration_ms=int(duration * 1000) if duration and duration > 0 else None,
        capture_time=_capture_time(record),
        camera_make=_text(record.get("EXIF:Make")) or _text(record.get("QuickTime:Make")),
        camera_model=_text(record.get("EXIF:Model")) or _text(record.get("QuickTime:Model")),
        lens_model=lens,
        focal_length_mm=_number(record.get("EXIF:FocalLength")) or None,
        aperture=_number(record.get("EXIF:FNumber")) or None,
        exposure_time_s=_number(record.get("EXIF:ExposureTime")) or None,
        iso=int(iso) if iso and iso > 0 else None,
        latitude=latitude,
        longitude=longitude,
        altitude_m=_number(record.get("Composite:GPSAltitude")) if latitude is not None else None,
        keywords=_keywords(record),
        xmp_rating=_rating(record),
        content_identifier=content_identifier.upper() if content_identifier else None,
        raw={k: v for k, v in record.items() if k != "SourceFile"},
    )


def _frame_rate(value: object) -> float | None:
    text = _text(value)
    if not text:
        return None
    if "/" in text:
        numerator, _, denominator = text.partition("/")
        num, den = _number(numerator), _number(denominator)
        if num and den:
            return round(num / den, 3)
        return None
    rate = _number(text)
    return rate if rate and rate > 0 else None


def parse_ffprobe(data: Mapping[str, Any]) -> Metadata:
    """Normalize ``ffprobe -show_format -show_streams -of json`` output."""
    streams: Sequence[Mapping[str, Any]] = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    fmt: Mapping[str, Any] = data.get("format") or {}

    metadata = Metadata()
    duration = _number(fmt.get("duration"))
    if duration and duration > 0:
        metadata.duration_ms = int(duration * 1000)
    if video:
        width, height = _positive_int(video.get("width")), _positive_int(video.get("height"))
        rotation = 0.0
        for side_data in video.get("side_data_list") or []:
            rotation = _number(side_data.get("rotation")) or rotation
        rotation = _number((video.get("tags") or {}).get("rotate")) or rotation
        if int(abs(rotation)) % 180 == 90 and width and height:
            width, height = height, width
        metadata.width, metadata.height = width, height
        metadata.video_codec = _text(video.get("codec_name"))
        metadata.frame_rate = _frame_rate(video.get("avg_frame_rate")) or _frame_rate(
            video.get("r_frame_rate")
        )
    created = _parse_date((fmt.get("tags") or {}).get("creation_time"))
    if created:
        metadata.capture_time = _utc_to_local_wall_clock(created[0])
    return metadata


def merge_video(exif: Metadata, probe: Metadata) -> Metadata:
    """ExifTool knows dates, GPS and camera; FFprobe knows the actual stream."""
    exif.width = probe.width or exif.width
    exif.height = probe.height or exif.height
    exif.duration_ms = probe.duration_ms or exif.duration_ms
    exif.video_codec = probe.video_codec
    exif.frame_rate = probe.frame_rate
    exif.capture_time = exif.capture_time or probe.capture_time
    return exif


# ---------------------------------------------------------------- tool runners


class ExifToolSession:
    """A persistent ``exiftool -stay_open`` process for batch extraction."""

    def __init__(self, executable: str) -> None:
        import exiftool

        self._helper = exiftool.ExifToolHelper(
            executable=executable,
            common_args=["-G", "-n", "-charset", "filename=utf8"],
            # Corrupt files still yield a record (with an error tag); do not fail the batch.
            check_execute=False,
            encoding="utf-8",
        )
        self.version = "unknown"

    def __enter__(self) -> ExifToolSession:
        self._helper.run()
        self.version = str(self._helper.version)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._helper.terminate()

    def copy_metadata(
        self, source: Path, target: Path, *, width: int, height: int, include_location: bool
    ) -> None:
        """Copy ``source``'s metadata into ``target`` (an exported JPEG, never an original).

        The pixels were developed (oriented, possibly cropped), so orientation, size and the
        embedded thumbnails are corrected; GPS is removed unless ``include_location``.
        The ICC profile is left as written with the pixels.
        """
        args = [
            "-TagsFromFile", str(source), "-all:all", "--ICC_Profile:all",
            "-ThumbnailImage=", "-PreviewImage=", "-Orientation=1",
            f"-ExifImageWidth={width}", f"-ExifImageHeight={height}",
        ]  # fmt: skip
        if not include_location:
            args += ["-GPS:all=", "-XMP:GPS*=", "-XMP-exif:GPS*="]
        self._helper.execute(*args, "-overwrite_original", str(target))

    def read(self, paths: Iterable[Path]) -> dict[str, dict[str, Any] | Exception]:
        """Read tags for many files; returns results keyed by ``str(path)``."""
        files = [str(p) for p in paths]
        if not files:
            return {}
        try:
            records = self._helper.get_tags(files, EXIFTOOL_TAGS)
            if len(records) == len(files):
                return dict(zip(files, records, strict=True))
        except Exception as exc:
            logger.warning("exiftool batch failed, retrying per file", extra={"error": str(exc)})
        results: dict[str, dict[str, Any] | Exception] = {}
        for file in files:
            try:
                [record] = self._helper.get_tags([file], EXIFTOOL_TAGS)
                results[file] = record
            except Exception as exc:
                results[file] = exc
        return results


def run_ffprobe(ffprobe: str, path: Path, timeout: float = 60) -> dict[str, Any]:
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-of", "json", "-show_format", "-show_streams", str(path)],
        stdin=subprocess.DEVNULL,  # never inherit the backend's stdin (see thumbnails)
        capture_output=True,
        timeout=timeout,
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    result: dict[str, Any] = json.loads(completed.stdout.decode("utf-8", errors="replace"))
    return result
