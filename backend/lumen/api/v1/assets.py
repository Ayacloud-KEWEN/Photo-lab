from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from lumen.api.deps import Connection
from lumen.core.config import Settings
from lumen.schemas.assets import (
    AssetBatchUpdate,
    AssetDetail,
    AssetFacets,
    AssetIds,
    AssetPage,
    AssetQuery,
    AssetUpdate,
    BatchResult,
    MapPoints,
    RenditionVariant,
    Timeline,
)
from lumen.schemas.common import ErrorResponse
from lumen.services import assets as service
from lumen.services import edits

router = APIRouter(tags=["assets"])

Filters = Annotated[AssetQuery, Query()]
NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}


@router.get("/assets", response_model=AssetPage, operation_id="listAssets")
def list_assets(
    conn: Connection,
    query: Filters,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=200, ge=1, le=1000),
) -> AssetPage:
    return service.list_assets(conn, query, cursor=cursor, limit=limit)


@router.get("/assets/ids", response_model=AssetIds, operation_id="listAssetIds")
def list_asset_ids(
    conn: Connection, query: Filters, limit: int = Query(default=100_000, ge=1, le=100_000)
) -> AssetIds:
    """Every matching asset id, in display order (used for "select all")."""
    return AssetIds(ids=service.list_asset_ids(conn, query, limit=limit))


@router.get("/assets/facets", response_model=AssetFacets, operation_id="getAssetFacets")
def get_facets(conn: Connection) -> AssetFacets:
    return service.facets(conn)


@router.post("/assets/batch", response_model=BatchResult, operation_id="batchUpdateAssets")
def batch_update(conn: Connection, body: AssetBatchUpdate) -> BatchResult:
    """Apply a rating, favorite flag or tag changes to many assets at once."""
    return BatchResult(updated=edits.batch_update(conn, body))


@router.get(
    "/assets/{asset_id}", response_model=AssetDetail, operation_id="getAsset",
    responses=NOT_FOUND,
)  # fmt: skip
def get_asset(conn: Connection, asset_id: int = Path(ge=1)) -> AssetDetail:
    return service.get_asset(conn, asset_id)


@router.patch(
    "/assets/{asset_id}", response_model=AssetDetail, operation_id="updateAsset",
    responses=NOT_FOUND,
)  # fmt: skip
def update_asset(conn: Connection, body: AssetUpdate, asset_id: int = Path(ge=1)) -> AssetDetail:
    return edits.update_asset(conn, asset_id, body)


@router.get(
    "/assets/{asset_id}/thumbnail",
    operation_id="getAssetThumbnail",
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}}}, **NOT_FOUND},
)
async def get_asset_thumbnail(
    conn: Connection,
    request: Request,
    asset_id: int = Path(ge=1),
    variant: RenditionVariant = Query(default="thumb"),
) -> FileResponse:
    """JPEG thumbnail (400px), preview (2048px) or the full-size photo, each with its edit.

    Accepts ``?token=`` for use in ``<img>``. ``full`` is rendered on first use and cached;
    videos answer it with their preview.
    """
    settings: Settings = request.app.state.settings
    path = await run_in_threadpool(
        service.rendition_path, conn, settings.cache_dir, asset_id, variant,
        ffmpeg=settings.tool("ffmpeg"),
    )  # fmt: skip
    # URLs carry the content version (?v=...), so the response never goes stale.
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get(
    "/assets/{asset_id}/original",
    operation_id="getAssetOriginal",
    response_class=FileResponse,
    responses=NOT_FOUND,
)
def get_asset_original(conn: Connection, asset_id: int = Path(ge=1)) -> FileResponse:
    """The cover file itself, read-only, with HTTP Range support (video seeking).

    Accepts ``?token=`` for use in ``<video>`` / ``<img>``.
    """
    path, media_type = service.original_file(conn, asset_id)
    return FileResponse(
        path,
        media_type=media_type,
        content_disposition_type="inline",
        filename=path.name,
        headers={"Cache-Control": "private, no-cache"},
    )


@router.get(
    "/assets/{asset_id}/motion",
    operation_id="getAssetMotion",
    response_class=FileResponse,
    responses=NOT_FOUND,
)
def get_asset_motion(conn: Connection, asset_id: int = Path(ge=1)) -> FileResponse:
    """A Live Photo's motion clip, read-only, with HTTP Range support.

    Accepts ``?token=`` for use in ``<video>``.
    """
    path, media_type = service.motion_file(conn, asset_id)
    return FileResponse(
        path,
        media_type=media_type,
        content_disposition_type="inline",
        filename=path.name,
        headers={"Cache-Control": "private, no-cache"},
    )


@router.get("/timeline", response_model=Timeline, operation_id="getTimeline")
def get_timeline(
    conn: Connection,
    query: Filters,
    granularity: Literal["year", "month", "day"] = Query(default="month"),
) -> Timeline:
    """Asset counts per period, newest first."""
    return service.timeline(conn, query, granularity)


@router.get("/map/points", response_model=MapPoints, operation_id="getMapPoints")
def get_map_points(
    conn: Connection, query: Filters, limit: int = Query(default=100_000, ge=1, le=200_000)
) -> MapPoints:
    return service.map_points(conn, query, limit=limit)
