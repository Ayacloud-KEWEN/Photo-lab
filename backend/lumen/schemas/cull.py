from __future__ import annotations

from pydantic import BaseModel, Field

from lumen.schemas.assets import AssetQuality, AssetSummary


class CullItem(BaseModel):
    asset: AssetSummary
    quality: AssetQuality | None


class SimilarGroup(BaseModel):
    items: list[CullItem] = Field(description="In capture order")
    recommended_id: int = Field(description="The photo to keep")
    pending: bool = Field(description="Some photos have neither a pick nor a reject flag")


class SimilarGroups(BaseModel):
    available: bool = Field(description="False until photos are indexed by the local AI")
    groups: list[SimilarGroup] = Field(description="Newest first")
    group_count: int
    pending_count: int


class Suspects(BaseModel):
    items: list[CullItem] = Field(description="Worst first")
    total: int


class RejectedFiles(BaseModel):
    asset_count: int
    paths: list[str] = Field(description="Every file of the rejected assets that is on disk")
