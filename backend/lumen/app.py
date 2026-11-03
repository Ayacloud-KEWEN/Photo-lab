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
        logger.info(
            "backend started",
            extra={
                "version": __version__,
                "schema_version": version,
                "data_dir": str(settings.data_dir),
            },
        )
        yield
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
        expose_headers=["X-Request-Id"],
    )
    return app
