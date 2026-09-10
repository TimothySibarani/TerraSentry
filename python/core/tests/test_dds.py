from __future__ import annotations

import base64
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from conftest import (
    FIXED_TIME,
    make_consignment,
    make_hotspots,
    make_input,
    make_loss,
    make_operator,
    make_parcel,
    make_supplier,
)
from terrasentry_core.dds import (
    COMMON_NAMESPACE,
    DDS_NAMESPACE,
    DDS_SCHEMA_VERSION,
    REQUIRED_DDS_CLAIMS,
    SOAP_NAMESPACE,
    DdsDocument,
    build_dds,
    validate_citations,
)
from terrasentry_core.domain.models import Assessment, AssessmentInput
from terrasentry_core.errors import (
    InvalidGeometryError,
    LedgerLookupError,
    MissingAssessmentInputError,
    UncitedClaimError,
)
from terrasentry_core.evidence import EvidenceLedger, build_source_ledger
from terrasentry_core.scoring import assess

FIXTURES = Path(__file__).parent / "fixtures"


def build_document(
    assessment_input: AssessmentInput,
) -> tuple[DdsDocument, Assessment, EvidenceLedger]:
    ledger = build_source_ledger(assessment_input, retrieved_at=FIXED_TIME)
    assessment = assess(assessment_input, ledger)
    document = build_dds(assessment_input, assessment, ledger)
    validate_citations(document, ledger)
    return document, assessment, ledger


def decode_geojson(document: DdsDocument) -> dict:
    encoded = document.statement.commodities[0].producers[0].geometry_geojson
    return json.loads(base64.b64decode(encoded).decode("utf-8"))


def test_document_reflects_supplier_consignment_and_operator() -> None:
    document, assessment, _ = build_document(make_input(record_id="REC-042"))
    statement = document.statement
    assert document.schema_version == DDS_SCHEMA_VERSION
    assert document.operator_role == "OPERATOR"
    assert statement.internal_reference_number == "TS-SUP-TEST-REC-042"
    assert statement.activity_type == "IMPORT"
    assert statement.country_of_activity == "NL"
    assert statement.border_cross_country == "NL"
    assert statement.geo_location_confidential is False
    commodity = statement.commodities[0]
    assert commodity.hs_heading == "1511"
    assert commodity.descriptors.description_of_goods == "Crude palm oil (synthetic consignment)"
    assert commodity.descriptors.goods_measure.net_weight == 4_500_000.0
    assert commodity.species_info is not None
    assert commodity.species_info.scientific_name == "Elaeis guineensis"
    producer = commodity.producers[0]
    assert producer.country == "ID"
    assert producer.name == "PT Uji Lestari Nusantara"
    assert document.assessment.verdict == str(assessment.verdict)
    assert document.synthetic is True
    assert document.disclosures


def test_json_uses_camel_case_and_carries_the_extension() -> None:
    document, _, _ = build_document(make_input())
    payload = json.loads(document.to_json())
    assert payload["schemaVersion"] == DDS_SCHEMA_VERSION
    assert payload["operatorRole"] == "OPERATOR"
    assert payload["statement"]["internalReferenceNumber"].startswith("TS-SUP-TEST")
    assert payload["statement"]["commodities"][0]["hsHeading"] == "1511"
    assert payload["assessment"]["recordId"] == "REC-TEST"
    assert payload["assessment"]["findings"][0]["evidenceIds"]
    assert payload["citations"]["statement.commodities[0].hsHeading"]


def test_xml_matches_the_eudr_submit_request_shape() -> None:
    document, _, _ = build_document(make_input())
    root = ET.fromstring(document.to_xml())
    assert root.tag == f"{{{SOAP_NAMESPACE}}}Envelope"
    request = root.find(f"{{{SOAP_NAMESPACE}}}Body/{{{DDS_NAMESPACE}}}SubmitDdsRequest")
    assert request is not None
    assert request.findtext(f"{{{DDS_NAMESPACE}}}operatorRole") == "OPERATOR"
    statement = request.find(f"{{{DDS_NAMESPACE}}}statement")
    assert statement is not None
    assert statement.findtext(f"{{{DDS_NAMESPACE}}}activityType") == "IMPORT"
    descriptor = statement.find(f"{{{DDS_NAMESPACE}}}commodities/{{{DDS_NAMESPACE}}}descriptors")
    assert descriptor is not None
    assert descriptor.findtext(f"{{{COMMON_NAMESPACE}}}descriptionOfGoods")
    measure = descriptor.find(f"{{{COMMON_NAMESPACE}}}goodsMeasure")
    assert measure is not None
    assert measure.findtext(f"{{{COMMON_NAMESPACE}}}netWeight")
    producer = statement.find(f"{{{DDS_NAMESPACE}}}commodities/{{{DDS_NAMESPACE}}}producers")
    assert producer is not None
    assert producer.findtext(f"{{{DDS_NAMESPACE}}}country") == "ID"
    assert producer.findtext(f"{{{DDS_NAMESPACE}}}geometryGeojson")


def test_geojson_is_a_polygon_for_plots_above_four_hectares() -> None:
    document, _, _ = build_document(make_input(parcel=make_parcel(area_ha=500.0)))
    collection = decode_geojson(document)
    assert collection["type"] == "FeatureCollection"
    feature = collection["features"][0]
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"]["ProducerCountry"] == "ID"
    assert feature["properties"]["Area"] == 500.0
    for lon, lat in feature["geometry"]["coordinates"][0]:
        assert round(lon, 6) == lon
        assert round(lat, 6) == lat


def test_geojson_is_a_point_at_or_below_four_hectares() -> None:
    document, _, _ = build_document(make_input(parcel=make_parcel(area_ha=2.0)))
    feature = decode_geojson(document)["features"][0]
    assert feature["geometry"]["type"] == "Point"
    assert feature["properties"]["Area"] == 2.0


def test_serializations_are_byte_stable() -> None:
    document, _, _ = build_document(make_input())
    assert document.to_xml() == document.to_xml()
    assert document.to_json() == document.to_json()


def test_all_required_claims_are_cited() -> None:
    document, _, ledger = build_document(make_input())
    for claim in REQUIRED_DDS_CLAIMS:
        assert document.citations.get(claim), f"missing citation for {claim}"
    validate_citations(document, ledger)


def test_validate_citations_rejects_uncited_and_unknown_claims() -> None:
    document, _, ledger = build_document(make_input())
    missing = document.model_copy(deep=True)
    del missing.citations["statement.commodities[0].hsHeading"]
    with pytest.raises(UncitedClaimError):
        validate_citations(missing, ledger)

    corrupt = document.model_copy(deep=True)
    corrupt.citations["statement.commodities[0].hsHeading"] = ["EV-does-not-exist"]
    with pytest.raises(LedgerLookupError):
        validate_citations(corrupt, ledger)


def test_missing_consignment_or_operator_is_a_typed_failure() -> None:
    input = make_input(consignment=None)
    ledger = build_source_ledger(input, retrieved_at=FIXED_TIME)
    assessment = assess(input, ledger)
    with pytest.raises(MissingAssessmentInputError):
        build_dds(input, assessment, ledger)

    input = make_input(operator=None)
    ledger = build_source_ledger(input, retrieved_at=FIXED_TIME)
    assessment = assess(input, ledger)
    with pytest.raises(MissingAssessmentInputError):
        build_dds(input, assessment, ledger)


def test_invalid_geometry_is_a_typed_failure() -> None:
    bowtie = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]],
    }
    input = make_input(parcel=make_parcel(area_ha=500.0, geometry=bowtie))
    ledger = build_source_ledger(input, retrieved_at=FIXED_TIME)
    assessment = assess(input, ledger)
    with pytest.raises(InvalidGeometryError):
        build_dds(input, assessment, ledger)


def test_producer_name_comes_from_the_supplier_legal_name() -> None:
    input = make_input(
        supplier=make_supplier(legal_name="PT Karya Sentosa Borneo"),
        consignment=make_consignment(commodity="wood", hs_heading="4703"),
        operator=make_operator(),
        loss=make_loss(),
        hotspots=make_hotspots(),
    )
    document, _, _ = build_document(input)
    assert document.statement.commodities[0].hs_heading == "4703"
    assert document.statement.commodities[0].producers[0].name == "PT Karya Sentosa Borneo"


def test_dds_golden_fixture_matches() -> None:
    input = make_input(
        parcel=make_parcel(polygon_id="PLY-GOLDEN"),
        record_id="REC-GOLDEN",
        loss=make_loss(total_ha=12.0),
        hotspots=make_hotspots(count=2, total_frp=30.0),
    )
    document, _, _ = build_document(input)
    assert document.to_xml() == (FIXTURES / "dds_reference.xml").read_text(encoding="utf-8")
    assert document.to_json() == (FIXTURES / "dds_reference.json").read_text(encoding="utf-8")
