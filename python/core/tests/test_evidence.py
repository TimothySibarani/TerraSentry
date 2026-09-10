from __future__ import annotations

from typing import Any

import pytest
from conftest import FIXED_TIME, make_input
from terrasentry_core.domain.enums import EvidenceSource
from terrasentry_core.errors import LedgerLookupError
from terrasentry_core.evidence import EvidenceLedger, build_source_ledger


def test_record_is_deterministic_and_idempotent() -> None:
    first = EvidenceLedger()
    second = EvidenceLedger()
    entry_one = first.record(claim="parcel.area_ha", value=10.0, source=EvidenceSource.CONCESSION)
    entry_two = first.record(claim="parcel.area_ha", value=10.0, source=EvidenceSource.CONCESSION)
    assert entry_one.evidence_id == entry_two.evidence_id
    assert len(first.entries) == 1

    repeated = second.record(claim="parcel.area_ha", value=10.0, source=EvidenceSource.CONCESSION)
    assert repeated.evidence_id == entry_one.evidence_id


def test_artifact_changes_the_evidence_id() -> None:
    ledger = EvidenceLedger()
    one = ledger.record(
        claim="parcel.area_ha", value=10.0, source=EvidenceSource.CONCESSION, artifact={"polygon": "A"}
    )
    two = ledger.record(
        claim="parcel.area_ha", value=10.0, source=EvidenceSource.CONCESSION, artifact={"polygon": "B"}
    )
    assert one.evidence_id != two.evidence_id


def test_get_and_verify_fail_on_unknown_ids() -> None:
    ledger = EvidenceLedger()
    with pytest.raises(LedgerLookupError):
        ledger.get("EV-missing")
    with pytest.raises(LedgerLookupError):
        ledger.verify({"claim": ["EV-missing"]})


def test_ledger_orders_entries_by_id() -> None:
    ledger = EvidenceLedger()
    ledger.record(claim="b", value=2, source=EvidenceSource.RUBRIC)
    ledger.record(claim="a", value=1, source=EvidenceSource.RUBRIC)
    ids = [entry.evidence_id for entry in ledger.entries]
    assert ids == sorted(ids)


def test_build_source_ledger_records_every_source_claim() -> None:
    input = make_input()
    ledger = build_source_ledger(input, retrieved_at=FIXED_TIME)
    claims = {entry.claim for entry in ledger.entries}
    assert {
        "parcel.geometry",
        "parcel.area_ha",
        "parcel.centroid",
        "parcel.country",
        "loss.total_loss_ha",
        "loss.by_year",
        "hotspots.detection_count",
        "hotspots.total_frp",
        "hotspots.detections",
        "supplier.identifiers",
        "supplier.name",
        "supplier.permit_status",
        "supplier.concession_area_ha",
        "supplier.hgu_pbp",
        "supplier.sanctions",
        "supplier.certifications",
        "supplier.beneficial_owners",
        "consignment.description",
        "consignment.hs_heading",
        "consignment.net_weight_kg",
        "consignment.measure",
        "consignment.species",
        "consignment.production_place",
        "consignment.harvest_year",
        "operator.name",
        "operator.identifier",
        "operator.address",
        "operator.activity",
    } <= claims


def test_source_entries_use_real_timestamps_and_label_synthetic_data() -> None:
    ledger = build_source_ledger(make_input(), retrieved_at=FIXED_TIME)
    loss_entry = ledger.by_claim("loss.total_loss_ha")[0]
    assert loss_entry.retrieved_at == FIXED_TIME
    legality_entry = ledger.by_claim("supplier.permit_status")[0]
    assert legality_entry.synthetic is True
    assert legality_entry.disclosure is not None


def test_ledger_snapshot_is_json_serializable() -> None:
    snapshot: list[dict[str, Any]] = build_source_ledger(make_input()).snapshot()
    assert snapshot and all("evidence_id" in entry for entry in snapshot)
