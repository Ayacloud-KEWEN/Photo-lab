"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from lumen import __version__
from lumen.api.v1 import router as v1_router
from lumen.core.config import Settings
from lumen.core.errors import LumenError
from lumen.core.logging import request_id_var
from lumen.core.security import TokenAuthMiddleware
from lumen.db.connection import Database
from lumen.db.migrator import migrate
from lumen.geo.tasks import GEO_TASK, needs_locating
from lumen.library.drives import DriveWatcher
from lumen.library.handlers import HANDLERS
from lumen.library.live import REPAIR_TASK as LIVE_REPAIR_TASK
from lumen.library.live import needs_repair as live_pairing_outdated
from lumen.library.quality import QUALITY_TASK, needs_scoring
from lumen.services.backups import BACKUP_TASK, auto_backup_due
from lumen.services.cache import apply_configured as apply_cache_folder
from lumen.services.settings import get_settings
from lumen.tasks import queue
from lumen.tasks.runner import TaskRunner
from lumen.vlm.pipeline import VLM_TASK

logger = logging.getLogger(__name__)


def _error(status_code: int, code: str, message: str, details: object = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, logs each request and turns crashes into JSON 500s.

    Sits inside the CORS middleware so even error responses carry CORS headers.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error", extra={"path": request.url.path})
            response = _error(500, "internal_error", "Internal server error")
        finally:
            request_id_var.reset(token)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["x-request-id"] = request_id
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


def create_app(settings: Settings, token: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            settings.ensure_directories()
            db = Database(settings.database_path)
            version = migrate(db, backup_dir=settings.backup_dir)
        except Exception as exc:
            # Read by __main__ to report the failure to the desktop shell.
            app.state.startup_error = str(exc)
            logger.exception("backend startup failed")
            raise
        app.state.db = db
        app.state.started_at = time.monotonic()
        with db.session() as conn:
            apply_cache_folder(conn, settings)  # thumbnails on the drive chosen in Settings
        runner: TaskRunner | None = None
        watcher: DriveWatcher | None = None
        if settings.run_tasks:
            runner = TaskRunner(db, settings, HANDLERS)
            # External drives: offline / back online / moved to another letter.
            watcher = DriveWatcher(db, runner.wake)
            watcher.check()
            with db.session() as conn:
                # Places for assets located before this version (or new place data).
                if live_pairing_outdated(conn):  # rules widened: pair the library again
                    queue.enqueue(conn, LIVE_REPAIR_TASK)
                if needs_locating(conn):
                    queue.enqueue(conn, GEO_TASK)
                if needs_scoring(conn):
                    queue.enqueue(conn, QUALITY_TASK)
                if auto_backup_due(conn, settings):
                    queue.enqueue(conn, BACKUP_TASK)
                if get_settings(conn).vlm_enabled:  # carry on reading photos
                    queue.enqueue(conn, VLM_TASK)
            runner.start()
            watcher.start()
        app.state.task_runner = runner
        logger.info(
            "backend started",
            extra={
                "version": __version__,
                "schema_version": version,
                "data_dir": str(settings.data_dir),
                "tools": {name: settings.tool(name) for name in ("exiftool", "ffmpeg", "ffprobe")},
            },
        )
        yield
        if watcher is not None:
            watcher.stop()
        if runner is not None:
            # Running tasks are put back in the queue and resume on next start.
            await run_in_threadpool(runner.stop)
        logger.info("backend stopped")

    app = FastAPI(
        title="LUMEN Studio API",
        version=__version__,
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = settings

    @app.exception_handler(LumenError)
    async def _lumen_error(_: Request, exc: LumenError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(err.get("loc", [])), "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        return _error(422, "validation_error", "Request validation failed", {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail))

    app.include_router(v1_router)

    # Starlette runs the last added middleware first: CORS → request context → auth → routes.
    app.add_middleware(TokenAuthMiddleware, token=token)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
        expose_headers=["X-Request-Id", "X-Histogram"],
    )
    return app
