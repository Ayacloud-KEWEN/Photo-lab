from __future__ import annotations

from fastapi import APIRouter, Path, Request, status

from lumen.api.deps import Connection, wake_task_runner
from lumen.schemas.common import ErrorResponse
from lumen.schemas.phones import PhoneImport, PhoneList, PhoneSummary
from lumen.schemas.tasks import Task
from lumen.services import phones as service
from lumen.services import tasks as task_service

router = APIRouter(prefix="/phones", tags=["phones"])

PHONE_ID = Path(pattern=r"^[0-9a-f]{16}$")


@router.get("", response_model=PhoneList, operation_id="listPhones")
def list_phones(conn: Connection) -> PhoneList:
    """Phones connected by cable (iPhone)."""
    return service.list_phones(conn)


@router.get(
    "/{phone_id}/summary",
    response_model=PhoneSummary,
    operation_id="getPhoneSummary",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def get_phone_summary(conn: Connection, phone_id: str = PHONE_ID) -> PhoneSummary:
    """How many photos and videos an import would copy (reads the phone's list of files)."""
    return service.summary(conn, phone_id)


@router.post(
    "/{phone_id}/import",
    response_model=Task,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="importFromPhone",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def import_from_phone(
    conn: Connection, request: Request, body: PhoneImport, phone_id: str = PHONE_ID
) -> Task:
    """Copy the photos and videos not imported yet, then scan the folder."""
    task_id = service.start_import(conn, phone_id, body)
    wake_task_runner(request)
    return task_service.get_task(conn, task_id)
