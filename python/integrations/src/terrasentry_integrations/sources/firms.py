"""NASA FIRMS active-fire / thermal anomaly client."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from terrasentry_integrations.cache import CacheBackend, CacheEntry, geometry_hash
from terrasentry_integrations.errors import MissingCredentialError, SourceResponseError
from terrasentry_integrations.settings import IntegrationSettings
from terrasentry_integrations.sources.http import SourceHttpClient, SourceHttpConfig


class FireDetection(BaseModel):
    latitude: float
    longitude: float
    acq_date: date
    acq_time: str = ""
    brightness: float | None = None
    scan: float | None = None
    track: float | None = None
    satellite: str | None = None
    instrument: str | None = None
    confidence: str | None = None
    version: str | None = None
    bright_t31: float | None = None
    frp: float | None = None
    daynight: str | None = None


class FirmsHotspotResult(BaseModel):
    source: str
    geometry_hash: str
    date_window: str
    window_start: date
    window_end: date
    detection_count: int
    total_frp: float
    detections: list[FireDetection] = Field(default_factory=list)
    cached: bool = False
    fetched_at: datetime | None = None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def _to_str(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _first_value(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value is not None and value.strip():
            return value
    return None


def parse_detections(text: str) -> list[FireDetection]:
    """Parse a FIRMS area CSV response (empty bodies and ``No data`` mean zero rows).

    MODIS sources use ``brightness``/``bright_t31``; VIIRS sources (the default) use
    ``bright_ti4``/``bright_ti5``, so both spellings are accepted.
    """
    stripped = text.strip()
    if not stripped or stripped.lower().startswith("no data"):
        return []
    detections: list[FireDetection] = []
    reader = csv.DictReader(io.StringIO(stripped))
    for row in reader:
        try:
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
            acq_date = date.fromisoformat(row["acq_date"])
        except (KeyError, ValueError) as exc:
            raise SourceResponseError("firms", f"malformed fire detection row: {row}") from exc
        detections.append(
            FireDetection(
                latitude=latitude,
                longitude=longitude,
                acq_date=acq_date,
                acq_time=(row.get("acq_time") or "").strip(),
                brightness=_to_float(_first_value(row, "bright_ti4", "brightness")),
                scan=_to_float(row.get("scan")),
                track=_to_float(row.get("track")),
                satellite=_to_str(row.get("satellite")),
                instrument=_to_str(row.get("instrument")),
                confidence=_to_str(row.get("confidence")),
                version=_to_str(row.get("version")),
                bright_t31=_to_float(_first_value(row, "bright_ti5", "bright_t31")),
                frp=_to_float(row.get("frp")),
                daynight=_to_str(row.get("daynight")),
            )
        )
    return detections


def polygon_from_geometry(geometry: dict[str, Any]) -> BaseGeometry:
    polygon = shape(geometry)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon


def filter_in_polygon(detections: list[FireDetection], polygon: BaseGeometry) -> list[FireDetection]:
    """FIRMS area queries use a bounding box, so re-filter detections against the polygon."""
    return [
        detection
        for detection in detections
        if polygon.covers(Point(detection.longitude, detection.latitude))
    ]


def dedupe_detections(detections: list[FireDetection]) -> list[FireDetection]:
    seen: set[tuple[float, float, date, str, str | None]] = set()
    unique: list[FireDetection] = []
    for detection in detections:
        key = (
            round(detection.latitude, 5),
            round(detection.longitude, 5),
            detection.acq_date,
            detection.acq_time,
            detection.satellite,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(detection)
    return unique


class FirmsClient:
    """Fetches fire detections for a polygon within a date window."""

    def __init__(
        self,
        settings: IntegrationSettings,
        *,
        cache: CacheBackend,
        http: SourceHttpClient | None = None,
    ) -> None:
        if not settings.has_firms_key:
            raise MissingCredentialError("firms", "FIRMS_MAP_KEY")
        self._settings = settings
        self._cache = cache
        self._map_key = settings.firms_map_key
        self._source = settings.firms_source
        self._day_range_max = max(1, min(settings.firms_day_range_max, 5))
        self._http = http or SourceHttpClient(
            SourceHttpConfig(
                source="firms",
                base_url=settings.firms_api_base_url.rstrip("/"),
                rate_limit=settings.firms_rate_limit_per_10min,
                time_period=600.0,
            )
        )

    async def close(self) -> None:
        await self._http.close()

    async def hotspots_in_polygon(
        self,
        geometry: dict[str, Any],
        *,
        days: int = 30,
        end_date: date | None = None,
        refresh: bool = False,
    ) -> FirmsHotspotResult:
        """Active fire detections inside ``geometry`` for the last ``days`` days."""
        window_end = end_date or datetime.now(tz=UTC).date()
        window_start = window_end - timedelta(days=max(days, 1) - 1)
        geometry_hash_value = geometry_hash(geometry)
        date_window = f"{window_start.isoformat()}..{window_end.isoformat()}"

        if not refresh:
            cached = await self._cache.get("firms", geometry_hash_value, date_window)
            if cached is not None:
                return FirmsHotspotResult.model_validate(cached.payload).model_copy(update={"cached": True})

        polygon = polygon_from_geometry(geometry)
        bbox = polygon.bounds
        detections: list[FireDetection] = []
        cursor = window_start
        while cursor <= window_end:
            chunk_end = min(cursor + timedelta(days=self._day_range_max - 1), window_end)
            day_range = (chunk_end - cursor).days + 1
            raw = await self._fetch_area(bbox, day_range=day_range, start_date=cursor)
            detections.extend(filter_in_polygon(raw, polygon))
            cursor = chunk_end + timedelta(days=1)

        unique = dedupe_detections(detections)
        unique.sort(key=lambda item: (item.acq_date, item.acq_time, item.latitude, item.longitude))
        result = FirmsHotspotResult(
            source=self._source,
            geometry_hash=geometry_hash_value,
            date_window=date_window,
            window_start=window_start,
            window_end=window_end,
            detection_count=len(unique),
            total_frp=round(sum(item.frp or 0.0 for item in unique), 4),
            detections=unique,
            fetched_at=datetime.now(tz=UTC),
        )
        await self._cache.set(
            CacheEntry(
                source="firms",
                geometry_hash=geometry_hash_value,
                date_window=date_window,
                request={
                    "path_template": "/area/csv/{MAP_KEY}/{source}/{bbox}/{day_range}/{date}",
                    "source": self._source,
                    "bbox": [round(value, 4) for value in bbox],
                    "days": days,
                },
                status_code=200,
                fetched_at=datetime.now(tz=UTC),
                payload=result.model_dump(mode="json"),
            )
        )
        return result

    async def _fetch_area(
        self,
        bbox: tuple[float, float, float, float],
        *,
        day_range: int,
        start_date: date,
    ) -> list[FireDetection]:
        west, south, east, north = bbox
        path = (
            f"/area/csv/{self._map_key}/{self._source}/"
            f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}/"
            f"{day_range}/{start_date.isoformat()}"
        )
        response = await self._http.get(path)
        return parse_detections(response.text)
