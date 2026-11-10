from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Query, Request, Response, status

from lumen.api.deps import Connection, wake_task_runner
from lumen.schemas.ask import AskAnswer, AskList, AskRequest
from lumen.schemas.common import ErrorResponse
from lumen.vlm import ask as service

router = APIRouter(tags=["ask"])

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}


@router.post(
    "/ask", response_model=AskAnswer, status_code=status.HTTP_202_ACCEPTED,
    operation_id="askLibrary",
)  # fmt: skip
def ask(conn: Connection, request: Request, body: AskRequest) -> AskAnswer:
    """Ask the library in plain language; the local model answers in a task (follow
    ``task_id``, then read the question again). Nothing leaves this computer."""
    answer = service.ask(conn, request.app.state.settings, body.question, body.language)
    wake_task_runner(request)
    return answer


@router.get("/ask", response_model=AskList, operation_id="listQuestions")
def history(conn: Connection, limit: int = Query(default=50, ge=1, le=200)) -> AskList:
    """Questions asked before, newest first."""
    return service.history(conn, limit)


@router.get(
    "/ask/{question_id}", response_model=AskAnswer, operation_id="getQuestion",
    responses=NOT_FOUND,
)  # fmt: skip
def get(conn: Connection, question_id: int = Path(ge=1)) -> AskAnswer:
    return service.get(conn, question_id)


@router.delete(
    "/ask/{question_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
    operation_id="deleteQuestion", responses=NOT_FOUND,
)  # fmt: skip
def delete(conn: Connection, question_id: int = Path(ge=1)) -> Response:
    service.delete(conn, question_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
