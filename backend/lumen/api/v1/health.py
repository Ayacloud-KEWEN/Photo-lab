from __future__ import annotations

from fastapi import APIRouter, Request

from lumen.api.deps import Connection
from lumen.schemas.health import HealthResponse
from lumen.services.health import check_health

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, operation_id="getHealth")
def get_health(request: Request, conn: Connection) -> HealthResponse:
    return check_health(conn, request.app.state.started_at)
