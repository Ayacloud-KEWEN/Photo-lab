"""Finding trips in the library: runs of photos taken far from home.

"Home" is where most located photos were taken (to 0.1°). A trip starts with a photo
taken more than ``AWAY_KM`` from home and continues while photos are away (or have no
location) and follow each other within ``MAX_GAP``; a photo taken at home ends it.
Pure functions over (id, time, latitude, longitude) rows: no database access.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

AWAY_KM = 50.0
MAX_GAP = timedelta(hours=48)
MIN_ASSETS = 5


@dataclass(frozen=True)
class Shot:
    asset_id: int
    taken: datetime
    latitude: float | None = None
    longitude: float | None = None

    @property
    def located(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass
class Trip:
    shots: list[Shot] = field(default_factory=list)
    latitude: float = 0.0
    longitude: float = 0.0
    distance_km: float = 0.0

    @property
    def start(self) -> datetime:
        return self.shots[0].taken

    @property
    def end(self) -> datetime:
        return self.shots[-1].taken


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def home(shots: list[Shot]) -> tuple[float, float] | None:
    """The centre of the 0.1° cell with the most located photos."""
    cells = Counter(
        (round(s.latitude, 1), round(s.longitude, 1))
        for s in shots
        if s.latitude is not None and s.longitude is not None
    )
    if not cells:
        return None
    (latitude, longitude), _ = cells.most_common(1)[0]
    return latitude, longitude


def find_trips(shots: list[Shot], *, min_assets: int | None = None) -> list[Trip]:
    """Trips in ``shots`` (sorted by time) with at least ``min_assets`` (default
    ``MIN_ASSETS``) photos, oldest first."""
    minimum = MIN_ASSETS if min_assets is None else min_assets
    base = home(shots)
    if base is None:
        return []

    def away(shot: Shot) -> bool | None:
        if shot.latitude is None or shot.longitude is None:
            return None
        return distance_km(base[0], base[1], shot.latitude, shot.longitude) > AWAY_KM

    trips: list[Trip] = []
    current: list[Shot] = []

    def close() -> None:
        # Photos without a location at the end may well be back home: leave them out.
        while current and not current[-1].located:
            current.pop()
        if len(current) >= minimum:
            trips.append(_finish(current, base))
        current.clear()

    for shot in shots:
        state = away(shot)
        if current and shot.taken - current[-1].taken > MAX_GAP:
            close()
        if state is True or (state is None and current):
            current.append(shot)
        elif state is False:
            close()
    close()
    return trips


def _finish(shots: list[Shot], base: tuple[float, float]) -> Trip:
    located = [s for s in shots if s.latitude is not None and s.longitude is not None]
    latitude = sum(s.latitude for s in located if s.latitude is not None) / len(located)
    longitude = sum(s.longitude for s in located if s.longitude is not None) / len(located)
    return Trip(
        shots=list(shots),
        latitude=latitude,
        longitude=longitude,
        distance_km=distance_km(base[0], base[1], latitude, longitude),
    )


def spread(items: list[int], count: int) -> list[int]:
    """``count`` items evenly spread over ``items`` (first and last included)."""
    if len(items) <= count:
        return list(items)
    step = (len(items) - 1) / (count - 1)
    return [items[round(index * step)] for index in range(count)]
