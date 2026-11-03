from __future__ import annotations

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from lumen.api.deps import Connection
from lumen.core.config import Settings
from lumen.schemas.assets import AssetDetail, AssetPage, DuplicateReport, RenditionVariant
from lumen.schemas.common import ErrorResponse
from lumen.services import assets as service

router = APIRouter(tags=["assets"])


@router.get("/assets", response_model=AssetPage, operation_id="listAssets")
def list_assets(
    conn: Connection,
    storage_root_id: int | None = Query(default=None, ge=1),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=200, ge=1, le=1000),
) -> AssetPage:
    return service.list_assets(conn, storage_root_id=storage_root_id, cursor=cursor, limit=limit)


@router.get(
    "/assets/{asset_id}", response_model=AssetDetail, operation_id="getAsset",
    responses={404: {"model": ErrorResponse}},
)  # fmt: skip
def get_asset(conn: Connection, asset_id: int = Path(ge=1)) -> AssetDetail:
    return service.get_asset(conn, asset_id)


@router.get(
    "/assets/{asset_id}/thumbnail",
    operation_id="getAssetThumbnail",
    response_class=FileResponse,
    responses={
        200: {"content": {"image/jpeg": {}}},
        404: {"model": ErrorResponse},
    },
)
async def get_asset_thumbnail(
    conn: Connection,
    request: Request,
    asset_id: int = Path(ge=1),
    variant: RenditionVariant = Query(default="thumb"),
) -> FileResponse:
    """JPEG thumbnail (400px) or preview (2048px). Accepts ``?token=`` for use in ``<img>``."""
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


@router.get("/duplicates", response_model=DuplicateReport, operation_id="listDuplicates")
def list_duplicates(
    conn: Connection, limit: int = Query(default=100, ge=1, le=1000)
) -> DuplicateReport:
    """Groups of files with identical content. Reported only; nothing is merged or deleted."""
    return service.find_duplicates(conn, limit=limit)
