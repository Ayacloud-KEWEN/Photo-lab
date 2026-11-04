"""Backend entry point: ``python -m lumen``.

Startup handshake (see docs/ARCHITECTURE.md, ADR-001): once the server accepts
connections, a single JSON line is written to stdout::

    {"event": "ready", "port": 52341, "pid": 1234}

If startup fails, ``{"event": "failed", "message": "..."}`` is written instead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import threading
from typing import Any

import uvicorn

from lumen.app import create_app
from lumen.core.config import Settings
from lumen.core.logging import configure_logging
from lumen.core.security import generate_token

logger = logging.getLogger("lumen")


def _emit(event: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def _watch_stdin(server: uvicorn.Server) -> None:
    """Shut down when the parent closes our stdin (normal exit or crash of the shell)."""
    try:
        while sys.stdin.buffer.read(4096):
            pass
    except (OSError, ValueError):
        pass
    logger.info("stdin closed, shutting down")
    server.should_exit = True


def _quiet_connection_resets(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """Drop the error Windows' event loop logs when a client resets a connection (the
    webview does so whenever it cancels an image request); report everything else."""
    if isinstance(context.get("exception"), ConnectionResetError):
        return
    loop.default_exception_handler(context)


async def _serve(server: uvicorn.Server, sock: socket.socket, generated_token: str | None) -> bool:
    asyncio.get_running_loop().set_exception_handler(_quiet_connection_resets)
    serve_task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started and not serve_task.done():
        await asyncio.sleep(0.02)
    if server.started:
        event: dict[str, Any] = {
            "event": "ready",
            "port": sock.getsockname()[1],
            "pid": os.getpid(),
        }
        if generated_token:
            event["token"] = generated_token
        _emit(event)
    await serve_task
    return server.started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lumen-backend")
    parser.add_argument(
        "--watch-stdin",
        action="store_true",
        help="exit when stdin is closed (used by the desktop shell)",
    )
    args = parser.parse_args(argv)

    try:
        settings = Settings()
    except Exception as exc:
        _emit({"event": "failed", "message": f"Invalid configuration: {exc}"})
        return 2

    configure_logging(settings.log_level, settings.log_dir if settings.log_to_file else None)

    # Running standalone (no shell-provided token): generate one and print it in the handshake.
    generated_token = None if settings.token else generate_token()
    token = settings.token.get_secret_value() if settings.token else str(generated_token)

    app = create_app(settings, token)
    family = socket.AF_INET6 if ":" in settings.host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.bind((settings.host, settings.port))

    config = uvicorn.Config(app, log_config=None, lifespan="on", access_log=False)
    server = uvicorn.Server(config)
    if args.watch_stdin:
        threading.Thread(target=_watch_stdin, args=(server,), daemon=True).start()

    try:
        started = asyncio.run(_serve(server, sock, generated_token))
    finally:
        sock.close()

    if not started:
        message = getattr(app.state, "startup_error", None) or "Backend failed to start"
        _emit({"event": "failed", "message": message})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
