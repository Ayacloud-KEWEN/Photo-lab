from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from lumen.schemas.assets import AssetSummary, FileRole


class DuplicateFile(BaseModel):
    file_id: int
    path: str = Field(description="Absolute path")
    folder: str = Field(description="Storage root display name")
    role: FileRole
    size_bytes: int
    modified_at: str


class DuplicateAsset(BaseModel):
    asset: AssetSummary
    files: list[DuplicateFile]
    tag_count: int = Field(description="User and imported tags (not AI labels)")
    collection_count: int


class DuplicateGroup(BaseModel):
    assets: list[DuplicateAsset] = Field(description="The copy to keep first")
    keep_asset_id: int = Field(
        description="The copy merging keeps: of identical copies the one with most user data, "
        "of copies in different quality the best picture"
    )
    redundant_bytes: int = Field(description="Space the extra copies take on disk")


class DuplicateReport(BaseModel):
    groups: list[DuplicateGroup] = Field(description="Largest redundant size first")
    group_count: int
    redundant_bytes: int


class MergeGroup(BaseModel):
    asset_ids: list[int] = Field(min_length=2, max_length=50)
    keep_asset_id: int | None = Field(default=None, description="Default: the suggested copy")


class MergeRequest(BaseModel):
    groups: list[MergeGroup] = Field(min_length=1, max_length=1000)
    kind: Literal["identical", "copies"] = Field(
        default="identical",
        description="identical: same file content; copies: the same shot in another quality",
    )


class MergeResult(BaseModel):
    merged_groups: int
    removed_assets: int = Field(description="Library entries folded into another (files untouched)")
