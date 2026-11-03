from __future__ import annotations

from fastapi import APIRouter, Path, Request, Response, status

from lumen.api.deps import Connection, wake_task_runner
from lumen.schemas.common import ErrorResponse
from lumen.schemas.storage_roots import StorageRoot, StorageRootCreate, StorageRootList
from lumen.schemas.tasks import Task
from lumen.services import storage_roots as service
from lumen.services import tasks as task_service

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
def create_storage_root(body: StorageRootCreate, conn: Connection, request: Request) -> StorageRoot:
    root = service.create_storage_root(conn, body)
    wake_task_runner(request)
    return root


@router.post(
    "/{root_id}/scan",
    response_model=Task,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="scanStorageRoot",
    responses={404: {"model": ErrorResponse}},
)
def scan_storage_root(conn: Connection, request: Request, root_id: int = Path(ge=1)) -> Task:
    """Queue a rescan (reuses an already queued or running scan of this root)."""
    task_id = service.request_scan(conn, root_id)
    wake_task_runner(request)
    return task_service.get_task(conn, task_id)


@router.delete(
    "/{root_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteStorageRoot",
    responses={404: {"model": ErrorResponse}},
)
def delete_storage_root(conn: Connection, root_id: int = Path(ge=1)) -> Response:
    service.delete_storage_root(conn, root_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
