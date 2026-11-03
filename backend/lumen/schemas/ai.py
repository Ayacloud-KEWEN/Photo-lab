from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lumen.schemas.assets import AssetSummary

AnalysisKind = Literal["describe", "critique", "select_best", "story"]

#: How many images each analysis accepts.
KIND_LIMITS: dict[str, tuple[int, int]] = {
    "describe": (1, 1),
    "critique": (1, 1),
    "select_best": (2, 12),
    "story": (2, 30),
}


class ModelInfo(BaseModel):
    id: str
    display_name: str
    backend: Literal["siglip2", "open_clip"]
    multilingual: bool
    approx_download_gb: float
    downloaded: bool


class LocalAIStatus(BaseModel):
    installed: bool = Field(description="AI components (PyTorch) are installed")
    device: Literal["cuda", "cpu"]
    device_name: str | None
    memory_gb: float | None
    enabled: bool
    model_id: str
    model_downloaded: bool
    model_loaded: bool
    indexed: int = Field(description="Assets with an embedding for the active model")
    total: int = Field(description="Assets that can be indexed")
    models: list[ModelInfo]


class CloudStatus(BaseModel):
    enabled: bool
    provider: Literal["deepseek"]
    model: str
    base_url: str
    has_key: bool
    include_location_default: bool


class AIStatus(BaseModel):
    local: LocalAIStatus
    cloud: CloudStatus


class SemanticPage(BaseModel):
    """Assets ranked by similarity; ``scores[i]`` (cosine) belongs to ``items[i]``."""

    items: list[AssetSummary]
    scores: list[float]
    relevant_count: int = Field(
        description="How many leading items are likely matches; the rest are weaker candidates"
    )
    model_id: str


class ModelDownload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str | None = None


class ApiKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=8, max_length=500)


class CloudTestResult(BaseModel):
    ok: bool
    message: str
    models: list[str] = Field(default_factory=list)
    vision: bool | None = Field(
        description="Whether the model accepted an image (None: not tested)"
    )


class CloudRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AnalysisKind
    asset_ids: list[int] = Field(min_length=1, max_length=30)
    include_location: bool = False
    text_only: bool = Field(
        default=False,
        description="Send metadata and local AI labels only, no images (fallback)",
    )
    language: Literal["zh-CN", "en", "fr"] = "zh-CN"


class CloudAnalyzeRequest(CloudRequest):
    confirmed: Literal[True] = Field(
        description="Must be true: the user reviewed exactly what will be sent"
    )


class CloudPreviewItem(BaseModel):
    asset_id: int
    rendition_version: str
    fields: dict[str, str] = Field(description="Metadata sent with the image")


class CloudPreview(BaseModel):
    provider: Literal["deepseek"]
    model: str
    host: str
    items: list[CloudPreviewItem]
    image_max_edge: int | None = Field(description="Long edge of uploaded images; None = no images")
    cached: bool = Field(description="A cached result exists: nothing will be uploaded")


class AnalysisResult(BaseModel):
    id: int
    kind: AnalysisKind
    provider: str
    model: str
    language: str
    vision: bool
    cached: bool
    result: str = Field(description="Markdown")
    data: dict[str, Any] | None
    asset_ids: list[int]
    input_tokens: int | None
    output_tokens: int | None
    created_at: str
