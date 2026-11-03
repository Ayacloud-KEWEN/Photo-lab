from __future__ import annotations

from fastapi import APIRouter, Path, Response, status

from lumen.api.deps import Connection
from lumen.schemas.common import ErrorResponse
from lumen.schemas.storage_roots import StorageRoot, StorageRootCreate, StorageRootList
from lumen.services import storage_roots as service

router = APIRouter(prefix="/storage-roots", tags=["storage-roots"])


@router.get("", response_model=StorageRootList, operation_id="listStorageRoots")
def list_storage_roots(conn: Connection) -> StorageRootList:
    return StorageRootList(items=service.list_storage_roots(conn))


@router.post(
    "",
    response_model=StorageRoot,
    status_code=status.HTTP_201_CREATED,
    operation_id="createStorageRoot",
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_storage_root(body: StorageRootCreate, conn: Connection) -> StorageRoot:
    return service.create_storage_root(conn, body)


@router.delete(
    "/{root_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteStorageRoot",
    responses={404: {"model": ErrorResponse}},
)
def delete_storage_root(conn: Connection, root_id: int = Path(ge=1)) -> Response:
    service.delete_storage_root(conn, root_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
