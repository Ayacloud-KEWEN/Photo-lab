"""Read-only directory traversal."""

from __future__ import annotations

import logging
import os
import stat
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from lumen.media.formats import MediaFormat, format_for

logger = logging.getLogger(__name__)

# Directory names never descended into (system folders, NAS metadata, trash).
SKIPPED_DIRECTORIES = {
    "system volume information",
    "$recycle.bin",
    "@eadir",
    "__macosx",
    "#recycle",
    ".trash",
    ".trashes",
    ".spotlight-v100",
    ".fseventsd",
}

_HIDDEN_OR_SYSTEM = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2) | getattr(
    stat, "FILE_ATTRIBUTE_SYSTEM", 4
)


@dataclass(frozen=True)
class FoundFile:
    relative_path: str
    file_name: str
    extension: str
    size: int
    mtime_ns: int
    format: MediaFormat


def _is_hidden(entry: os.DirEntry[str]) -> bool:
    if entry.name.startswith((".", "$", "~$")):
        return True
    try:
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & _HIDDEN_OR_SYSTEM)


def walk_media(root: Path, should_stop: Callable[[], bool] = lambda: False) -> Iterator[FoundFile]:
    """Yield supported media files below ``root``.

    Symlinks and junctions are not followed (avoids loops and escaping the root);
    hidden/system entries and known system folders are skipped; unreadable
    directories are logged and skipped.
    """
    stack = [root]
    while stack:
        if should_stop():
            return
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                children = sorted(entries, key=lambda e: e.name)
        except OSError as exc:
            logger.warning(
                "cannot read directory", extra={"path": str(directory), "error": str(exc)}
            )
            continue

        subdirectories: list[Path] = []
        for entry in children:
            if _is_hidden(entry):
                continue
            try:
                if entry.is_symlink() or entry.is_junction():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.lower() not in SKIPPED_DIRECTORIES:
                        subdirectories.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                extension = os.path.splitext(entry.name)[1].lower().lstrip(".")
                media_format = format_for(extension)
                if media_format is None:
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                logger.warning("cannot stat file", extra={"path": entry.path, "error": str(exc)})
                continue
            yield FoundFile(
                relative_path=os.path.relpath(entry.path, root),
                file_name=entry.name,
                extension=extension,
                size=info.st_size,
                mtime_ns=info.st_mtime_ns,
                format=media_format,
            )
        # Depth-first, in name order.
        stack.extend(reversed(subdirectories))
