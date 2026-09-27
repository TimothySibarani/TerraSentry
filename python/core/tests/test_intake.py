"""Intake validation: untrusted plot submissions become agent-ready records."""

from __future__ import annotations

from typing import Any

import agent_helpers
import pytest
from shapely.geometry import shape
from terrasentry_core.intake import (
    DECLARED_DISCLOSURE,
    IntakeError,
    RecordSubmission,
    build_submitted_record,
    geodesic_area_ha,
    validate_geometry,
)

# ~0.02 deg square near the equator in Riau: about 494 ha.
SQUARE: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[101.0, 0.5], [101.02, 0.5], [101.02, 0.52], [101.0, 0.52], [101.0, 0.5]]],
}


def submission(**plot: Any) -> RecordSubmission:
    return RecordSubmission.model_validate(
        {
            "plot": {"geometry": SQUARE, "label": "Blok A", "province": "Riau", "kabupaten": "Siak", **plot},
            "supplier": {"legal_name": "PT Contoh Sawit"},
            "legality": {"permit_type": "hgu", "permit_number": "12/HGU/BPN/2019"},
            "consignment": {
                "commodity": "oil_palm",
                "description": "Crude palm oil",
                "net_weight_kg": 25000,
                "harvest_year": 2026,
            },
        }
    )


def test_valid_polygon_builds_an_unlabelled_declared_record() -> None:
    record, report = build_submitted_record(submission())
    assert 480 < report.area_ha < 510
    assert record.polygon.area_ha == report.area_ha
    assert record.expected_archetype is None and record.polygon.archetype is None
    assert record.legality.hgu_number == "12/HGU/BPN/2019"
    assert record.legality.synthetic is False
    assert record.legality.provenance == "supplier_declared"
    assert record.legality.disclosure == DECLARED_DISCLOSURE
    assert record.consignment.hs_heading == "1511"
    assert record.record_id.startswith("REC-U-")
    assert record.polygon.region == "Siak, Riau"


def test_feature_wrapper_is_unwrapped() -> None:
    report = validate_geometry({"type": "Feature", "properties": {}, "geometry": SQUARE})
    assert report.geometry_type == "Polygon"


def test_point_with_small_declared_area_is_buffered_for_queries() -> None:
    report = validate_geometry({"type": "Point", "coordinates": [101.0, 0.5]}, declared_area_ha=3.5)
    assert report.geometry_type == "Point"
    assert report.area_ha == 3.5
    buffered = geodesic_area_ha(shape(report.query_geometry))  # type: ignore[arg-type]
    assert buffered == pytest.approx(3.5, rel=0.02)


@pytest.mark.parametrize(
    ("geometry", "area", "field", "fragment"),
    [
        (
            {"type": "Point", "coordinates": [101.0, 0.5]},
            6.0,
            "plot.declared_area_ha",
            "must be described by a polygon",
        ),
        ({"type": "Point", "coordinates": [101.0, 0.5]}, None, "plot.declared_area_ha", "declared area"),
        (
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]},
            None,
            "plot.geometry",
            "Self-intersection",
        ),
        (
            {"type": "Polygon", "coordinates": [[[100, 0], [101, 0], [101, 1], [100, 1], [100, 0]]]},
            None,
            "plot.geometry",
            "exceeds",
        ),
        (
            {"type": "Polygon", "coordinates": [[[200, 0], [201, 0], [201, 1], [200, 0]]]},
            None,
            "plot.geometry",
            "WGS84",
        ),
        ({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, None, "plot.geometry", "unsupported"),
        ({"type": "Polygon"}, None, "plot.geometry", "not a GeoJSON"),
    ],
)
def test_invalid_geometry_is_rejected_with_a_reason(
    geometry: dict[str, Any], area: float | None, field: str, fragment: str
) -> None:
    with pytest.raises(IntakeError) as caught:
        validate_geometry(geometry, declared_area_ha=area)
    assert caught.value.field == field
    assert fragment in caught.value.message


def test_too_many_vertices_is_rejected() -> None:
    import math

    ring = [[101 + 0.01 * math.cos(i / 1000), 0.5 + 0.01 * math.sin(i / 1000)] for i in range(6283)]
    ring.append(ring[0])
    with pytest.raises(IntakeError, match="vertices"):
        validate_geometry({"type": "Polygon", "coordinates": [ring]})


def test_declared_permit_needs_a_number() -> None:
    bad = submission()
    bad.legality.permit_number = " "
    with pytest.raises(IntakeError) as caught:
        build_submitted_record(bad)
    assert caught.value.field == "legality.permit_number"


def test_registered_record_resolves_without_touching_the_seed_batch() -> None:
    datasets = agent_helpers.datasets()
    record, _ = build_submitted_record(submission())
    before = len(datasets.records)
    datasets.register(record)
    assert datasets.get_record(record.record_id) is record
    assert datasets.record_for_polygon(record.polygon.id) is record
    assert datasets.record_for_supplier(record.supplier_id) is record
    assert len(datasets.records) == before
    disclosures = datasets.disclosures_for(record)
    assert DECLARED_DISCLOSURE in disclosures
    assert datasets.batch.disclosure not in disclosures
