from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MediaType = Literal["photo", "video"]
FileRole = Literal["primary", "companion", "sidecar"]
RenditionVariant = Literal["thumb", "preview"]


class AssetSummary(BaseModel):
    id: int
    media_type: MediaType
    capture_time: str | None
    rating: int
    is_favorite: bool
    file_name: str = Field(description="Name of the file shown as the asset's cover")
    formats: list[str] = Field(description="Upper-case extensions of the asset's files")
    width: int | None
    height: int | None
    duration_ms: int | None
    rendition_version: str = Field(
        description="Changes whenever the cover's content changes; use as cache-buster"
    )


class AssetPage(BaseModel):
    items: list[AssetSummary]
    next_cursor: str | None


class AssetFile(BaseModel):
    id: int
    storage_root_id: int
    role: FileRole
    path: str = Field(description="Absolute path (root path + relative path)")
    relative_path: str
    size_bytes: int
    status: Literal["present", "missing", "error"]
    ingest_state: Literal["pending", "done", "error"]
    ingest_error: str | None
    fingerprint: str | None


class AssetMetadata(BaseModel):
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    capture_time: str | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    focal_length_mm: float | None = None
    aperture: float | None = None
    exposure_time_s: float | None = None
    iso: int | None = None
    video_codec: str | None = None
    frame_rate: float | None = None


class AssetLocation(BaseModel):
    latitude: float
    longitude: float
    altitude_m: float | None
    source: Literal["exif", "manual"]


class AssetDetail(BaseModel):
    id: int
    uuid: str
    media_type: MediaType
    capture_time: str | None
    rating: int
    is_favorite: bool
    notes: str | None
    rendition_version: str | None
    metadata: AssetMetadata
    location: AssetLocation | None
    files: list[AssetFile]


class DuplicateFile(BaseModel):
    file_id: int
    asset_id: int | None
    storage_root_id: int
    path: str


class DuplicateGroup(BaseModel):
    fingerprint: str
    size_bytes: int
    files: list[DuplicateFile]


class DuplicateReport(BaseModel):
    groups: list[DuplicateGroup]
    reclaimable_bytes: int = Field(description="Bytes used by redundant copies in these groups")
