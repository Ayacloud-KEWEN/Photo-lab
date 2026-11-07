from __future__ import annotations

from pydantic import BaseModel, Field

MAX_ASSETS = 5000


class MapWebTestRequest(BaseModel):
    url: str = Field(min_length=8, max_length=300)


class MapWebStatus(BaseModel):
    url: str
    point_count: int = Field(description="Footprints on the map")


class MapWebAttach(BaseModel):
    point_id: int
    title: str
    visited_at: str | None
    count: int = Field(description="Photos added to this existing footprint")


class MapWebGroup(BaseModel):
    title: str = Field(description="The title the new footprint will get")
    lat: float
    lon: float
    start: str | None = Field(description="Capture time of its first photo (UTC)")
    count: int


class MapWebPlan(BaseModel):
    url: str
    photo_count: int = Field(description="Photos among the selection")
    video_count: int = Field(description="Videos (MapWeb keeps photos only, so not sent)")
    attach: list[MapWebAttach] = Field(description="Existing footprints that get photos")
    groups: list[MapWebGroup] = Field(description="New footprints")
    duplicate_count: int = Field(description="Photos sent before (skipped)")
    unplaced_count: int = Field(description="Photos without a location or a nearby footprint")


class MapWebPlanRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=MAX_ASSETS)
    language: str = Field(default="zh-CN", max_length=10)


class MapWebSendRequest(MapWebPlanRequest):
    description: str | None = Field(
        default=None, max_length=500, description="Text for new footprints (e.g. the portfolio)"
    )
