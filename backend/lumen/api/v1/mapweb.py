from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, Response

from lumen.api.deps import Connection, wake_task_runner
from lumen.core.errors import NotFoundError
from lumen.core.reveal import open_in_browser
from lumen.schemas.common import ErrorResponse
from lumen.schemas.mapweb import (
    FootprintPhotos,
    LayerFootprint,
    LayerPlan,
    LayerPlanSummary,
    LayerTrack,
    MapWebAssets,
    MapWebPlan,
    MapWebPlanRequest,
    MapWebSendRequest,
    MapWebStatus,
    MapWebSync,
    MapWebTestRequest,
)
from lumen.schemas.tasks import Task
from lumen.services import mapweb as service
from lumen.services import mapweb_layers as layers
from lumen.services import mapweb_sync as sync_service
from lumen.services import tasks as tasks_service
from lumen.services.settings import get_settings
from lumen.tasks import queue

router = APIRouter(prefix="/mapweb", tags=["mapweb"])

ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse}, 502: {"model": ErrorResponse},
}  # fmt: skip


@router.post(
    "/test", response_model=MapWebStatus, operation_id="testMapWeb", responses=ERRORS
)
def test_mapweb(body: MapWebTestRequest) -> MapWebStatus:
    """Check that an address answers like MapWeb (before saving it)."""
    return service.test_connection(body.url)


@router.post(
    "/plan", response_model=MapWebPlan, operation_id="planMapWebSend", responses=ERRORS
)
def plan_send(conn: Connection, body: MapWebPlanRequest) -> MapWebPlan:
    """Where these photos would go on the map: existing footprints, new ones, skipped."""
    return service.plan_summary(conn, body.asset_ids, body.language)


@router.post(
    "/send", response_model=Task, status_code=202, operation_id="sendToMapWeb",
    responses=ERRORS,
)  # fmt: skip
def send(conn: Connection, request: Request, body: MapWebSendRequest) -> Task:
    """Send the photos to MapWeb as planned (a background task)."""
    task_id = service.start_send(conn, body, queue.enqueue)
    wake_task_runner(request)
    return tasks_service.get_task(conn, task_id)


@router.get("/sync", response_model=MapWebSync, operation_id="mapWebSyncStatus")
def sync_status(conn: Connection) -> MapWebSync:
    """Photos on the map and edited since sent; what this MapWeb supports."""
    return sync_service.status(conn)


@router.post(
    "/sync", response_model=Task, status_code=202, operation_id="syncMapWeb", responses=ERRORS
)
def sync(conn: Connection, request: Request) -> Task:
    """Ask MapWeb which photos of the library it has (a task)."""
    task_id = sync_service.start_sync(conn)
    wake_task_runner(request)
    return tasks_service.get_task(conn, task_id)


@router.post(
    "/update", response_model=Task, status_code=202, operation_id="updateOnMapWeb",
    responses=ERRORS,
)  # fmt: skip
def update(conn: Connection, request: Request, body: MapWebAssets) -> Task:
    """Replace on the map the photos edited since they were sent (a task)."""
    task_id = sync_service.start_update(conn, body.asset_ids)
    wake_task_runner(request)
    return tasks_service.get_task(conn, task_id)


@router.post(
    "/open-point/{point_id}", status_code=204, operation_id="openFootprint", responses=ERRORS
)
def open_footprint(conn: Connection, point_id: int) -> None:
    """Open a footprint in MapWeb, in the browser."""
    url = get_settings(conn).mapweb_url
    if not url:
        raise NotFoundError("Set MapWeb's address in Settings first")
    open_in_browser(f"{url.rstrip('/')}/?point={int(point_id)}", allow_http=True)


@router.post("/open/{asset_id}", status_code=204, operation_id="openOnMapWeb", responses=ERRORS)
def open_on_map(conn: Connection, asset_id: int) -> None:
    """Open the photo's footprint in MapWeb, in the browser."""
    row = conn.execute(
        "SELECT point_id FROM mapweb_photos WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    url = get_settings(conn).mapweb_url
    if row is None or not url:
        raise NotFoundError("This photo is not on the map", details={"id": asset_id})
    open_in_browser(f"{url.rstrip('/')}/?point={int(row[0])}", allow_http=True)


# --- Layers on LUMEN's map ------------------------------------------------------------------


@router.get(
    "/layers/footprints", response_model=list[LayerFootprint], operation_id="mapWebFootprints",
    responses=ERRORS,
)  # fmt: skip
def footprints(conn: Connection) -> list[LayerFootprint]:
    """MapWeb's footprints (kept a couple of minutes)."""
    return layers.footprints(conn)


@router.get(
    "/layers/footprints/{point_id}/photos", response_model=FootprintPhotos,
    operation_id="mapWebFootprintPhotos", responses=ERRORS,
)  # fmt: skip
def footprint_photos(
    conn: Connection, point_id: int, language: str = Query(default="zh-CN", max_length=10)
) -> FootprintPhotos:
    """The library's photos MapWeb's import would put on this footprint."""
    return layers.footprint_photos(conn, point_id, language)


@router.get(
    "/layers/tracks", response_model=list[LayerTrack], operation_id="mapWebTracks",
    responses=ERRORS,
)  # fmt: skip
def tracks(conn: Connection) -> list[LayerTrack]:
    return layers.tracks(conn)


@router.get(
    "/layers/plans", response_model=list[LayerPlanSummary], operation_id="mapWebPlans",
    responses=ERRORS,
)  # fmt: skip
def plans(conn: Connection) -> list[LayerPlanSummary]:
    return layers.plans(conn)


@router.get(
    "/layers/plans/{plan_id}", response_model=LayerPlan, operation_id="mapWebPlan",
    responses=ERRORS,
)  # fmt: skip
def plan(conn: Connection, plan_id: int) -> LayerPlan:
    """A plan's days and stops, each stop with the photos taken there that day."""
    return layers.plan(conn, plan_id)


@router.get("/layers/thumb", operation_id="mapWebThumb", responses=ERRORS)
def thumb(conn: Connection, path: str = Query(max_length=300)) -> Response:
    """A footprint's thumbnail, from MapWeb. Accepts ``?token=`` (for ``<img>``)."""
    data, kind = layers.thumbnail(conn, path)
    return Response(data, media_type=kind, headers={"Cache-Control": "private, max-age=600"})
