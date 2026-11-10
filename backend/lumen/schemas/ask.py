from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from lumen.schemas.assets import AssetSummary

Intent = Literal["photos", "count", "top"]
GroupBy = Literal["", "city", "country", "year", "month", "camera", "lens"]


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    language: Literal["zh-CN", "en", "fr"] = "zh-CN"


class AskPlan(BaseModel):
    """How the question was understood: the filters actually applied."""

    intent: Intent = "photos"
    date_from: str = ""
    date_to: str = Field(default="", description="Exclusive")
    country: str = Field(default="", description="ISO code")
    city: str = ""
    camera: str = ""
    lens: str = ""
    min_rating: int = 0
    favorite: bool = False
    media_type: Literal["", "photo", "video"] = ""
    keywords: list[str] = Field(default_factory=list, description="Any of them, in what was read")
    visual: str = Field(default="", description="Searched by image content (AI search)")
    group_by: GroupBy = ""


class AskCount(BaseModel):
    label: str
    count: int


class AskStats(BaseModel):
    total: int = Field(description="Matching photos and videos")
    described: int = Field(description="Of the candidates, how many the local model has read")
    first: str | None = None
    last: str | None = None
    groups: list[AskCount] = Field(default_factory=list)
    visual_used: bool = False


class AskAnswer(BaseModel):
    id: int
    question: str
    language: str
    status: Literal["pending", "done", "failed"]
    task_id: int | None
    plan: AskPlan | None
    stats: AskStats | None
    answer: str | None = Field(description="Markdown; [n] cites the n-th of ``items``")
    items: list[AssetSummary] = Field(description="Matching photos, best first (up to 60)")
    asset_ids: list[int] = Field(description="All matches kept (up to 500), best first")
    error: str | None
    created_at: str


class AskList(BaseModel):
    items: list[AskAnswer] = Field(description="Newest first (without photos)")
