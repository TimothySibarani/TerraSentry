"""NASA FIRMS hotspot tool.

The easiest real-data win in this project: a free API key, a CSV response, and
five years of fire history for any bounding box on earth.

API reference: https://firms.modaps.eosdis.nasa.gov/api/area/

Two constraints from the official docs that shape this client:

  * ``day_range`` is capped at **5 days per request**. Multi-year history therefore
    requires windowed calls -- see :func:`fetch_history`.
  * A map key is limited to **5000 transactions per 10-minute interval**, and a large
    request may consume more than one transaction. Five years of daily windows is
    ~365 calls per source per year, so cache aggressively (``data/cache/``) and never
    run a full history pull live on stage.

Source selection matters: ``*_NRT`` products are near-real-time (recent weeks),
``*_SP`` products are the quality-controlled science archive. For historical
analysis use the SP variants where available.
"""

from __future__ import annotations

import csv
import io
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Sequence

import requests

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

MAX_DAY_RANGE = 5  # hard API limit, verified against the FIRMS area API docs

# Near-real-time products (recent data) and science-quality archive products.
SOURCES_NRT = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT", "LANDSAT_NRT")
SOURCES_ARCHIVE = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "MODIS_SP")


class FirmsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Hotspot:
    latitude: float
    longitude: float
    acq_date: str
    acq_time: str
    confidence: str
    satellite: str
    instrument: str
    frp: float | None  # fire radiative power, MW
    source: str
    raw: dict[str, Any]

    @property
    def hotspot_id(self) -> str:
        """Stable identifier for citation in the evidence ledger."""
        return f"{self.source}:{self.acq_date}T{self.acq_time}:{self.latitude:.5f},{self.longitude:.5f}"

    def as_point(self) -> Point:
        return Point(self.longitude, self.latitude)


class FirmsClient:
    """Thin, honest client over the FIRMS area API."""

    def __init__(
        self,
        map_key: str | None = None,
        session: requests.Session | None = None,
        timeout: int = 30,
        polite_delay_s: float = 0.2,
    ) -> None:
        self.map_key = map_key or os.environ.get("FIRMS_MAP_KEY", "")
        if not self.map_key:
            raise FirmsError(
                "No FIRMS map key. Get one free at "
                "https://firms.modaps.eosdis.nasa.gov/api/map_key/ and set FIRMS_MAP_KEY."
            )
        self.session = session or requests.Session()
        self.timeout = timeout
        self.polite_delay_s = polite_delay_s

    # -- single request ---------------------------------------------------

    def fetch_area(
        self,
        bbox: Sequence[float],
        source: str = "VIIRS_SNPP_SP",
        day_range: int = MAX_DAY_RANGE,
        start_date: date | str | None = None,
    ) -> list[Hotspot]:
        """Fetch hotspots inside a bounding box.

        Args:
            bbox: ``(west, south, east, north)`` in WGS84 degrees -- the order the
                FIRMS API expects. Getting this order wrong returns an empty result
                rather than an error, which is a nasty way to lose an afternoon.
            source: One of :data:`SOURCES_NRT` or :data:`SOURCES_ARCHIVE`.
            day_range: 1..5. Values above 5 are rejected by the API.
            start_date: First day of the window (``YYYY-MM-DD``). Omit for most recent.
        """
        if not 1 <= day_range <= MAX_DAY_RANGE:
            raise ValueError(f"day_range must be 1..{MAX_DAY_RANGE} (FIRMS API limit), got {day_range}")
        if len(bbox) != 4:
            raise ValueError("bbox must be (west, south, east, north)")

        area = ",".join(str(round(float(v), 6)) for v in bbox)
        url = f"{FIRMS_BASE}/{self.map_key}/{source}/{area}/{day_range}"
        if start_date is not None:
            iso = start_date.isoformat() if isinstance(start_date, date) else str(start_date)
            url = f"{url}/{iso}"

        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code != 200:
            raise FirmsError(f"FIRMS returned HTTP {resp.status_code}: {resp.text[:200]}")

        body = resp.text.strip()
        # FIRMS signals quota and key problems in the response body, not the status code.
        if body.lower().startswith(("invalid", "error", "you have exceeded")):
            raise FirmsError(f"FIRMS rejected the request: {body[:200]}")

        return list(self._parse_csv(body, source))

    # -- windowed history -------------------------------------------------

    def fetch_history(
        self,
        bbox: Sequence[float],
        start: date,
        end: date,
        sources: Iterable[str] = ("VIIRS_SNPP_SP",),
    ) -> list[Hotspot]:
        """Walk a date range in 5-day windows and concatenate the results.

        Expect this to be slow and transaction-hungry. Run it once, write the output
        to ``data/cache/``, and read from cache thereafter.
        """
        if start > end:
            raise ValueError("start must be on or before end")

        out: list[Hotspot] = []
        for source in sources:
            cursor = start
            while cursor <= end:
                window = min(MAX_DAY_RANGE, (end - cursor).days + 1)
                out.extend(self.fetch_area(bbox, source=source, day_range=window, start_date=cursor))
                cursor += timedelta(days=window)
                if self.polite_delay_s:
                    time.sleep(self.polite_delay_s)
        return out

    # -- parsing ----------------------------------------------------------

    @staticmethod
    def _parse_csv(body: str, source: str) -> Iterable[Hotspot]:
        reader = csv.DictReader(io.StringIO(body))
        for row in reader:
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                continue  # header-only or malformed response
            frp_raw = row.get("frp")
            try:
                frp = float(frp_raw) if frp_raw not in (None, "") else None
            except ValueError:
                frp = None
            yield Hotspot(
                latitude=lat,
                longitude=lon,
                acq_date=row.get("acq_date", ""),
                acq_time=row.get("acq_time", ""),
                confidence=str(row.get("confidence", "")),
                satellite=row.get("satellite", ""),
                instrument=row.get("instrument", ""),
                frp=frp,
                source=source,
                raw=dict(row),
            )


# -- geometry filtering ---------------------------------------------------


def within(geom: BaseGeometry, hotspots: Iterable[Hotspot]) -> list[Hotspot]:
    """Keep only hotspots whose centre falls inside the geometry.

    A hotspot is a satellite pixel centre, not a point fire: VIIRS pixels are
    ~375 m across. Treat boundary hits as ambiguous rather than conclusive --
    that ambiguity is precisely what the orchestrator should escalate on.
    """
    return [h for h in hotspots if geom.contains(h.as_point())]


def outside(geom: BaseGeometry, hotspots: Iterable[Hotspot]) -> list[Hotspot]:
    return [h for h in hotspots if not geom.contains(h.as_point())]


def summarise(hotspots: Sequence[Hotspot]) -> dict[str, Any]:
    """Aggregate hotspots into the shape the scoring rubric consumes."""
    by_year: dict[str, int] = {}
    by_month: dict[str, int] = {}
    for h in hotspots:
        if len(h.acq_date) >= 7:
            by_year[h.acq_date[:4]] = by_year.get(h.acq_date[:4], 0) + 1
            by_month[h.acq_date[:7]] = by_month.get(h.acq_date[:7], 0) + 1

    peak_month = max(by_month.items(), key=lambda kv: kv[1]) if by_month else None
    high_conf = [h for h in hotspots if str(h.confidence).lower() in ("h", "high") or _conf_num(h) >= 80]

    return {
        "total": len(hotspots),
        "high_confidence": len(high_conf),
        "by_year": dict(sorted(by_year.items())),
        "peak_month": {"month": peak_month[0], "count": peak_month[1]} if peak_month else None,
        "hotspot_ids": [h.hotspot_id for h in hotspots[:200]],  # cap the artifact size
    }


def _conf_num(h: Hotspot) -> float:
    try:
        return float(h.confidence)
    except (TypeError, ValueError):
        return 0.0
