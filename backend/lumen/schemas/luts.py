from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LutSpace = Literal["rec709", "p3"]
LutKind = Literal["look", "log", "transform"]


class Lut(BaseModel):
    id: str
    ref: str = Field(description="What a recipe stores: <id>.<color_space>")
    name: str
    pack: str | None
    color_space: LutSpace
    kind: LutKind = Field(
        description="look: for finished photos and videos; log: needs log footage; "
        "transform: a colour-space conversion"
    )
    size: int
    hidden: bool
    used: int = Field(description="Photos and videos whose current edit uses it")


class LutList(BaseModel):
    items: list[Lut]


class LutImport(BaseModel):
    paths: list[str] = Field(
        min_length=1, max_length=2000, description=".cube files or folders (searched deeply)"
    )
    color_space: LutSpace = Field(default="rec709", description="What the LUTs expect")


class LutImportResult(BaseModel):
    imported: int
    already: int = Field(description="Same content as a LUT imported before")
    failed: list[str] = Field(description="Files that are not usable 3D LUTs (with why)")
    items: list[Lut]


class LutUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    color_space: LutSpace | None = None
    kind: LutKind | None = None
    hidden: bool | None = None
