from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MediaType = Literal["photo", "video"]
AssetSort = Literal["capture_desc", "capture_asc", "added_desc"]
FileRole = Literal["primary", "companion", "sidecar"]
# "full": the whole photo (with its edit) at full size, for zooming in.
RenditionVariant = Literal["thumb", "preview", "full"]
# Culling: "pick" (keep) or "reject" (hidden unless asked for; never deleted).
CullFlag = Literal["none", "pick", "reject"]
QualityFlag = Literal["blurry", "overexposed", "underexposed"]


class AssetQuery(BaseModel):
    """Filters shared by the asset list, ids, timeline and map endpoints."""

    q: str | None = Field(default=None, max_length=200, description="Text search (substring)")
    media_type: MediaType | None = None
    min_rating: int | None = Field(default=None, ge=0, le=5)
    favorite: bool | None = None
    camera: str | None = Field(default=None, max_length=200, description="Camera model")
    lens: str | None = Field(default=None, max_length=200)
    format: str | None = Field(default=None, max_length=10, description="File extension, e.g. CR3")
    storage_root_id: int | None = Field(default=None, ge=1)
    tag_id: list[int] = Field(default_factory=list, description="Assets having all these tags")
    date_from: str | None = Field(default=None, description="Inclusive, YYYY-MM-DD[THH:MM:SS]")
    date_to: str | None = Field(default=None, description="Exclusive, YYYY-MM-DD[THH:MM:SS]")
    has_location: bool | None = None
    country: str | None = Field(
        default=None, pattern=r"^[A-Z]{2}$", description="ISO country code of the place taken"
    )
    place_id: int | None = Field(default=None, ge=1, description="GeoNames id of the town")
    rejected: Literal["hide", "show", "only"] = Field(
        default="hide", description="Rejected assets: hidden (default), shown too, or only them"
    )
    sort: AssetSort = "capture_desc"

    @field_validator("date_from", "date_to")
    @classmethod
    def _iso_prefix(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(
            r"\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2}(:\d{2})?)?)?)?", value
        ):
            raise ValueError("expected YYYY[-MM[-DD[THH:MM[:SS]]]]")
        return value


class AssetSummary(BaseModel):
    id: int
    media_type: MediaType
    capture_time: str | None
    rating: int
    is_favorite: bool
    file_name: str = Field(description="Name of the file shown as the asset's cover")
    formats: list[str] = Field(description="Upper-case extensions of the asset's files")
    width: int | None
    height: int | None
    duration_ms: int | None
    is_live: bool = Field(description="A Live Photo: has a motion clip (see /motion)")
    is_edited: bool = Field(description="Shown with a non-destructive edit applied")
    cover_extension: str = Field(description="Lower-case extension of the cover file")
    rendition_version: str = Field(
        description="Changes whenever the cover's content changes; use as cache-buster"
    )
    cull_flag: CullFlag


class AssetPage(BaseModel):
    items: list[AssetSummary]
    next_cursor: str | None


class AssetIds(BaseModel):
    ids: list[int]


class Tag(BaseModel):
    id: int
    name: str
    asset_count: int = 0


class AssetTag(BaseModel):
    id: int
    name: str
    source: Literal["user", "import", "ai"]
    confidence: float | None = Field(default=None, description="For AI labels (0-1)")


class AssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: int | None = Field(default=None, ge=0, le=5)
    is_favorite: bool | None = None
    notes: str | None = Field(default=None, max_length=10_000, description="Empty string clears")
    cull_flag: CullFlag | None = None


class AssetBatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ids: list[int] = Field(min_length=1, max_length=100_000)
    rating: int | None = Field(default=None, ge=0, le=5)
    is_favorite: bool | None = None
    cull_flag: CullFlag | None = None
    add_tags: list[str] = Field(default_factory=list, max_length=50, description="Tag names")
    remove_tag_ids: list[int] = Field(default_factory=list, max_length=50)


class BatchResult(BaseModel):
    updated: int


class FacetValue(BaseModel):
    value: str
    count: int


class PlaceName(BaseModel):
    """A place name in each interface language (the international name when untranslated)."""

    name: str
    zh: str
    fr: str


class CityFacet(BaseModel):
    place_id: int
    name: PlaceName
    count: int


class CountryFacet(BaseModel):
    country_code: str
    name: PlaceName
    count: int
    cities: list[CityFacet] = Field(description="Most photographed towns first")


class AssetFacets(BaseModel):
    total: int
    photos: int
    videos: int
    favorites: int
    with_location: int
    cameras: list[FacetValue]
    lenses: list[FacetValue]
    formats: list[FacetValue]
    years: list[FacetValue]
    tags: list[Tag]
    places: list[CountryFacet] = Field(description="Countries, most photographed first")


class TimelineBucket(BaseModel):
    period: str = Field(description="YYYY, YYYY-MM or YYYY-MM-DD")
    count: int


class Timeline(BaseModel):
    granularity: Literal["year", "month", "day"]
    buckets: list[TimelineBucket]


class MapPoint(BaseModel):
    id: int
    lat: float
    lon: float
    v: str = Field(description="Rendition version (for thumbnail URLs)")
    p: int | None = Field(description="Town (an id in ``places``)")


class NamedPlace(BaseModel):
    place_id: int
    name: PlaceName


class MapPoints(BaseModel):
    points: list[MapPoint]
    places: list[NamedPlace] = Field(description="Towns of the points")


class AssetFile(BaseModel):
    id: int
    storage_root_id: int
    role: FileRole
    path: str = Field(description="Absolute path (root path + relative path)")
    relative_path: str
    size_bytes: int
    status: Literal["present", "missing", "error"]
    ingest_state: Literal["pending", "done", "error"]
    ingest_error: str | None
    fingerprint: str | None


class AssetMetadata(BaseModel):
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    capture_time: str | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    focal_length_mm: float | None = None
    aperture: float | None = None
    exposure_time_s: float | None = None
    iso: int | None = None
    video_codec: str | None = None
    frame_rate: float | None = None


class AssetLocation(BaseModel):
    latitude: float
    longitude: float
    altitude_m: float | None
    source: Literal["exif", "manual"]


class AssetQuality(BaseModel):
    sharpness: float = Field(description="0..1")
    exposure: float = Field(description="0..1 (1 = nothing clipped)")
    score: float = Field(description="0..1 overall")
    flags: list[QualityFlag]


class AssetPlace(BaseModel):
    place_id: int = Field(description="GeoNames id of the town")
    city: PlaceName
    region: PlaceName | None
    country_code: str
    country: PlaceName
    distance_km: float = Field(description="From the town's centre")


class AssetDetail(BaseModel):
    id: int
    uuid: str
    media_type: MediaType
    capture_time: str | None
    rating: int
    is_favorite: bool
    rating_source: Literal["import", "user"] | None
    notes: str | None
    tags: list[AssetTag]
    cover_file_id: int | None = Field(description="File shown as thumbnail and by /original")
    motion_file_id: int | None = Field(description="Live Photo clip, served by /motion")
    is_edited: bool = Field(description="Shown with a non-destructive edit applied")
    rendition_version: str | None
    metadata: AssetMetadata
    location: AssetLocation | None
    place: AssetPlace | None = Field(description="Where the location is (offline place names)")
    cull_flag: CullFlag
    quality: AssetQuality | None = Field(description="Photos only, once measured")
    files: list[AssetFile]
