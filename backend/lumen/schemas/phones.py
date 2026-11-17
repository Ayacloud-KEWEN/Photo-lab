from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lumen.schemas.settings import _check_folder


class Phone(BaseModel):
    id: str
    name: str
    status: Literal["ready", "locked"] = Field(
        description="locked: connected but its photos cannot be read (locked, or this "
        "computer not trusted yet)"
    )


class PhoneList(BaseModel):
    items: list[Phone]
    folder: str = Field(description="Where the photos are copied")
    include_edited: bool
    available: bool = Field(description="False when phones cannot be read on this system")


class PhoneSummary(BaseModel):
    total: int = Field(description="Photos and videos on the phone")
    new_count: int = Field(description="Not imported yet: what an import copies")
    new_bytes: int
    already: int = Field(description="Imported before or already in the library")


class PhoneImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder: str | None = Field(default=None, max_length=500)
    include_edited: bool | None = None

    @field_validator("folder")
    @classmethod
    def _valid_folder(cls, value: str | None) -> str | None:
        return _check_folder(value.strip()) if value and value.strip() else None
