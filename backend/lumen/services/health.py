from __future__ import annotations

import logging
import sqlite3
import time

from lumen import API_VERSION, __version__
from lumen.db.migrator import current_version
from lumen.schemas.health import DatabaseHealth, HealthResponse

logger = logging.getLogger(__name__)


def check_health(conn: sqlite3.Connection, started_at: float) -> HealthResponse:
    try:
        conn.execute("SELECT 1").fetchone()
        database = DatabaseHealth(status="ok", schema_version=current_version(conn))
    except sqlite3.Error as exc:
        logger.exception("database health check failed")
        database = DatabaseHealth(status="error", schema_version=0, detail=str(exc))

    return HealthResponse(
        status="ok" if database.status == "ok" else "degraded",
        app_version=__version__,
        api_version=API_VERSION,
        uptime_seconds=round(time.monotonic() - started_at, 3),
        database=database,
    )
