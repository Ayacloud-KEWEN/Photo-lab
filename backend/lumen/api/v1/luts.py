from __future__ import annotations

from fastapi import APIRouter, Path, Response, status
from starlette.concurrency import run_in_threadpool

from lumen.api.deps import Connection
from lumen.schemas.luts import Lut, LutImport, LutImportResult, LutList, LutUpdate
from lumen.services import luts as service

router = APIRouter(prefix="/luts", tags=["luts"])

LUT_ID = Path(pattern=r"^[0-9a-f]{16}$")


@router.get("", response_model=LutList, operation_id="listLuts")
def list_luts(conn: Connection) -> LutList:
    return service.list_luts(conn)


@router.post("/import", response_model=LutImportResult, operation_id="importLuts")
async def import_luts(conn: Connection, body: LutImport) -> LutImportResult:
    """Copy .cube files (or every .cube in folders) into the LUT library."""
    return await run_in_threadpool(service.import_luts, conn, body)


@router.patch("/{lut_id}", response_model=Lut, operation_id="updateLut")
def update_lut(conn: Connection, body: LutUpdate, lut_id: str = LUT_ID) -> Lut:
    return service.update_lut(conn, lut_id, body)


@router.delete("/{lut_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteLut")
def delete_lut(conn: Connection, lut_id: str = LUT_ID) -> Response:
    """Delete a LUT (hidden instead when an edit uses it)."""
    service.delete_lut(conn, lut_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
