from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Response, status
from pydantic import BaseModel, Field

from lumen.api.deps import Connection
from lumen.schemas.assets import Tag
from lumen.schemas.common import ErrorResponse
from lumen.services import assets, edits

router = APIRouter(prefix="/tags", tags=["tags"])

ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


class TagName(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.get("", response_model=list[Tag], operation_id="listTags")
def list_tags(conn: Connection) -> list[Tag]:
    return assets.list_tags(conn)


@router.post(
    "", response_model=Tag, status_code=status.HTTP_201_CREATED, operation_id="createTag",
    responses=ERRORS,
)  # fmt: skip
def create_tag(conn: Connection, body: TagName) -> Tag:
    return edits.create_tag(conn, body.name)


@router.patch("/{tag_id}", response_model=Tag, operation_id="renameTag", responses=ERRORS)
def rename_tag(conn: Connection, body: TagName, tag_id: int = Path(ge=1)) -> Tag:
    return edits.rename_tag(conn, tag_id, body.name)


@router.delete(
    "/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteTag",
    responses=ERRORS,
)  # fmt: skip
def delete_tag(conn: Connection, tag_id: int = Path(ge=1)) -> Response:
    """Delete a tag and remove it from all assets (files are not touched)."""
    edits.delete_tag(conn, tag_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
