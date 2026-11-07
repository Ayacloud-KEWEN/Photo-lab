from __future__ import annotations

from pydantic import BaseModel, Field

from lumen.schemas.assets import PlaceName

MAX_ASSETS = 20_000


class _Assets(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=MAX_ASSETS)


class SetLocationRequest(_Assets):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class AssetsRequest(_Assets):
    pass


class NearbyRequest(_Assets):
    max_hours: float = Field(default=2, gt=0, le=48)
    apply: bool = Field(default=False, description="false: only count what would be found")


class NearbyLocation(BaseModel):
    asset_id: int
    from_asset_id: int = Field(description="The photo whose location is used")
    latitude: float
    longitude: float
    gap_s: int = Field(description="How far apart in time the two were taken")


class NearbyResult(BaseModel):
    found: int
    missing: int = Field(description="No located photo close enough in time")
    examples: list[NearbyLocation] = Field(description="The first few, for a preview")


class TimeShiftRequest(_Assets):
    seconds: int = Field(ge=-400 * 86400, le=400 * 86400, description="Added to capture times")


class ChangeCount(BaseModel):
    changed: int


class PlaceMatch(BaseModel):
    place_id: int
    city: PlaceName
    region: PlaceName | None
    country: PlaceName
    latitude: float
    longitude: float
