from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AppSettings(BaseModel):
    map_online_tiles: bool = Field(
        default=False,
        description="Use the online street map (sends map viewport requests to OpenFreeMap)",
    )


class AppSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_online_tiles: bool | None = None
