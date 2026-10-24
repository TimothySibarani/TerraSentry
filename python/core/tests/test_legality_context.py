"""Slice 2 rule boundaries, provenance and full-cutoff verification."""

from __future__ import annotations

from datetime import date

import pytest
from conftest import clear_layers, make_consignment, make_input, make_loss, make_supplier
from terrasentry_core.domain.enums import FindingCode, FindingLevel, Verdict
from terrasentry_core.evidence import EvidenceEntry, build_source_ledger
from terrasentry_core.scoring import assess
from terrasentry_integrations.sources.gfw_layers import LayerFeature


@pytest.mark.parametrize(
    ("name", "area", "level", "points", "verdict"),
    [
        ("protected_areas", 0.0000001, "flag", 60, "high_risk"),
        ("moratorium", 0.1, "borderline", 20, "ambiguous"),
        ("moratorium", 0.10000001, "flag", 60, "high_risk"),
        ("peatlands", 0.0000001, "borderline", 10, "ambiguous"),
        ("forest_baseline", 100, "clear", 0, "compliant"),
    ],
)
def test_overlap_boundaries(name: str, area: float, level: str, points: int, verdict: str) -> None:
    input = make_input()
    input.layers = clear_layers()
    layer = next(layer for layer in input.layers.layers if layer.name == name)
    layer.overlap_ha = area
    if name == "protected_areas":
        layer.features = [
            LayerFeature(
                feature_id="1",
                overlap_ha=area,
                properties={"name": "Named reserve"},
                geometry=input.parcel.geometry,
            )
        ]
    result = assess(input, build_source_ledger(input))
    finding = next(finding for finding in result.findings if finding.metrics.get("dataset") == layer.dataset)
    assert finding.level == level and finding.points == points
    assert result.verdict == verdict  # certification never clears a critical legality flag
    assert finding.evidence_ids
    if name == "protected_areas":
        assert "Named reserve" in finding.detail


@pytest.mark.parametrize(
    ("expiry", "verdict"),
    [(date(2026, 10, 1), "high_risk"), (date(2026, 10, 2), "compliant"), (date(2026, 10, 3), "compliant")],
)
def test_permit_expiry_is_relative_to_the_accepted_date(expiry: date, verdict: str) -> None:
    input = make_input(supplier=make_supplier(permit_expiry=expiry))
    input.assessment_date = date(2026, 10, 2)
    assert assess(input, build_source_ledger(input)).verdict == verdict


def test_missing_permit_missing_layer_and_non_indonesian_checks() -> None:
    input = make_input(supplier=make_supplier(permit_status="none", hgu_number=None, pbp_number=None))
    result = assess(input, build_source_ledger(input))
    assert result.verdict is Verdict.AMBIGUOUS
    assert result.findings[0].level is FindingLevel.BORDERLINE
    input.parcel.country = "BR"
    assert assess(input, build_source_ledger(input)).findings[0].level is FindingLevel.CLEAR
    input.layers = None
    result = assess(input, build_source_ledger(input))
    assert result.verdict is Verdict.AMBIGUOUS and "gfw:protected_areas:unavailable" in result.data_gaps


def test_concession_holder_uses_normalized_names_and_strongest_conflict_once() -> None:
    input = make_input(supplier=make_supplier(legal_name="PT Test, Ltd."))
    assert input.layers is not None
    layer = next(layer for layer in input.layers.layers if layer.name == "oil_palm_concessions")
    layer.overlap_ha = 5
    layer.features = [
        LayerFeature(
            feature_id="1",
            overlap_ha=5,
            properties={"company": "pt test ltd"},
            geometry=input.parcel.geometry,
        )
    ]
    result = assess(input, build_source_ledger(input))
    assert result.verdict is Verdict.COMPLIANT
    layer.features[0].properties["company"] = "Another company"
    result = assess(input, build_source_ledger(input))
    conflicts = [finding for finding in result.findings if finding.code is FindingCode.CONCESSION_CONFLICT]
    assert len(conflicts) == 1 and conflicts[0].points == 60
    assert result.verdict is Verdict.HIGH_RISK
    layer.features[0].properties["company"] = None
    assert assess(input, build_source_ledger(input)).verdict is Verdict.AMBIGUOUS


def test_evidence_provenance_is_specific_and_part_of_the_hash() -> None:
    input = make_input()
    input.parcel.provenance = "supplier_declared"
    ledger = build_source_ledger(input)
    assert ledger.by_claim("parcel.geometry")[0].provenance == "supplier_declared"
    assert ledger.by_claim("parcel.area_ha")[0].provenance == "derived"
    assert ledger.by_claim("loss.total_loss_ha")[0].provenance == "real_source"
    original = ledger.by_claim("parcel.geometry")[0]
    input.parcel.provenance = "synthetic"
    assert build_source_ledger(input).by_claim("parcel.geometry")[0].evidence_id != original.evidence_id
    legacy = original.model_dump(exclude={"provenance"})
    assert EvidenceEntry.model_validate(legacy).provenance == "legacy_unknown"


def test_point_declarations_are_distinct_from_the_derived_query_buffer() -> None:
    input = make_input()
    input.parcel.provenance = "supplier_declared"
    input.parcel.input_geometry = {"type": "Point", "coordinates": [101.01, 0.01]}
    input.parcel.area_ha = 3
    ledger = build_source_ledger(input)
    assert ledger.by_claim("parcel.geometry")[0].value == input.parcel.input_geometry
    assert ledger.by_claim("parcel.area_ha")[0].provenance == "supplier_declared"
    assert ledger.by_claim("parcel.query_geometry")[0].value == input.parcel.geometry
    assert ledger.by_claim("parcel.query_geometry")[0].provenance == "derived"


def test_unavailable_required_peat_layer_cannot_be_treated_as_clean_zero() -> None:
    input = make_input()
    assert input.layers is not None
    peat = next(layer for layer in input.layers.layers if layer.name == "peatlands")
    peat.status, peat.error = "unavailable", "invalid raster area type"
    result = assess(input, build_source_ledger(input))
    assert result.verdict is Verdict.AMBIGUOUS
    assert "gfw:peatlands:unavailable" in result.data_gaps


def _wood_plot(*, commodity: str = "wood", overlap: float = 500.0, company: str = "PT Uji Lestari Nusantara"):
    """A 500 ha plot with flagged loss, optionally inside a wood-fibre concession."""
    input = make_input(
        supplier=make_supplier(certifications=[]),
        loss=make_loss(total_ha=20.0),
        consignment=make_consignment(commodity=commodity, hs_heading="4703"),
    )
    assert input.layers is not None
    layer = next(layer for layer in input.layers.layers if layer.name == "wood_fiber_concessions")
    layer.overlap_ha = overlap
    layer.features = [
        LayerFeature(
            feature_id="1",
            overlap_ha=overlap,
            properties={"company": company},
            geometry=input.parcel.geometry,
        )
    ]
    return input


def _loss_finding(input):
    result = assess(input, build_source_ledger(input))
    finding = next(item for item in result.findings if item.code is FindingCode.DEFORESTATION_LOSS)
    return result, finding


def test_loss_inside_the_suppliers_own_fibre_concession_goes_to_a_person() -> None:
    result, finding = _loss_finding(_wood_plot())

    assert finding.level is FindingLevel.BORDERLINE and finding.points == 15
    assert finding.metrics["harvest_candidate"] == 1
    assert "possible plantation harvest, needs review" in finding.detail
    assert "not located within the plot" in finding.detail
    assert result.verdict is Verdict.AMBIGUOUS


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"company": "PT Someone Else"}, "holder differs from the declared holder"),
        ({"commodity": "oil_palm"}, "only a wood consignment can be a fibre harvest"),
        ({"overlap": 400.0}, "80% of the plot is below the 90% overlap needed"),
    ],
)
def test_loss_that_is_not_a_plausible_harvest_still_flags(kwargs: dict, why: str) -> None:
    result, finding = _loss_finding(_wood_plot(**kwargs))

    assert finding.level is FindingLevel.FLAG, why
    assert "harvest_candidate" not in finding.metrics
    assert result.verdict is Verdict.HIGH_RISK


def test_the_harvest_rule_never_touches_loss_below_the_flag_threshold() -> None:
    input = _wood_plot()
    input.loss = make_loss(total_ha=1.0)  # 0.2% of the plot: already only borderline

    _, finding = _loss_finding(input)

    assert finding.level is FindingLevel.BORDERLINE
    assert "harvest_candidate" not in finding.metrics
