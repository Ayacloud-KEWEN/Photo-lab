from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response, status
from starlette.concurrency import run_in_threadpool

from lumen.ai import cloud
from lumen.ai.pipeline import AI_DOWNLOAD_TASK, AI_INDEX_TASK
from lumen.api.deps import Connection, wake_task_runner
from lumen.core.config import Settings
from lumen.schemas.ai import (
    AIStatus,
    AnalysisResult,
    ApiKey,
    CloudAnalyzeRequest,
    CloudPreview,
    CloudRequest,
    CloudTestResult,
    ModelDownload,
    SemanticPage,
)
from lumen.schemas.assets import AssetQuery
from lumen.schemas.common import ErrorResponse
from lumen.schemas.tasks import Task
from lumen.services import ai as service
from lumen.services import tasks as task_service
from lumen.services.settings import get_settings
from lumen.tasks import queue

router = APIRouter(tags=["ai"])

Filters = Annotated[AssetQuery, Query()]
ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
}


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.get("/ai/status", response_model=AIStatus, operation_id="getAiStatus")
def get_status(conn: Connection, request: Request) -> AIStatus:
    return service.status(conn, _settings(request))


@router.post(
    "/ai/model/download", response_model=Task, status_code=status.HTTP_202_ACCEPTED,
    operation_id="downloadAiModel",
)  # fmt: skip
def download_model(conn: Connection, request: Request, body: ModelDownload) -> Task:
    """Download the active (or given) model into the HuggingFace cache, then index."""
    task_id = queue.enqueue(conn, AI_DOWNLOAD_TASK, payload=body.model_dump(exclude_none=True))
    wake_task_runner(request)
    return task_service.get_task(conn, task_id)


@router.post(
    "/ai/index", response_model=Task, status_code=status.HTTP_202_ACCEPTED,
    operation_id="indexAiAssets",
)  # fmt: skip
def index_assets(conn: Connection, request: Request) -> Task:
    task_id = queue.enqueue(conn, AI_INDEX_TASK)
    wake_task_runner(request)
    return task_service.get_task(conn, task_id)


@router.get("/ai/search", response_model=SemanticPage, operation_id="aiSearch", responses=ERRORS)
async def ai_search(
    conn: Connection,
    request: Request,
    query: Filters,
    text: str = Query(min_length=1, max_length=300, description="What to look for"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> SemanticPage:
    """Photos best matching a natural-language description (Chinese works directly)."""
    return await run_in_threadpool(service.search, conn, _settings(request), text, query, limit)


@router.get(
    "/assets/{asset_id}/similar", response_model=SemanticPage, operation_id="similarAssets",
    responses=ERRORS,
)  # fmt: skip
def similar_assets(
    conn: Connection,
    query: Filters,
    asset_id: int = Path(ge=1),
    limit: int = Query(default=100, ge=1, le=1000),
) -> SemanticPage:
    return service.similar(conn, asset_id, query, limit)


# ------------------------------------------------------------------ cloud


@router.put("/ai/cloud/key", status_code=status.HTTP_204_NO_CONTENT, operation_id="saveCloudKey")
def save_key(body: ApiKey) -> Response:
    """Store the DeepSeek API key in the Windows Credential Manager (never in the database)."""
    cloud.set_api_key(body.api_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/ai/cloud/key", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteCloudKey"
)
def delete_key() -> Response:
    cloud.delete_api_key()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/ai/cloud/test", response_model=CloudTestResult, operation_id="testCloud")
async def test_cloud(conn: Connection) -> CloudTestResult:
    """Check the saved key and whether the configured model accepts images."""
    return await run_in_threadpool(cloud.test_connection, get_settings(conn))


@router.post(
    "/ai/cloud/preview", response_model=CloudPreview, operation_id="previewCloudRequest",
    responses=ERRORS,
)  # fmt: skip
def preview_cloud(conn: Connection, body: CloudRequest) -> CloudPreview:
    """Exactly what would be sent for this request (shown to the user for consent)."""
    return cloud.preview(conn, get_settings(conn), body)


@router.post(
    "/ai/cloud/analyze", response_model=AnalysisResult, operation_id="analyzeWithCloud",
    responses=ERRORS,
)  # fmt: skip
async def analyze_cloud(
    conn: Connection, request: Request, body: CloudAnalyzeRequest
) -> AnalysisResult:
    """Run (or reuse a cached) cloud analysis. Requires ``confirmed: true``."""
    return await run_in_threadpool(
        cloud.analyze, conn, get_settings(conn), _settings(request).cache_dir, body
    )


@router.get(
    "/assets/{asset_id}/analyses", response_model=list[AnalysisResult],
    operation_id="listAssetAnalyses",
)  # fmt: skip
def list_analyses(conn: Connection, asset_id: int = Path(ge=1)) -> list[AnalysisResult]:
    return cloud.analyses_for_asset(conn, asset_id)
