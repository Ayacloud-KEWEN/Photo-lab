from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from lumen.api.deps import Connection
from lumen.develop.recipe import EditRecipe
from lumen.schemas.common import ErrorResponse
from lumen.schemas.develop import DevelopPreviewRequest, EditSelect, EditState
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
    conn: Connection, body: DevelopPreviewRequest, asset_id: int = Path(ge=1)
) -> Response:
    """JPEG of the photo developed with an unsaved recipe (for live slider feedback).

    The ``X-Histogram`` header holds its RGB histogram: three ``;``-separated lists of
    comma-separated pixel counts.
    """
    data, histogram = await run_in_threadpool(
        service.render_preview, conn, asset_id, body.recipe, body.edge
    )
    return Response(
        data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            HISTOGRAM_HEADER: ";".join(",".join(map(str, channel)) for channel in histogram),
        },
    )
