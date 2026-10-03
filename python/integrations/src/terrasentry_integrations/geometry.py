"""Shared WGS84 measurements for submitted plots and clipped source features."""

from itertools import pairwise

from pyproj import Geod
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient

_GEOD = Geod(ellps="WGS84")


def geodesic_area_ha(geometry: BaseGeometry) -> float:
    """Measure each polygon independently; holes subtract regardless of winding."""
    if isinstance(geometry, Polygon):
        area, _ = _GEOD.geometry_area_perimeter(orient(geometry, sign=1.0))
        return abs(area) / 10_000.0
    if isinstance(geometry, MultiPolygon | GeometryCollection):
        return sum((geodesic_area_ha(part) for part in geometry.geoms), 0.0)
    return 0.0


def has_polygon_holes(geometry: BaseGeometry) -> bool:
    if isinstance(geometry, Polygon):
        return bool(geometry.interiors)
    if isinstance(geometry, MultiPolygon | GeometryCollection):
        return any(has_polygon_holes(part) for part in geometry.geoms)
    return False


def crosses_antimeridian(geometry: BaseGeometry) -> bool:
    """Unsplit longitude jumps have incompatible geodesic and planar meanings."""
    if isinstance(geometry, Polygon):
        return any(
            abs(end[0] - start[0]) > 180
            for ring in (geometry.exterior, *geometry.interiors)
            for start, end in pairwise(ring.coords)
        )
    if isinstance(geometry, MultiPolygon | GeometryCollection):
        return any(crosses_antimeridian(part) for part in geometry.geoms)
    return False
