from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from lumen.api.deps import Connection
from lumen.core.config import Settings
from lumen.develop import live
from lumen.develop.recipe import EditRecipe, VideoRecipe
from lumen.schemas.common import ErrorResponse
from lumen.schemas.develop import (
    DevelopPreviewRequest,
    EditBatch,
    EditBatchResult,
    EditSelect,
    EditState,
    FrameExport,
    FrameExportResult,
    LiveInfo,
    VideoEditState,
)
from lumen.services import develop as service

router = APIRouter(tags=["develop"])

HISTOGRAM_HEADER = "X-Histogram"

ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse, "description": "Not a photo, or its original is unavailable"},
}


@router.get(
    "/assets/{asset_id}/edit", response_model=EditState, operation_id="getEdit",
    responses=ERRORS,
)  # fmt: skip
def get_edit(conn: Connection, asset_id: int = Path(ge=1)) -> EditState:
    """The edit in effect and its history. Unedited photos have the default recipe."""
    return service.get_edit_state(conn, asset_id)


@router.put(
    "/assets/{asset_id}/edit", response_model=EditState, operation_id="saveEdit",
    responses=ERRORS,
)  # fmt: skip
def save_edit(conn: Connection, recipe: EditRecipe, asset_id: int = Path(ge=1)) -> EditState:
    """Save ``recipe`` as a new history step and put it in effect. Originals are not touched."""
    return service.save_edit(conn, asset_id, recipe)


@router.get(
    "/assets/{asset_id}/video-edit", response_model=VideoEditState, operation_id="getVideoEdit",
    responses=ERRORS,
)  # fmt: skip
def get_video_edit(conn: Connection, asset_id: int = Path(ge=1)) -> VideoEditState:
    """A video's trim, rotation and sound (defaults if unedited)."""
    return service.get_video_edit(conn, asset_id)


@router.put(
    "/assets/{asset_id}/video-edit", response_model=VideoEditState, operation_id="saveVideoEdit",
    responses=ERRORS,
)  # fmt: skip
def save_video_edit(
    conn: Connection, recipe: VideoRecipe, asset_id: int = Path(ge=1)
) -> VideoEditState:
    """Save a video's edit as a new history step. The original file is not touched."""
    return service.save_video_edit(conn, asset_id, recipe)


@router.post(
    "/assets/{asset_id}/frame-export", response_model=FrameExportResult,
    operation_id="exportVideoFrame", responses=ERRORS,
)  # fmt: skip
async def export_frame(
    conn: Connection, request: Request, body: FrameExport, asset_id: int = Path(ge=1)
) -> FrameExportResult:
    """Save one frame of a video (turned like its edit) as a new JPEG in a folder."""
    settings: Settings = request.app.state.settings
    path = await run_in_threadpool(
        service.export_frame, conn, asset_id, body, ffmpeg=settings.tool("ffmpeg")
    )
    return FrameExportResult(path=str(path))


@router.post("/edits/batch", response_model=EditBatchResult, operation_id="applyEdits")
def apply_edits(conn: Connection, body: EditBatch) -> EditBatchResult:
    """Apply some settings (pasted, or a preset) to many photos, each as a new history step."""
    return service.apply_to_many(conn, body)


@router.post(
    "/assets/{asset_id}/edit/undo", response_model=EditState, operation_id="undoEdit",
    responses=ERRORS,
)  # fmt: skip
def undo_edit(conn: Connection, asset_id: int = Path(ge=1)) -> EditState:
    return service.step_edit(conn, asset_id, -1)


@router.post(
    "/assets/{asset_id}/edit/redo", response_model=EditState, operation_id="redoEdit",
    responses=ERRORS,
)  # fmt: skip
def redo_edit(conn: Connection, asset_id: int = Path(ge=1)) -> EditState:
    return service.step_edit(conn, asset_id, 1)


@router.post(
    "/assets/{asset_id}/edit/select", response_model=EditState, operation_id="selectEdit",
    responses=ERRORS,
)  # fmt: skip
def select_edit(conn: Connection, body: EditSelect, asset_id: int = Path(ge=1)) -> EditState:
    """Return to a history step (``null``: the original) without discarding later steps."""
    return service.select_edit(conn, asset_id, body.edit_id)


@router.post(
    "/assets/{asset_id}/develop/preview",
    operation_id="renderDevelopPreview",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}, **ERRORS},
)
async def render_preview(
    conn: Connection, request: Request, body: DevelopPreviewRequest, asset_id: int = Path(ge=1)
) -> Response:
    """JPEG of the photo developed with an unsaved recipe (for live slider feedback).

    The ``X-Histogram`` header holds its RGB histogram: three ``;``-separated lists of
    comma-separated pixel counts.
    """
    settings: Settings = request.app.state.settings
    data, histogram = await run_in_threadpool(
        service.render_preview, conn, asset_id, body.recipe, body.edge, live.Tools.of(settings)
    )
    return Response(
        data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            HISTOGRAM_HEADER: ";".join(",".join(map(str, channel)) for channel in histogram),
        },
    )


@router.get(
    "/assets/{asset_id}/live", response_model=LiveInfo, operation_id="getLiveInfo",
    responses=ERRORS,
)  # fmt: skip
async def get_live_info(conn: Connection, request: Request, asset_id: int = Path(ge=1)) -> LiveInfo:
    """A Live Photo's frames: their times and sharpness, the still's position and the
    sharpest frame (for choosing the frame to show)."""
    settings: Settings = request.app.state.settings
    return await run_in_threadpool(service.live_info, conn, asset_id, live.Tools.of(settings))


@router.get(
    "/assets/{asset_id}/live/strip",
    operation_id="getLiveStrip",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}, **ERRORS},
)
async def get_live_strip(
    conn: Connection, request: Request, asset_id: int = Path(ge=1)
) -> Response:
    """JPEG of the clip's frames side by side, evenly spaced in time. Accepts ``?token=``."""
    settings: Settings = request.app.state.settings
    data = await run_in_threadpool(service.live_strip, conn, asset_id, live.Tools.of(settings))
    return Response(
        data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
    )
