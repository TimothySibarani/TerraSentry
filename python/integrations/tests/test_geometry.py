import pytest
from pyproj import Geod
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon
from terrasentry_integrations.geometry import geodesic_area_ha


def test_components_do_not_cancel_and_holes_subtract() -> None:
    ring = [(101, 0.5), (101.02, 0.5), (101.02, 0.52), (101, 0.52), (101, 0.5)]
    hole = [(101.005, 0.505), (101.015, 0.505), (101.015, 0.515), (101.005, 0.515), (101.005, 0.505)]
    other = [(x + 0.03, y) for x, y in reversed(ring)]
    geod = Geod(ellps="WGS84")
    outer_area = abs(geod.polygon_area_perimeter([p[0] for p in ring], [p[1] for p in ring])[0]) / 10000
    hole_area = abs(geod.polygon_area_perimeter([p[0] for p in hole], [p[1] for p in hole])[0]) / 10000
    assert geodesic_area_ha(Polygon(ring, [hole])) == pytest.approx(outer_area - hole_area)
    assert geodesic_area_ha(Polygon(list(reversed(ring)), [list(reversed(hole))])) == pytest.approx(
        outer_area - hole_area
    )
    assert geodesic_area_ha(MultiPolygon([Polygon(ring), Polygon(other)])) == pytest.approx(outer_area * 2)
    assert geodesic_area_ha(GeometryCollection([Polygon(ring), LineString(ring)])) == pytest.approx(
        outer_area
    )
    assert geodesic_area_ha(GeometryCollection()) == 0
