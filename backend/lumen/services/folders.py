"""Folders the user picked to write new files into (exports)."""

from __future__ import annotations

import os
from pathlib import Path

from lumen.core.errors import InvalidPathError


def check_folder(destination: str) -> Path:
    """An existing, writable folder given as a full path; returns it resolved."""
    path = Path(destination)
    if not path.is_absolute():
        raise InvalidPathError("Choose a full folder path", details={"path": destination})
    if not path.is_dir():
        raise InvalidPathError("The folder does not exist", details={"path": destination})
    if not os.access(path, os.W_OK):
        raise InvalidPathError("The folder is not writable", details={"path": destination})
    return path.resolve()
