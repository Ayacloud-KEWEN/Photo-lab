from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Request, Response, status
from starlette.concurrency import run_in_threadpool

from lumen.api.deps import Connection, wake_task_runner
from lumen.schemas.ai import AnalysisResult
from lumen.schemas.collections import (
    CollectionAssets,
    CollectionChange,
    CollectionCreate,
    CollectionDetail,
    CollectionItemUpdate,
    CollectionList,
    CollectionRoute,
    CollectionUpdate,
    StoryCloudRequest,
    StoryRequest,
    StoryStarted,
    TripSuggestions,
)
from lumen.schemas.common import ErrorResponse
from lumen.services import collections as service
from lumen.vlm import story

router = APIRouter(tags=["collections"])

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}


@router.get("/collections", response_model=CollectionList, operation_id="listCollections")
def list_collections(conn: Connection) -> CollectionList:
    """Trips (newest first), then albums by name."""
    return CollectionList(items=service.list_collections(conn))


@router.get("/collections/suggestions", response_model=TripSuggestions, operation_id="suggestTrips")
def suggest_trips(conn: Connection) -> TripSuggestions:
    """Trips found from capture times and places that no trip collection covers yet."""
    return service.suggest_trips(conn)


@router.post(
    "/collections", response_model=CollectionDetail, status_code=status.HTTP_201_CREATED,
    operation_id="createCollection",
)  # fmt: skip
def create_collection(conn: Connection, body: CollectionCreate) -> CollectionDetail:
    return service.create_collection(conn, body)


@router.get(
    "/collections/{collection_id}", response_model=CollectionDetail,
    operation_id="getCollection", responses=NOT_FOUND,
)  # fmt: skip
def get_collection(conn: Connection, collection_id: int = Path(ge=1)) -> CollectionDetail:
    return service.get_collection(conn, collection_id)


@router.get(
    "/collections/{collection_id}/route", response_model=CollectionRoute,
    operation_id="getCollectionRoute", responses=NOT_FOUND,
)  # fmt: skip
def get_route(conn: Connection, collection_id: int = Path(ge=1)) -> CollectionRoute:
    """The collection's located photos in capture order, grouped into stops (for its map)."""
    return service.collection_route(conn, collection_id)


@router.patch(
    "/collections/{collection_id}", response_model=CollectionDetail,
    operation_id="updateCollection", responses=NOT_FOUND,
)  # fmt: skip
def update_collection(
    conn: Connection, body: CollectionUpdate, collection_id: int = Path(ge=1)
) -> CollectionDetail:
    return service.update_collection(conn, collection_id, body)


@router.delete(
    "/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response, operation_id="deleteCollection", responses=NOT_FOUND,
)  # fmt: skip
def delete_collection(conn: Connection, collection_id: int = Path(ge=1)) -> Response:
    """Delete the collection only: its photos and videos stay in the library."""
    service.delete_collection(conn, collection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/collections/{collection_id}/items", response_model=CollectionChange,
    operation_id="addCollectionItems", responses=NOT_FOUND,
)  # fmt: skip
def add_items(
    conn: Connection, body: CollectionAssets, collection_id: int = Path(ge=1)
) -> CollectionChange:
    """Append assets to the end (ones already in it keep their place)."""
    return CollectionChange(changed=service.add_items(conn, collection_id, body.asset_ids))


@router.post(
    "/collections/{collection_id}/items/remove", response_model=CollectionChange,
    operation_id="removeCollectionItems", responses=NOT_FOUND,
)  # fmt: skip
def remove_items(
    conn: Connection, body: CollectionAssets, collection_id: int = Path(ge=1)
) -> CollectionChange:
    return CollectionChange(changed=service.remove_items(conn, collection_id, body.asset_ids))


@router.put(
    "/collections/{collection_id}/order", response_model=CollectionChange,
    operation_id="reorderCollection", responses=NOT_FOUND,
)  # fmt: skip
def reorder(
    conn: Connection, body: CollectionAssets, collection_id: int = Path(ge=1)
) -> CollectionChange:
    """The complete new order of the items."""
    return CollectionChange(changed=service.reorder(conn, collection_id, body.asset_ids))


@router.patch(
    "/collections/{collection_id}/items/{asset_id}", status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response, operation_id="updateCollectionItem", responses=NOT_FOUND,
)  # fmt: skip
def update_item(
    conn: Connection,
    body: CollectionItemUpdate,
    collection_id: int = Path(ge=1),
    asset_id: int = Path(ge=1),
) -> Response:
    """Set (or clear) an item's caption."""
    service.set_caption(conn, collection_id, asset_id, body.caption)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/collections/{collection_id}/story", response_model=StoryStarted,
    status_code=status.HTTP_202_ACCEPTED, operation_id="writeCollectionStory",
    responses=NOT_FOUND,
)  # fmt: skip
def write_story(
    conn: Connection, request: Request, body: StoryRequest, collection_id: int = Path(ge=1)
) -> StoryStarted:
    """Write a travel story with the local model (a task; nothing leaves this computer)."""
    task_id = story.start(
        conn, request.app.state.settings, collection_id, body.language, body.writer,
        body.notes_from,
    )  # fmt: skip
    wake_task_runner(request)
    return StoryStarted(task_id=task_id)


@router.get(
    "/collections/{collection_id}/stories", response_model=list[AnalysisResult],
    operation_id="listCollectionStories", responses=NOT_FOUND,
)  # fmt: skip
def list_stories(conn: Connection, collection_id: int = Path(ge=1)) -> list[AnalysisResult]:
    """Travel stories written for this portfolio by the local model, newest first."""
    return service.stories(conn, collection_id)


@router.post(
    "/collections/{collection_id}/stories/{analysis_id}/cloud", response_model=AnalysisResult,
    operation_id="writeCollectionStoryInCloud", responses=NOT_FOUND,
)  # fmt: skip
async def write_story_in_cloud(
    conn: Connection,
    body: StoryCloudRequest,
    collection_id: int = Path(ge=1),
    analysis_id: int = Path(ge=1),
) -> AnalysisResult:
    """Write the story with DeepSeek from the day notes the local model kept (the notes are
    the only thing sent: no photo, no coordinates). Requires ``confirmed: true``."""
    del body
    story_id = await run_in_threadpool(story.write_with_cloud, conn, collection_id, analysis_id)
    return next(s for s in service.stories(conn, collection_id) if s.id == story_id)
