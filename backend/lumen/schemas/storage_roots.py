from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StorageRootStatus = Literal["pending_scan", "scanning", "ready", "offline", "error"]


class StorageRootCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    path: str = Field(min_length=1, max_length=32767, description="Absolute directory path")
    display_name: str | None = Field(default=None, min_length=1, max_length=255)


class StorageRoot(BaseModel):
    id: int
    path: str
    display_name: str
    status: StorageRootStatus
    is_available: bool = Field(description="Whether the directory is currently reachable")
    volume_serial: str | None
    volume_label: str | None
    last_scanned_at: str | None
    created_at: str
    updated_at: str


class StorageRootList(BaseModel):
    items: list[StorageRoot]
