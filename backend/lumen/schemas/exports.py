from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from lumen.schemas.tasks import Task

MAX_EXPORT_ASSETS = 20_000


class ExportRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=MAX_EXPORT_ASSETS)
    destination: str = Field(min_length=1, description="An existing folder (absolute path)")
    long_edge: int | None = Field(
        default=None, ge=256, le=20_000, description="Long side in pixels; null: full size"
    )
    quality: int = Field(default=90, ge=50, le=100, description="JPEG quality")
    include_metadata: bool = Field(default=True, description="Copy EXIF/XMP from the original")
    include_location: bool = Field(default=False, description="Keep GPS (only with metadata)")
    video_mode: Literal["copy", "h264"] = Field(
        default="copy",
        description="Videos: copy the streams (original quality, fast) or re-encode to H.264",
    )


class ExportFailure(BaseModel):
    asset_id: int
    file_name: str
    error: str


class ExportResult(BaseModel):
    """The ``result`` of a finished export task."""

    destination: str
    exported: int
    skipped: int = Field(description="Items whose original is unavailable")
    failed: list[ExportFailure]


class ExportStatus(BaseModel):
    task: Task
    result: ExportResult | None = Field(description="Set once the export has finished")
