"""Content fingerprints used for change, move and duplicate detection."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import xxhash

ALGORITHM = "xxh128"
_CHUNK = 4 * 1024 * 1024


class FingerprintCancelled(Exception):
    pass


def fingerprint_file(path: Path, should_stop: Callable[[], bool] = lambda: False) -> str:
    """Hash the whole file (read-only). Returns ``'xxh128:<32 hex>'``."""
    digest = xxhash.xxh3_128()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
            if should_stop():
                raise FingerprintCancelled(str(path))
    return f"{ALGORITHM}:{digest.hexdigest()}"


def fingerprint_digest(fingerprint: str) -> str:
    """The hex part of a fingerprint, used for cache file names."""
    return fingerprint.split(":", 1)[-1]
