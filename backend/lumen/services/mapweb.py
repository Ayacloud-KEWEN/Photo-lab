"""Sending photos to MapWeb, the user's personal map on their Raspberry Pi (ADR-034).

LUMEN calls MapWeb's existing API; MapWeb needs no change. Photos go where MapWeb's own
photo import ("自动归位", ``public/js/photoimport.js``) would put them — the rules below
are a port of its ``planImport`` and must stay in step with it:

1. near an existing footprint (≤ 500 m and ≤ 3 h, or ≤ 150 m the same day) → added to it;
2. otherwise consecutive photos ≤ 300 m and ≤ 2 h apart make a new footprint;
3. a photo without a location goes to a footprint within an hour of it, else is skipped;
4. a photo sent before (same ``source_key``) is skipped.

Each photo is sent as a JPEG developed with its edit (long edge 2048 px, EXIF kept with
the location). Nothing is sent until the user confirms, and only to the address they set.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from lumen.core.errors import LumenError, NotFoundError
from lumen.develop.engine import DevelopError
from lumen.develop.exporter import ExportOptions, export_photo
from lumen.media.metadata import ExifToolSession
from lumen.schemas.mapweb import (
    MapWebAttach,
    MapWebGroup,
    MapWebPlan,
    MapWebSendRequest,
    MapWebStatus,
)
from lumen.services.assets import DevelopUnavailableError, develop_source
from lumen.services.develop import current_recipe
from lumen.services.settings import get_settings
from lumen.tasks.runner import PermanentTaskError, TaskContext

logger = logging.getLogger(__name__)

SEND_TASK = "mapweb_send"
LONG_EDGE = 2048
QUALITY = 85
TIMEOUT_S = 30
UPLOAD_TIMEOUT_S = 120

# MapWeb's rules (public/js/photoimport.js).
HOUR_S = 3600.0
ATTACH_KM = 0.5
ATTACH_HOURS = 3
SAME_SPOT_KM = 0.15
NO_GPS_MINUTES = 60
GROUP_KM = 0.3
GROUP_HOURS = 2
MAX_PHOTOS = 50  # per footprint, as on the server


class MapWebError(LumenError):
    code = "mapweb_failed"
    status_code = 502


class MapWebNotConfigured(LumenError):
    code = "mapweb_not_configured"


# ------------------------------------------------------------------------------ client


class MapWebClient:
    """MapWeb's HTTP API (no login: it is only reachable at home or over Tailscale)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        body: object = None,
        *,
        data: bytes | None = None,
        content_type: str | None = None,
        timeout: float = TIMEOUT_S,
    ) -> Any:
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method)
        request.add_header("Accept", "application/json")
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise MapWebError(
                f"MapWeb answered {exc.code}", details={"status": exc.code, "detail": detail}
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise MapWebError(
                "MapWeb cannot be reached", details={"url": self.base_url, "reason": str(reason)}
            ) from exc
        except json.JSONDecodeError as exc:
            raise MapWebError(
                "This address does not answer like MapWeb", details={"url": self.base_url}
            ) from exc

    def health(self) -> None:
        answer = self._request("GET", "/api/health")
        if not isinstance(answer, dict) or answer.get("ok") is not True:
            raise MapWebError(
                "This address does not answer like MapWeb", details={"url": self.base_url}
            )

    def points(self) -> list[dict[str, Any]]:
        answer = self._request("GET", "/api/points")
        if not isinstance(answer, list):
            raise MapWebError("Unexpected answer from MapWeb", details={"path": "/api/points"})
        return answer

    def sent_keys(self, keys: list[str]) -> set[str]:
        found: set[str] = set()
        for start in range(0, len(keys), 5000):
            answer = self._request(
                "POST", "/api/points/photo-keys", {"keys": keys[start : start + 5000]}
            )
            found.update(str(key) for key in answer or [])
        return found

    def create_points(self, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        created = self._request("POST", "/api/points/batch", points)
        if not isinstance(created, list) or len(created) != len(points):
            raise MapWebError("Unexpected answer from MapWeb", details={"path": "/batch"})
        return created

    def add_photo(self, point_id: int, jpeg: bytes, file_name: str, source_key: str) -> None:
        boundary = f"lumen-{uuid.uuid4().hex}"
        quoted = file_name.replace('"', "")
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="source_key"\r\n\r\n'
            f"{source_key}\r\n".encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
            f'filename="{quoted}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode(),
            jpeg,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        self._request(
            "POST",
            f"/api/points/{point_id}/photos",
            data=b"".join(parts),
            content_type=f"multipart/form-data; boundary={boundary}",
            timeout=UPLOAD_TIMEOUT_S,
        )


def client_for(conn: sqlite3.Connection) -> MapWebClient:
    url = get_settings(conn).mapweb_url
    if not url:
        raise MapWebNotConfigured("Set MapWeb's address in Settings first")
    return MapWebClient(url)


def test_connection(url: str) -> MapWebStatus:
    client = MapWebClient(url)
    client.health()
    return MapWebStatus(url=client.base_url, point_count=len(client.points()))


# -------------------------------------------------------------------------------- plan


@dataclass
class Photo:
    asset_id: int
    key: str
    name: str
    lat: float | None
    lng: float | None
    time: float | None  # seconds since the epoch (UTC)
    town: str | None = None

    @property
    def located(self) -> bool:
        return self.lat is not None and self.lng is not None


@dataclass
class Target:
    """An existing footprint and the photos planned for it."""

    pin: dict[str, Any]
    time: float | None
    room: int
    photos: list[Photo] = field(default_factory=list)


@dataclass
class Group:
    """A new footprint."""

    lat: float
    lng: float
    start: float | None
    last: float | None
    photos: list[Photo] = field(default_factory=list)


@dataclass
class Plan:
    attach: list[Target]
    groups: list[Group]
    duplicates: list[Photo]
    unplaced: list[Photo]


def distance_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    rad = math.pi / 180
    h = (
        math.sin((b_lat - a_lat) * rad / 2) ** 2
        + math.cos(a_lat * rad) * math.cos(b_lat * rad) * math.sin((b_lng - a_lng) * rad / 2) ** 2
    )
    return 12742 * math.asin(math.sqrt(min(1.0, h)))


def _same_day(a: float, b: float) -> bool:
    """The same calendar day where the user is (MapWeb compares in the browser's zone)."""
    return datetime.fromtimestamp(a).date() == datetime.fromtimestamp(b).date()


def _pin_time(pin: dict[str, Any]) -> float | None:
    value = pin.get("visited_at")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def plan_send(photos: list[Photo], pins: list[dict[str, Any]], sent: set[str]) -> Plan:
    """Where each photo goes (no network). ``photos`` sorted by time, unknown times last."""
    targets = [
        Target(pin=pin, time=_pin_time(pin), room=MAX_PHOTOS - len(pin.get("photos") or []))
        for pin in pins
        if isinstance(pin.get("lat"), (int, float)) and isinstance(pin.get("lng"), (int, float))
    ]
    groups: list[Group] = []
    duplicates: list[Photo] = []
    unplaced: list[Photo] = []
    later: list[Photo] = []

    for photo in photos:
        if photo.key in sent:
            duplicates.append(photo)
            continue
        if not photo.located:
            (later if photo.time is not None else unplaced).append(photo)
            continue
        lat, lng = float(photo.lat), float(photo.lng)  # type: ignore[arg-type]

        # 1. An existing footprint: distance and time scored together.
        match: Target | None = None
        best = math.inf
        for target in targets:
            if target.room <= 0:
                continue
            km = distance_km(lat, lng, float(target.pin["lat"]), float(target.pin["lng"]))
            hours = (
                abs(photo.time - target.time) / HOUR_S
                if photo.time is not None and target.time is not None
                else None
            )
            near = km <= ATTACH_KM and hours is not None and hours <= ATTACH_HOURS
            same_place = km <= SAME_SPOT_KM and (
                photo.time is None or target.time is None or _same_day(photo.time, target.time)
            )
            if not near and not same_place:
                continue
            score = km + (hours if hours is not None else 12) * 0.2  # an hour ≈ 200 m
            if score < best:
                best, match = score, target
        if match is not None:
            match.photos.append(photo)
            match.room -= 1
            continue

        # 2. A new footprint, continuing the last one when close in place and time.
        last = groups[-1] if groups else None
        continues = (
            last is not None
            and len(last.photos) < MAX_PHOTOS
            and distance_km(last.lat, last.lng, lat, lng) <= GROUP_KM
            and (
                photo.time is None
                or last.last is None
                or photo.time - last.last <= GROUP_HOURS * HOUR_S
            )
        )
        if continues and last is not None:
            last.photos.append(photo)
            if photo.time is not None:
                last.last = photo.time
        else:
            groups.append(Group(lat, lng, photo.time, photo.time, [photo]))

    # 3. Photos without a location: the footprint closest in time, within an hour.
    window = NO_GPS_MINUTES * 60
    for photo in later:
        time = photo.time
        assert time is not None
        gaps = [
            (abs(t.time - time), i)
            for i, t in enumerate(targets)
            if t.room > 0 and t.time is not None and abs(t.time - time) <= window
        ]
        if gaps:
            target = targets[min(gaps)[1]]
            target.photos.append(photo)
            target.room -= 1
            continue
        group_gaps = [
            (abs(g.start - time), i)
            for i, g in enumerate(groups)
            if g.start is not None and len(g.photos) < MAX_PHOTOS and abs(g.start - time) <= window
        ]
        if group_gaps:
            groups[min(group_gaps)[1]].photos.append(photo)
        else:
            unplaced.append(photo)

    return Plan(
        attach=[t for t in targets if t.photos], groups=groups,
        duplicates=duplicates, unplaced=unplaced,
    )  # fmt: skip


# ------------------------------------------------------------------------- the photos


def source_key(asset_uuid: str) -> str:
    """How MapWeb recognises a photo LUMEN sent before."""
    return f"lumen:{asset_uuid}"


def _utc_seconds(wall_clock: str, offset: str | None) -> float | None:
    """A capture time (local wall clock) as seconds since the epoch: with the photo's own
    EXIF offset when it has one, else in this computer's time zone (as MapWeb's import,
    which runs in the browser, reads a photo without an offset)."""
    try:
        moment = datetime.fromisoformat(wall_clock)
    except ValueError:
        return None
    if offset:
        text = offset.strip()
        try:
            sign = -1 if text.startswith("-") else 1
            hours, minutes = text.lstrip("+-").split(":")[:2]
            zone = timezone(sign * timedelta(hours=int(hours), minutes=int(minutes)))
            return moment.replace(tzinfo=zone).timestamp()
        except ValueError:
            pass
    return moment.astimezone().timestamp()  # naive: local time of this computer


@dataclass(frozen=True)
class Selection:
    photos: list[Photo]
    videos: int
    missing: int


def collect(conn: sqlite3.Connection, asset_ids: list[int], language: str) -> Selection:
    """The photos among ``asset_ids`` with what placing them needs, sorted by time."""
    ids = list(dict.fromkeys(asset_ids))
    photos: list[Photo] = []
    videos = 0
    town = {"zh": "city_zh", "fr": "city_fr"}.get(language[:2], "city")
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        for row in conn.execute(
            f"""
            SELECT a.id, a.uuid, a.media_type, a.capture_time, c.file_name, m.raw_json,
                   l.latitude, l.longitude, p.{town} AS town
            FROM media_assets a
            JOIN media_files c ON c.id = a.cover_file_id
                 AND c.ingest_state = 'done' AND c.status = 'present'
            LEFT JOIN media_metadata m ON m.file_id = c.id
            LEFT JOIN media_locations l ON l.asset_id = a.id
            LEFT JOIN media_places p ON p.asset_id = a.id
            WHERE a.id IN ({",".join("?" * len(chunk))})
            """,
            chunk,
        ):
            if row["media_type"] != "photo":
                videos += 1  # MapWeb keeps photos only
                continue
            offset = None
            if row["raw_json"]:
                try:
                    raw = json.loads(row["raw_json"])
                    offset = raw.get("EXIF:OffsetTimeOriginal") or raw.get("EXIF:OffsetTime")
                except (ValueError, AttributeError):
                    offset = None
            photos.append(
                Photo(
                    asset_id=int(row["id"]),
                    key=source_key(row["uuid"]),
                    name=row["file_name"],
                    lat=row["latitude"],
                    lng=row["longitude"],
                    time=_utc_seconds(row["capture_time"], offset)
                    if row["capture_time"]
                    else None,
                    town=row["town"],
                )
            )
    photos.sort(key=lambda p: (p.time is None, p.time or 0.0, p.asset_id))
    found = len(photos) + videos
    return Selection(photos=photos, videos=videos, missing=len(ids) - found)


def _plan_for(
    conn: sqlite3.Connection, client: MapWebClient, asset_ids: list[int], language: str
) -> tuple[Plan, Selection]:
    selection = collect(conn, asset_ids, language)
    sent = client.sent_keys([photo.key for photo in selection.photos])
    return plan_send(selection.photos, client.points(), sent), selection


def _group_title(group: Group, language: str) -> str:
    """The town most of its photos were taken in, else MapWeb's "Photos · time"."""
    towns: dict[str, int] = {}
    for photo in group.photos:
        if photo.town:
            towns[photo.town] = towns.get(photo.town, 0) + 1
    when = (
        datetime.fromtimestamp(group.start).strftime("%Y-%m-%d %H:%M")
        if group.start is not None
        else ""
    )
    if towns:
        town = max(towns, key=lambda name: towns[name])
        return f"{town} · {when}" if when else town
    word = "照片" if language.startswith("zh") else "Photos"
    return f"{word} · {when}" if when else word


def plan_summary(conn: sqlite3.Connection, asset_ids: list[int], language: str) -> MapWebPlan:
    client = client_for(conn)
    plan, selection = _plan_for(conn, client, asset_ids, language)
    return MapWebPlan(
        url=client.base_url,
        photo_count=len(selection.photos),
        video_count=selection.videos,
        attach=[
            MapWebAttach(
                point_id=int(t.pin["id"]),
                title=str(t.pin.get("title") or ""),
                visited_at=t.pin.get("visited_at"),
                count=len(t.photos),
            )
            for t in plan.attach
        ],
        groups=[
            MapWebGroup(
                title=_group_title(g, language),
                lat=round(g.lat, 5),
                lon=round(g.lng, 5),
                start=datetime.fromtimestamp(g.start, UTC).isoformat() if g.start else None,
                count=len(g.photos),
            )
            for g in plan.groups
        ],
        duplicate_count=len(plan.duplicates),
        unplaced_count=len(plan.unplaced),
    )


# -------------------------------------------------------------------------------- send


def start_send(conn: sqlite3.Connection, request: MapWebSendRequest, enqueue: Any) -> int:
    client_for(conn)  # configured?
    task_id: int = enqueue(conn, SEND_TASK, payload=request.model_dump())
    return task_id


def send_task(ctx: TaskContext) -> dict[str, Any]:
    """Create the new footprints, then upload each photo (developed with its edit). Sent
    photos are recognised by their ``source_key``, so a send that stopped resumes."""
    request = MapWebSendRequest.model_validate(ctx.payload)
    try:
        client = client_for(ctx.conn)
        plan, _ = _plan_for(ctx.conn, client, request.asset_ids, request.language)
    except LumenError as exc:
        raise PermanentTaskError(exc.message) from exc

    jobs: list[tuple[int, Photo]] = [(int(t.pin["id"]), p) for t in plan.attach for p in t.photos]
    created = 0
    if plan.groups:
        try:
            points = client.create_points(
                [
                    {
                        "lat": group.lat, "lng": group.lng, "emoji": "📷",
                        "title": _group_title(group, request.language)[:200],
                        **({"description": request.description[:5000]}
                           if request.description else {}),
                        **({"visited_at": datetime.fromtimestamp(group.start, UTC).isoformat()}
                           if group.start is not None else {}),
                    }
                    for group in plan.groups
                ]
            )  # fmt: skip
        except MapWebError as exc:
            raise PermanentTaskError(exc.message) from exc
        created = len(points)
        for point, group in zip(points, plan.groups, strict=True):
            jobs.extend((int(point["id"]), photo) for photo in group.photos)

    uploaded = 0
    failed: list[dict[str, Any]] = []
    ctx.progress(0, len(jobs), force=True)
    exiftool_path = ctx.settings.tool("exiftool")
    with (
        tempfile.TemporaryDirectory(prefix="lumen-mapweb-") as folder,
        ExifToolSession(exiftool_path) if exiftool_path else _NoExifTool() as exiftool,
    ):
        options = ExportOptions(
            long_edge=LONG_EDGE, quality=QUALITY, include_metadata=exiftool is not None,
            include_location=True,
        )  # fmt: skip
        for index, (point_id, photo) in enumerate(jobs):
            ctx.check()
            try:
                source = develop_source(ctx.conn, photo.asset_id)
                path = export_photo(
                    source.path, source.format, current_recipe(ctx.conn, photo.asset_id),
                    Path(folder), options, exiftool, stem=f"{photo.asset_id}",
                )  # fmt: skip
                jpeg = path.read_bytes()
                path.unlink(missing_ok=True)
                client.add_photo(point_id, jpeg, f"{Path(photo.name).stem}.jpg", photo.key)
                uploaded += 1
            except MapWebError as exc:
                if exc.details.get("status") is None:  # unreachable: stop, resume later
                    raise PermanentTaskError(exc.message) from exc
                failed.append({"asset_id": photo.asset_id, "error": exc.message})
            except (DevelopError, DevelopUnavailableError, NotFoundError, OSError) as exc:
                logger.warning(
                    "photo not sent to MapWeb",
                    extra={"asset_id": photo.asset_id, "error": str(exc)},
                )
                failed.append({"asset_id": photo.asset_id, "error": str(exc)})
            ctx.progress(index + 1, len(jobs))
    return {
        "uploaded": uploaded,
        "created_points": created,
        "attached_points": len(plan.attach),
        "skipped": len(plan.duplicates) + len(plan.unplaced),
        "failed": failed[:50],
    }


class _NoExifTool:
    """Stands in for an ExifTool session when ExifTool is not installed (no EXIF copied)."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        return None
