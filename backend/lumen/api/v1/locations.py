from __future__ import annotations

from fastapi import APIRouter, Query

from lumen.api.deps import Connection
from lumen.schemas.locations import (
    AssetsRequest,
    ChangeCount,
    NearbyRequest,
    NearbyResult,
    PlaceMatch,
    SetLocationRequest,
    TimeRange,
    TimeSetRequest,
    TimeShiftRequest,
)
from lumen.services import locations as service

router = APIRouter(tags=["locations"])


@router.post("/assets/location", response_model=ChangeCount, operation_id="setLocation")
def set_location(conn: Connection, body: SetLocationRequest) -> ChangeCount:
    """Put photos at a place. Stored in LUMEN only (originals are not changed); exports
    write it into the new files."""
    return ChangeCount(
        changed=service.set_location(conn, body.asset_ids, body.latitude, body.longitude)
    )


@router.post(
    "/assets/location/restore", response_model=ChangeCount, operation_id="restoreLocation"
)
def restore_location(conn: Connection, body: AssetsRequest) -> ChangeCount:
    """Back to the location in the photos' files (none if they have none)."""
    return ChangeCount(changed=service.restore_location(conn, body.asset_ids))


@router.post(
    "/assets/location/nearby", response_model=NearbyResult, operation_id="locateByTime"
)
def locate_by_time(conn: Connection, body: NearbyRequest) -> NearbyResult:
    """Each photo gets the location of the photo taken closest in time that has one."""
    return service.nearby_locations(conn, body.asset_ids, body.max_hours, apply=body.apply)


@router.post("/assets/time-shift", response_model=ChangeCount, operation_id="shiftTime")
def shift_time(conn: Connection, body: TimeShiftRequest) -> ChangeCount:
    """Move capture times (a camera clock set wrong). Exports write the corrected time."""
    return ChangeCount(changed=service.shift_time(conn, body.asset_ids, body.seconds))


@router.post("/assets/time-set", response_model=ChangeCount, operation_id="setTime")
def set_time(conn: Connection, body: TimeSetRequest) -> ChangeCount:
    """Set capture times to a date and time (one photo's, keeping the others' spacing, or
    all the same). Restoring the time in the files still works."""
    time = body.time.replace(tzinfo=None).isoformat()
    changed = service.set_time(
        conn, body.asset_ids, time, body.reference_asset_id, keep_spacing=body.keep_spacing
    )
    return ChangeCount(changed=changed)


@router.post("/assets/time-range", response_model=TimeRange, operation_id="timeRange")
def time_range(conn: Connection, body: AssetsRequest) -> TimeRange:
    """The earliest and latest capture times of these photos."""
    first, first_id, last = service.time_range(conn, body.asset_ids)
    return TimeRange(first=first, first_asset_id=first_id, last=last)


@router.post(
    "/assets/time-shift/restore", response_model=ChangeCount, operation_id="restoreTime"
)
def restore_time(conn: Connection, body: AssetsRequest) -> ChangeCount:
    return ChangeCount(changed=service.restore_time(conn, body.asset_ids))


@router.get("/places/search", response_model=list[PlaceMatch], operation_id="searchPlaces")
def search_places(
    q: str = Query(min_length=1, max_length=100), limit: int = Query(default=10, ge=1, le=50)
) -> list[PlaceMatch]:
    """Towns by name, offline (bundled GeoNames data, any of the three languages)."""
    return service.search_places(q, limit)
