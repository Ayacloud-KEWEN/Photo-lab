from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from lumen.schemas.assets import AssetSummary

MAX_ASSETS = 5000


class MapWebTestRequest(BaseModel):
    url: str = Field(min_length=8, max_length=300)


class MapWebStatus(BaseModel):
    url: str
    point_count: int = Field(description="Footprints on the map")
    features: list[str] = Field(
        default_factory=list,
        description="What this MapWeb supports beyond sending (photo-lookup, photo-replace, "
        "link-point…); empty for versions before them",
    )


class MapWebSync(BaseModel):
    on_map: int = Field(description="Photos of the library on the map")
    outdated: int = Field(description="…of which edited since they were sent")
    features: list[str]


class MapWebAssets(BaseModel):
    asset_ids: list[int] | None = Field(
        default=None, max_length=MAX_ASSETS, description="null: every outdated photo"
    )


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
    point_id: int | None = Field(
        default=None,
        description="Send every photo to this footprint (the user picked it on the map) "
        "instead of placing them by MapWeb's rules",
    )


# --- Layers on LUMEN's map ------------------------------------------------------------------


class LayerFootprint(BaseModel):
    id: int
    title: str
    description: str
    emoji: str
    lat: float
    lng: float
    visited_at: str | None
    photo_count: int
    thumb: str | None = Field(description="MapWeb path of its cover thumbnail (see /layers/thumb)")
    plan_id: int | None


class FootprintPhotos(BaseModel):
    point_id: int
    items: list[AssetSummary] = Field(description="LUMEN photos MapWeb's import would put here")
    here: list[int] = Field(description="…of which already on this footprint")
    elsewhere: list[int] = Field(description="…of which on another footprint")


class LayerTrack(BaseModel):
    id: int
    name: str
    sport: str
    started_at: str | None
    ended_at: str | None
    distance_m: float
    ascent_m: float
    geometry: dict[str, Any] = Field(description="GeoJSON LineString or MultiLineString")


class LayerPlanSummary(BaseModel):
    id: int
    title: str
    start_date: str | None
    end_date: str | None


class LayerPlanStop(BaseModel):
    name: str
    lat: float
    lng: float
    asset_ids: list[int] = Field(description="LUMEN photos taken that day within 3 km")


class LayerPlanDay(BaseModel):
    number: int
    date: str | None
    title: str
    stops: list[LayerPlanStop]


class LayerPlan(BaseModel):
    id: int
    title: str
    days: list[LayerPlanDay]
