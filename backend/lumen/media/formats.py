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
    "xmp": MediaFormat("sidecar", "application/rdf+xml"),
}


def format_for(extension: str) -> MediaFormat | None:
    """Look up a format by extension (with or without the dot, any case)."""
    return FORMATS.get(extension.lower().lstrip("."))
