"""Supported file formats."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FormatKind = Literal["raw", "jpeg", "heic", "png", "tiff", "video", "sidecar"]
MediaType = Literal["photo", "video"]


@dataclass(frozen=True)
class MediaFormat:
    kind: FormatKind
    mime_type: str

    @property
    def media_type(self) -> MediaType | None:
        if self.kind == "sidecar":
            return None
        return "video" if self.kind == "video" else "photo"

    @property
    def is_raw(self) -> bool:
        return self.kind == "raw"


_RAW_EXTENSIONS = [
    "3fr",
    "ari",
    "arw",
    "bay",
    "cap",
    "cr2",
    "cr3",
    "crw",
    "dcr",
    "dcs",
    "dng",
    "drf",
    "eip",
    "erf",
    "fff",
    "iiq",
    "k25",
    "kdc",
    "mef",
    "mos",
    "mrw",
    "nef",
    "nrw",
    "orf",
    "ori",
    "pef",
    "raf",
    "raw",
    "rw2",
    "rwl",
    "sr2",
    "srf",
    "srw",
    "x3f",
]

FORMATS: dict[str, MediaFormat] = {
    **{ext: MediaFormat("raw", "image/x-raw") for ext in _RAW_EXTENSIONS},
    "dng": MediaFormat("raw", "image/x-adobe-dng"),
    "jpg": MediaFormat("jpeg", "image/jpeg"),
    "jpeg": MediaFormat("jpeg", "image/jpeg"),
    "jpe": MediaFormat("jpeg", "image/jpeg"),
    "heic": MediaFormat("heic", "image/heic"),
    "heif": MediaFormat("heic", "image/heif"),
    "hif": MediaFormat("heic", "image/heif"),
    "png": MediaFormat("png", "image/png"),
    "tif": MediaFormat("tiff", "image/tiff"),
    "tiff": MediaFormat("tiff", "image/tiff"),
    "mp4": MediaFormat("video", "video/mp4"),
    "m4v": MediaFormat("video", "video/x-m4v"),
    "mov": MediaFormat("video", "video/quicktime"),
    "mts": MediaFormat("video", "video/mp2t"),
    "m2ts": MediaFormat("video", "video/mp2t"),
    "avi": MediaFormat("video", "video/x-msvideo"),
    "wmv": MediaFormat("video", "video/x-ms-wmv"),
    "asf": MediaFormat("video", "video/x-ms-asf"),
    "mpg": MediaFormat("video", "video/mpeg"),
    "mpeg": MediaFormat("video", "video/mpeg"),
    "3gp": MediaFormat("video", "video/3gpp"),
    "mkv": MediaFormat("video", "video/x-matroska"),
    "webm": MediaFormat("video", "video/webm"),
    "xmp": MediaFormat("sidecar", "application/rdf+xml"),
}


# Videos the app's web view plays as they are; the others are converted to H.264 MP4 for
# playback (cached; the original is never touched).
PLAYABLE_VIDEO = frozenset({"mp4", "m4v", "mov", "webm"})


def needs_playback_copy(extension: str) -> bool:
    ext = extension.lower().lstrip(".")
    fmt = FORMATS.get(ext)
    return fmt is not None and fmt.kind == "video" and ext not in PLAYABLE_VIDEO


def format_for(extension: str) -> MediaFormat | None:
    """Look up a format by extension (with or without the dot, any case)."""
    return FORMATS.get(extension.lower().lstrip("."))
