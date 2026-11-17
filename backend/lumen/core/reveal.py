"""Show a file in Windows Explorer (selected in its folder)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from lumen.core.errors import LumenError, NotFoundError


def reveal_in_explorer(path: Path) -> None:
    if not path.exists():
        raise NotFoundError("The file is not available", details={"path": str(path)})
    if sys.platform != "win32":
        raise LumenError("Showing files is only supported on Windows")
    # Never inherit the backend's stdin (see the ffmpeg note in HANDOFF.md).
    subprocess.Popen(
        ["explorer", f"/select,{path}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def open_in_browser(url: str, *, allow_http: bool = False) -> None:
    """Open an https URL built by the backend in the default browser (never one from a
    request: endpoints compose it themselves). ``allow_http``: the user's own MapWeb,
    which may be on the home network without https."""
    if not (url.startswith("https://") or (allow_http and url.startswith("http://"))):
        raise LumenError("Only https links can be opened")
    if sys.platform != "win32":
        raise LumenError("Opening links is only supported on Windows")
    os.startfile(url)  # Windows only
