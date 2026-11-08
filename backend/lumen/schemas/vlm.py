from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AssetDescription(BaseModel):
    """What the local model saw in a photo (machine-written: it can be wrong)."""

    description: str = Field(description="Empty when the model could not read the photo")
    text: str = Field(description="Text in the photo as written, one line each")
    keywords: list[str]
    model: str
    model_label: str
    fine: bool = Field(description="Read with the slower, more careful model")
    truncated: bool = Field(description="The answer was cut off: the text may be incomplete")
    created_at: str


class VlmModelInfo(BaseModel):
    id: str
    label: str
    role: Literal["default", "fine"]
    downloaded: bool
    size_gb: float
    licence: str
    repo: str


class VlmStatus(BaseModel):
    enabled: bool
    scope: Literal["priority", "all"]
    folder: str
    runtime_installed: bool = Field(description="llama.cpp is present in the folder")
    models: list[VlmModelInfo]
    described: int = Field(description="Photos read (at the current prompt version)")
    requested: int = Field(description="Photos waiting because the user asked for them")
    to_read: int = Field(description="Photos still to read within the scope")


class VlmDescribeRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=20_000)
    fine: bool = Field(default=False, description="Use the slower, more careful model")


class VlmDescribeResult(BaseModel):
    queued: int
    task_id: int


class VlmDownloadRequest(BaseModel):
    model: str
