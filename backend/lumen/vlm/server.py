"""A llama.cpp ``llama-server`` process that LUMEN starts, talks to and stops.

It listens on 127.0.0.1 only (a free port chosen at start), never inherits the
backend's stdin (see HANDOFF: ffmpeg hung on it the same way) and has no console
window. Its output goes to a log file next to the models, for diagnosing start-up.
"""

from __future__ import annotations

import contextlib
import logging
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ServerError(Exception):
    """llama-server could not be started or stopped responding."""


@dataclass(frozen=True)
class ModelFiles:
    """One model as llama-server needs it, and how to fit it on this machine."""

    name: str
    model: Path
    mmproj: Path
    # Extra llama-server arguments (GPU offload, expert offload, draft model...).
    args: tuple[str, ...] = ()
    context: int = 8192


@dataclass
class LlamaServer:
    binary: Path
    files: ModelFiles
    log_path: Path | None = None
    startup_timeout: float = 600
    port: int = 0
    _process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    _log: BinaryIO | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def command(self) -> list[str]:
        return [
            str(self.binary),
            "--model", str(self.files.model),
            "--mmproj", str(self.files.mmproj),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "--ctx-size", str(self.files.context),
            "--parallel", "1",
            "--no-webui",
            *self.files.args,
        ]  # fmt: skip

    def start(self) -> None:
        with self._lock:
            if self.running():
                return
            self.port = _free_port()
            log = (self.log_path or Path(os.devnull)).open("ab")
            self._log = log
            logger.info(
                "starting llama-server", extra={"model": self.files.name, "port": self.port}
            )
            try:
                self._process = subprocess.Popen(
                    self.command(),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=str(self.binary.parent),
                    creationflags=_NO_WINDOW,
                )
            except OSError as exc:
                log.close()
                raise ServerError(f"cannot start llama-server: {exc}") from exc
        self._wait_ready()

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if not self.running():
                code = self._process.returncode if self._process else None
                raise ServerError(f"llama-server exited while loading (code {code})")
            try:
                with urllib.request.urlopen(f"{self.url}/health", timeout=2) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError, TimeoutError):
                pass
            time.sleep(0.5)
        self.stop()
        raise ServerError("llama-server did not become ready in time")

    def stop(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            log, self._log = self._log, None
            if log is not None:
                with contextlib.suppress(OSError):
                    log.close()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
