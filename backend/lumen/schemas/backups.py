from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BackupKind = Literal["manual", "auto", "pre_restore", "migration", "other"]


class BackupInfo(BaseModel):
    name: str
    path: str
    kind: BackupKind = Field(
        description="manual, auto, pre_restore (made before a restore), migration (made "
        "before a database upgrade) or other (a file chosen by the user)"
    )
    created_at: str = Field(description="Local time, ISO 8601")
    size_bytes: int
    schema_version: int
    asset_count: int


class BackupList(BaseModel):
    folder: str
    default_folder: str
    folder_available: bool = Field(description="False when e.g. the backup drive is unplugged")
    last_auto_at: str | None
    items: list[BackupInfo] = Field(description="Newest first")


class RestoreRequest(BaseModel):
    name: str | None = Field(default=None, description="A listed backup")
    path: str | None = Field(default=None, max_length=1000, description="Any backup file")


class RestoreResult(BaseModel):
    restored: BackupInfo
    safety_backup: BackupInfo = Field(description="The database as it was before restoring")
    schema_version: int


class RevealRequest(BaseModel):
    name: str
