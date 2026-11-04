"""Offline reverse geocoding: the town, region and country a photo was taken in.

Places come from the bundled GeoNames extract (``data/places.tsv.gz``, built by
``lumen.geo.build``): about 160 000 towns of 1 000+ people with Chinese and French names.
There are no boundaries, so a point is given to the place that "covers" it best: the
distance is divided by a radius that grows with the population (a large city wins over a
village next to it, a village wins in its own centre).
"""

from __future__ import annotations

import gzip
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DATA_FILE = Path(__file__).parent / "data" / "places.tsv.gz"
EARTH_KM = 6371.0
_BATCH = 16


@dataclass(frozen=True)
class Names:
    name: str
    zh: str
    fr: str

    @classmethod
    def parse(cls, name: str, zh: str, fr: str) -> Names:
        return cls(name=name, zh=zh or name, fr=fr or name)


@dataclass(frozen=True)
class Place:
    place_id: int
    city: Names
    region: Names | None
    country_code: str
    country: Names
    distance_km: float


def data_version(path: Path = DATA_FILE) -> str:
    """The version line of the data file (cheap: reads only the first line)."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return handle.readline().strip().lstrip("#")


class Gazetteer:
    def __init__(self, path: Path = DATA_FILE) -> None:
        countries: dict[str, Names] = {}
        regions: dict[str, Names] = {}
        ids: list[int] = []
        coords: list[tuple[float, float]] = []
        populations: list[int] = []
        keys: list[tuple[str, str]] = []
        names: list[Names] = []
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            self.version = handle.readline().strip().lstrip("#")
            for line in handle:
                cols = line.rstrip("\n").split("\t")
                if cols[0] == "P":
                    ids.append(int(cols[1]))
                    coords.append((float(cols[2]), float(cols[3])))
                    keys.append((cols[4], cols[5]))
                    populations.append(int(cols[6]))
                    names.append(Names.parse(cols[7], cols[8], cols[9]))
                elif cols[0] == "A":
                    regions[cols[1]] = Names.parse(cols[2], cols[3], cols[4])
                elif cols[0] == "C":
                    countries[cols[1]] = Names.parse(cols[2], cols[3], cols[4])
        self._countries = countries
        self._regions = regions
        self._ids = ids
        self._keys = keys
        self._names = names
        # float64: in float32 the cosine of a few kilometres rounds to 1.
        self._vectors = _unit_vectors(np.array(coords, dtype=np.float64))
        population = np.maximum(np.array(populations, dtype=np.float64), 1000.0)
        # Radius a place "covers": ~1.5 km for 1 000 people, ~19 km for 2 million.
        self._radius_km = 1.5 * np.cbrt(population / 1000.0)

    def __len__(self) -> int:
        return len(self._ids)

    def locate(self, points: list[tuple[float, float]]) -> list[Place]:
        """The place of each (latitude, longitude)."""
        found: list[Place] = []
        for start in range(0, len(points), _BATCH):
            batch = _unit_vectors(np.array(points[start : start + _BATCH], dtype=np.float64))
            cosines = np.clip(batch @ self._vectors.T, -1.0, 1.0)
            distances = EARTH_KM * np.arccos(cosines)
            best = np.argmin(distances / self._radius_km, axis=1)
            for row, index in enumerate(best.tolist()):
                found.append(self._place(index, float(distances[row, index])))
        return found

    def _place(self, index: int, distance_km: float) -> Place:
        country_code, admin1 = self._keys[index]
        country = self._countries.get(country_code) or Names(country_code, country_code, "")
        return Place(
            place_id=self._ids[index],
            city=self._names[index],
            region=self._regions.get(f"{country_code}.{admin1}"),
            country_code=country_code,
            country=Names(country.name, country.zh, country.fr or country.name),
            distance_km=round(distance_km, 2),
        )


def _unit_vectors(latlon_degrees: np.ndarray) -> np.ndarray:
    lat = np.radians(latlon_degrees[:, 0])
    lon = np.radians(latlon_degrees[:, 1])
    return np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], axis=1)


_lock = threading.Lock()
_gazetteer: Gazetteer | None = None


def gazetteer() -> Gazetteer:
    """The bundled gazetteer, loaded on first use (~1 s) and kept in memory."""
    global _gazetteer
    with _lock:
        if _gazetteer is None:
            _gazetteer = Gazetteer()
        return _gazetteer
