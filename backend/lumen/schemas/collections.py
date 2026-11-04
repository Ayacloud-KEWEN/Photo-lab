from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from lumen.schemas.assets import AssetSummary, PlaceName

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
    cover: AssetSummary | None = Field(description="The chosen cover, else the first item")
    first_capture: str | None
    last_capture: str | None
    created_at: str
    updated_at: str


class CollectionList(BaseModel):
    items: list[Collection]


class CollectionItem(BaseModel):
    asset: AssetSummary
    caption: str | None


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
