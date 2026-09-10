"""Geometry is the gate: if area or the Article 9 rule is wrong, every finding is wrong."""

import pytest
from shapely.geometry import Polygon

from terrasentry.tools import geometry as geo


def test_demo_polygon_area_is_about_4200_ha():
    g = geo.load_geojson("data/polygons/SUP-001.geojson")
    area = geo.area_hectares(g)
    # Geodesic area of the bundled demo concession, +/- 1%.
    assert 4150 < area < 4250, f"unexpected area: {area}"


def test_article_9_threshold():
    assert geo.geolocation_requirement(4.0) == "polygon"
    assert geo.geolocation_requirement(4.1) == "polygon"
    assert geo.geolocation_requirement(3.99) == "point"


def test_validate_accepts_demo_polygon():
    g = geo.load_geojson("data/polygons/SUP-001.geojson")
    report = geo.validate(g)
    assert report.valid, report.problems
    assert report.geolocation_requirement == "polygon"
    assert not report.blocking


def test_validate_flags_self_intersection():
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    report = geo.validate(bowtie)
    assert not report.valid
    assert any("invalid geometry" in p for p in report.problems)


def test_swapped_coordinates_are_flagged():
    # Latitude placed in the longitude slot: 110 is a valid longitude but not a latitude.
    swapped = Polygon([(-0.15, 110.55), (-0.15, 110.60), (-0.20, 110.60), (-0.20, 110.55)])
    report = geo.validate(swapped)
    assert not report.valid
    assert any("out of range" in p for p in report.problems)


def test_buffer_bbox_expands_in_both_axes():
    bbox = (110.55, -0.21, 110.61, -0.15)
    west, south, east, north = geo.buffer_bbox(bbox, km=2)
    assert west < bbox[0] and south < bbox[1]
    assert east > bbox[2] and north > bbox[3]
