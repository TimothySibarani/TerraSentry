import re

from shapely.geometry import shape
from terrasentry_core.seed.generator import (
    BATCH_DISTRIBUTION,
    demo_dataset,
    generate_batch,
    legality_dataset,
)


def test_batch_distribution_and_size() -> None:
    batch = generate_batch()
    assert batch.distribution == BATCH_DISTRIBUTION
    assert len(batch.records) == 50
    assert sum(batch.distribution.values()) == 50


def test_batch_is_deterministic() -> None:
    first = generate_batch(rng_seed=42)
    second = generate_batch(rng_seed=42)
    assert first.model_dump() == second.model_dump()


def test_demo_subset_contains_both_live_scenarios() -> None:
    demo = demo_dataset(generate_batch())
    assert len(demo.polygons) == 8
    assert all(polygon.is_demo for polygon in demo.polygons)
    scenarios = {polygon.scenario for polygon in demo.polygons if polygon.scenario}
    assert scenarios == {"compliant_live", "high_risk_live"}


def test_polygons_are_valid_and_on_land() -> None:
    for record in generate_batch().records:
        geometry = shape(record.polygon.geometry)
        assert geometry.is_valid
        assert geometry.area > 0
        assert 0 < record.polygon.area_ha < 10_000
        assert 95.0 <= record.polygon.centroid_lon <= 141.0
        assert -11.0 <= record.polygon.centroid_lat <= 6.0


def test_legality_records_are_labelled_synthetic() -> None:
    legality = legality_dataset(generate_batch())
    assert len(legality.records) == 50
    for record in legality.records:
        assert record.synthetic is True
        assert "SYNTH-" in record.trading_name
        assert len(record.nib) == 13
        assert re.fullmatch(r"\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3}", record.npwp)
        assert record.disclosure.startswith("SYNTHETIC")
        assert record.beneficial_owners
