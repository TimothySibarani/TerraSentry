"""Geometry tool: polygon validation, geodesic area, and the EUDR Article 9 rule.

This gates everything downstream. If the polygon is wrong, every later finding is
wrong with it -- so validation here is strict and failures are loud.

All geometry is assumed to be WGS84 (EPSG:4326), lon/lat order, which is what
GeoJSON mandates and what EUDR submissions expect.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pyproj import Geod
from shapely.geometry import shape, mapping
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

# WGS84 ellipsoid -- geodesic area, no projection choice to get wrong.
_GEOD = Geod(ellps="WGS84")

# EUDR Art. 9: plots of 4 ha and above require a polygon; below that a GPS point suffices.
EUDR_POLYGON_THRESHOLD_HA = 4.0

GeolocationRequirement = Literal["polygon", "point"]


@dataclass
class GeometryReport:
    """Result of validating a supplier-supplied geometry."""

    valid: bool
    area_ha: float
    perimeter_km: float
    geolocation_requirement: GeolocationRequirement
    bbox: tuple[float, float, float, float]  # west, south, east, north
    problems: list[str]
    centroid: tuple[float, float]  # lon, lat

    @property
    def blocking(self) -> bool:
        """True when the geometry cannot be used for a due diligence statement."""
        return not self.valid

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "area_ha": round(self.area_ha, 3),
            "perimeter_km": round(self.perimeter_km, 3),
            "geolocation_requirement": self.geolocation_requirement,
            "bbox": [round(v, 6) for v in self.bbox],
            "centroid": [round(v, 6) for v in self.centroid],
            "problems": self.problems,
        }


def load_geojson(path: str | Path) -> BaseGeometry:
    """Load a GeoJSON file into a shapely geometry.

    Accepts a bare geometry, a Feature, or a FeatureCollection (first feature).
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return geometry_from_geojson(raw)


def geometry_from_geojson(raw: dict[str, Any]) -> BaseGeometry:
    kind = raw.get("type")
    if kind == "FeatureCollection":
        features = raw.get("features") or []
        if not features:
            raise ValueError("FeatureCollection contains no features")
        return shape(features[0]["geometry"])
    if kind == "Feature":
        return shape(raw["geometry"])
    return shape(raw)


def area_hectares(geom: BaseGeometry) -> float:
    """Geodesic area in hectares.

    Uses pyproj's geodesic computation rather than a projected CRS, which avoids
    picking the wrong UTM zone for concessions that straddle a zone boundary --
    a real problem in Kalimantan and Sumatra.
    """
    area_m2, _ = _GEOD.geometry_area_perimeter(geom)
    return abs(area_m2) / 10_000.0


def perimeter_km(geom: BaseGeometry) -> float:
    _, perim_m = _GEOD.geometry_area_perimeter(geom)
    return abs(perim_m) / 1_000.0


def geolocation_requirement(area_ha: float) -> GeolocationRequirement:
    """EUDR Art. 9: >= 4 ha needs a polygon, below that a point is acceptable."""
    return "polygon" if area_ha >= EUDR_POLYGON_THRESHOLD_HA else "point"


def validate(geom: BaseGeometry) -> GeometryReport:
    """Validate a geometry for EUDR use and report every problem found.

    Problems are collected rather than raised so the agent can decide what to do:
    a self-intersection may be repairable, coordinates outside Indonesia are more
    likely a lon/lat swap that a human should confirm.
    """
    problems: list[str] = []

    if geom.is_empty:
        problems.append("geometry is empty")

    if not geom.is_valid:
        problems.append(f"invalid geometry: {explain_validity(geom)}")

    if geom.geom_type not in ("Polygon", "MultiPolygon", "Point"):
        problems.append(f"unsupported geometry type for EUDR: {geom.geom_type}")

    west, south, east, north = geom.bounds if not geom.is_empty else (0.0, 0.0, 0.0, 0.0)

    if not (-180.0 <= west <= 180.0 and -180.0 <= east <= 180.0):
        problems.append("longitude out of range -- coordinates may be swapped (GeoJSON is lon,lat)")
    if not (-90.0 <= south <= 90.0 and -90.0 <= north <= 90.0):
        problems.append("latitude out of range -- coordinates may be swapped (GeoJSON is lon,lat)")

    area = area_hectares(geom) if geom.geom_type != "Point" and not geom.is_empty else 0.0

    if geom.geom_type != "Point" and area == 0.0:
        problems.append("polygon has zero area")

    # Sanity band for Indonesian concessions. Not a hard failure -- a smallholder
    # plot can legitimately be under a hectare -- but worth surfacing to a human.
    if 0.0 < area < 0.1:
        problems.append(f"suspiciously small area ({area:.4f} ha) -- verify units and coordinate order")
    if area > 500_000.0:
        problems.append(f"implausibly large area ({area:,.0f} ha) -- verify the geometry")

    centroid = (geom.centroid.x, geom.centroid.y) if not geom.is_empty else (0.0, 0.0)

    return GeometryReport(
        valid=not problems,
        area_ha=area,
        perimeter_km=perimeter_km(geom) if not geom.is_empty else 0.0,
        geolocation_requirement=geolocation_requirement(area),
        bbox=(west, south, east, north),
        problems=problems,
        centroid=centroid,
    )


def buffer_bbox(
    bbox: tuple[float, float, float, float], km: float
) -> tuple[float, float, float, float]:
    """Expand a bbox by roughly `km` in every direction.

    Used to search for hotspots just outside a concession boundary -- fires that
    start next door and burn in are exactly the ambiguous case worth investigating.

    Approximation: 1 degree latitude ~ 111 km; longitude is scaled by cos(latitude).
    Good enough for a search envelope, never use it for area.
    """
    from math import cos, radians

    west, south, east, north = bbox
    mid_lat = (south + north) / 2.0
    d_lat = km / 111.0
    d_lon = km / max(111.0 * cos(radians(mid_lat)), 1e-6)
    return (
        max(west - d_lon, -180.0),
        max(south - d_lat, -90.0),
        min(east + d_lon, 180.0),
        min(north + d_lat, 90.0),
    )


def to_geojson_feature(geom: BaseGeometry, properties: dict[str, Any] | None = None) -> dict:
    """Wrap a geometry as a GeoJSON Feature, the shape EUDR submissions expect."""
    return {
        "type": "Feature",
        "geometry": mapping(geom),
        "properties": properties or {},
    }
