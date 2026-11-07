"""A collection's route: its located photos in capture order, grouped into stops.

Consecutive photos taken in the same town, or within ``STOP_KM`` of the stop's centre,
belong to that stop, so a few hundred photos of one town draw one point instead of a
tangle of short lines. Pure functions over (id, time, latitude, longitude, town) rows: no
database access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise

from lumen.library.trips import distance_km

STOP_KM = 1.0


@dataclass(frozen=True)
class RoutePoint:
    asset_id: int
    taken: datetime
    latitude: float
    longitude: float
    town: int | None = None
    """GeoNames id of the town, when the place is named."""


@dataclass
class Stop:
    points: list[RoutePoint] = field(default_factory=list)
    latitude: float = 0.0
    longitude: float = 0.0
    town: int | None = None

    def add(self, point: RoutePoint) -> None:
        self.points.append(point)
        if self.town is None:
            self.town = point.town
        count = len(self.points)
        self.latitude += (point.latitude - self.latitude) / count
        self.longitude += (point.longitude - self.longitude) / count

    @property
    def start(self) -> datetime:
        return self.points[0].taken

    @property
    def end(self) -> datetime:
        return self.points[-1].taken


def find_stops(points: list[RoutePoint], stop_km: float = STOP_KM) -> list[Stop]:
    """Stops in capture order; ``points`` must be sorted by time."""
    stops: list[Stop] = []
    for point in points:
        current = stops[-1] if stops else None
        same_town = current is not None and point.town is not None and point.town == current.town
        if current is None or (
            not same_town
            and distance_km(current.latitude, current.longitude, point.latitude, point.longitude)
            > stop_km
        ):
            current = Stop()
            stops.append(current)
        current.add(point)
    return stops


def route_km(stops: list[Stop]) -> float:
    """Length of the straight lines from stop to stop."""
    return sum(
        distance_km(a.latitude, a.longitude, b.latitude, b.longitude)
        for a, b in pairwise(stops)
    )
