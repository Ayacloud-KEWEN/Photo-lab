"""Show a file in Windows Explorer (selected in its folder)."""

from __future__ import annotations

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
