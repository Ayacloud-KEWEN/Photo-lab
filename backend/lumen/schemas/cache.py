from __future__ import annotations

from pydantic import BaseModel, Field


class CacheUsage(BaseModel):
    count: int
    bytes: int


class CacheStatus(BaseModel):
    folder: str = Field(description="The folder in use")
    default_folder: str
    configured_folder: str | None = Field(description="The folder chosen in Settings, if any")
    folder_available: bool = Field(
        description="False when the chosen folder's drive was missing at startup: the default "
        "folder is used until the next start"
    )
    thumbs: CacheUsage
    previews: CacheUsage
    full: CacheUsage = Field(description="Full-size renditions of edited photos")
    other: CacheUsage
    total_bytes: int
    free_bytes: int | None = Field(description="Free space on the cache folder's drive")


class MoveCacheRequest(BaseModel):
    folder: str = Field(min_length=1, max_length=500)
