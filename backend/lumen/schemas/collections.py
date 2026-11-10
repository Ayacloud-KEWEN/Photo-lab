from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from lumen.schemas.assets import AssetSummary, MapPoint, NamedPlace, PlaceName

CollectionKind = Literal["album", "trip"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
MAX_ITEMS = 20_000


class _Dates(BaseModel):
    @model_validator(mode="after")
    def _ordered(self) -> _Dates:
        start, end = getattr(self, "start_date", None), getattr(self, "end_date", None)
        if start and end and end < start:
            raise ValueError("the end date is before the start date")
        return self


class CollectionCreate(_Dates):
    name: Name
    kind: CollectionKind = "album"
    description: str | None = Field(default=None, max_length=5000)
    place: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    asset_ids: list[int] = Field(default_factory=list, max_length=MAX_ITEMS)


class CollectionUpdate(_Dates):
    """Only the fields sent are changed (``null`` clears)."""

    name: Name | None = None
    kind: CollectionKind | None = None
    description: str | None = Field(default=None, max_length=5000)
    place: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    cover_asset_id: int | None = None
    collage_asset_ids: list[int | None] | None = Field(
        default=None, max_length=2, description="The two small photos; null slots: automatic"
    )


class Collection(BaseModel):
    id: int
    uuid: str
    name: str
    kind: CollectionKind
    description: str | None
    place: str | None
    start_date: str | None
    end_date: str | None
    item_count: int
    cover_asset_id: int | None = Field(description="The chosen cover; null: the first item")
    cover: AssetSummary | None = Field(description="The chosen cover, else the first item")
    samples: list[AssetSummary] = Field(
        default_factory=list,
        description="The collage's 2 small photos: chosen ones, else the first other items",
    )
    collage_asset_ids: list[int | None] = Field(
        default_factory=lambda: list[int | None]([None, None]),
        description="Chosen small photos (null: automatic)",
    )
    first_capture: str | None
    last_capture: str | None
    created_at: str
    updated_at: str


class CollectionList(BaseModel):
    items: list[Collection]


class CollectionItem(BaseModel):
    asset: AssetSummary
    caption: str | None
    caption_draft: str | None = Field(
        default=None, description="Caption suggested by the local model, until accepted"
    )


class CollectionDetail(Collection):
    items: list[CollectionItem] = Field(description="In the collection's order")


class CollectionAssets(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=MAX_ITEMS)


class CollectionChange(BaseModel):
    changed: int


class CollectionItemUpdate(BaseModel):
    caption: str | None = Field(default=None, max_length=2000)


class TripSuggestion(BaseModel):
    start_date: str
    end_date: str
    asset_count: int
    asset_ids: list[int]
    samples: list[AssetSummary] = Field(description="A few photos spread over the trip")
    latitude: float
    longitude: float
    distance_km: float = Field(description="From home (where most located photos were taken)")
    cities: list[PlaceName] = Field(description="Most photographed towns (up to 3), for naming")
    countries: list[PlaceName] = Field(description="Most photographed first")


class TripSuggestions(BaseModel):
    items: list[TripSuggestion] = Field(description="Newest first")


class RouteStop(BaseModel):
    lat: float = Field(description="Centre of the stop's photos")
    lon: float
    start: str = Field(description="Capture time of its first photo")
    end: str
    day: int = Field(description="Day of the route: 1 is the day of the first located photo")
    asset_ids: list[int] = Field(description="In capture order")
    cover: MapPoint = Field(description="The photo shown for the stop (best rated, else first)")
    place: PlaceName | None = Field(description="Town most of its photos were taken in")


class CollectionRoute(BaseModel):
    points: list[MapPoint] = Field(description="Located photos, in capture order")
    places: list[NamedPlace] = Field(description="Towns of the points")
    stops: list[RouteStop] = Field(description="Runs of photos taken close together, in order")
    distance_km: float = Field(description="Straight lines from stop to stop")
    days: int = Field(description="Calendar days from the first to the last located photo")
    unlocated: int = Field(description="Photos of the collection without a location")


class StoryRequest(BaseModel):
    language: Literal["zh-CN", "en", "fr"] = "zh-CN"
    writer: Literal["qwen3.6-35b-a3b", "qwen3.8-27b", "deepseek"] = Field(
        default="qwen3.6-35b-a3b",
        description="Who writes the story from the day notes (DeepSeek: after the user saw them)",
    )
    notes_from: int | None = Field(
        default=None, description="Reuse the day notes of this story: only write it again"
    )


class StoryCloudRequest(BaseModel):
    confirmed: Literal[True] = Field(
        description="Must be true: the user reviewed the day notes that will be sent"
    )


class StoryStarted(BaseModel):
    task_id: int


class CaptionDraftRequest(BaseModel):
    asset_ids: list[int] | None = Field(
        default=None,
        max_length=MAX_ITEMS,
        description="These items (even captioned ones); null: every item without a caption",
    )
    language: Literal["zh-CN", "en", "fr"] = "zh-CN"


class DraftSettle(BaseModel):
    asset_ids: list[int] | None = Field(
        default=None, max_length=900, description="null: every suggested caption"
    )


class DiaryNote(BaseModel):
    after_asset_id: int | None = Field(description="The photo it follows; null: opens the day")
    text: str


class DiaryDay(BaseModel):
    number: int = Field(description="1 for the first day with photos")
    date: str = Field(description="YYYY-MM-DD; empty for undated photos")
    places: list[PlaceName] = Field(description="Towns of the day, in the order visited")
    asset_ids: list[int] = Field(description="Its photos and videos, in capture order")
    intro: str | None = Field(description="The day's opening text")
    notes: list[DiaryNote] = Field(description="Texts after its photos, in photo order")


class Diary(BaseModel):
    days: list[DiaryDay]


class DiaryWrite(BaseModel):
    day: str = Field(pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    after_asset_id: int | None = None
    text: str = Field(max_length=20_000, description="Empty: removes the text")


class DiaryImport(BaseModel):
    analysis_id: int = Field(description="A travel story whose day notes become day texts")
