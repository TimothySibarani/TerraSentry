import json
import re
from pathlib import Path

from shapely.geometry import shape
from terrasentry_core.seed import generate_batch, operator_dataset
from terrasentry_core.seed.generator import BATCH_DISTRIBUTION, demo_dataset, legality_dataset

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_batch_distribution_and_size() -> None:
    batch = generate_batch()
    assert batch.distribution == BATCH_DISTRIBUTION
    assert len(batch.records) == 50
    assert sum(batch.distribution.values()) == 50


def test_batch_is_deterministic() -> None:
    first = generate_batch(rng_seed=42)
    second = generate_batch(rng_seed=42)
    assert first.model_dump() == second.model_dump()


def test_committed_seed_files_match_the_generator() -> None:
    batch = generate_batch()
    seed_dir = REPO_ROOT / "data/seed"
    committed = {
        "batch_50.json": batch,
        "demo_polygons.json": demo_dataset(batch),
        "legality.json": legality_dataset(batch),
        "operator.json": operator_dataset(batch),
    }
    for filename, model in committed.items():
        payload = json.loads((seed_dir / filename).read_text(encoding="utf-8"))
        assert payload == model.model_dump(mode="json"), f"{filename} is out of sync"


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


def test_consignments_follow_real_hs_structure_and_are_synthetic() -> None:
    for record in generate_batch().records:
        consignment = record.consignment
        assert consignment.synthetic is True
        assert consignment.disclosure.startswith("SYNTHETIC")
        assert re.fullmatch(r"[0-9]{2,6}", consignment.hs_heading)
        assert consignment.net_weight_kg > 0
        assert 2023 <= consignment.harvest_year <= 2025
        assert "(SYNTH)" in consignment.production_place
        if consignment.commodity == "oil_palm":
            assert consignment.hs_heading == "1511"
            assert consignment.supplementary_unit is None
        else:
            assert consignment.hs_heading == "4703"
            assert consignment.supplementary_unit is not None
            assert consignment.supplementary_unit_qualifier == "MTQ"


def test_expected_signal_coverage_exercises_all_detection_paths() -> None:
    batch = generate_batch()
    signals = [record.expected_signal for record in batch.records if record.expected_signal]
    assert signals.count("deforestation") == 4
    assert signals.count("fire") == 4
    assert signals.count("legal") == 4
    ambiguities = [record.expected_ambiguity for record in batch.records if record.expected_ambiguity]
    assert ambiguities.count("borderline_area") == 3
    assert ambiguities.count("old_fire_scar") == 3
    assert ambiguities.count("permit_gap") == 2
    for record in batch.records:
        if record.expected_ambiguity == "permit_gap":
            assert record.legality.permit_status == "active"
            assert record.legality.hgu_number is None
            assert record.legality.pbp_number is None


def test_operator_dataset_is_synthetic_and_complete() -> None:
    operator = operator_dataset(generate_batch()).operator
    assert operator.synthetic is True
    assert "SYNTH" in operator.legal_name
    assert operator.identifier_type == "eori"
    assert operator.activity_type == "IMPORT"
    assert operator.country == "NL"
    assert "@" in operator.email
