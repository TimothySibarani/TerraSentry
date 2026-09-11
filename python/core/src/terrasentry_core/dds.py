"""DDS builder: EUDR Information System (TRACES) V3-aligned JSON + XML.

The EUDR Information System is the TRACES platform's due-diligence tool. Its
public Operator API Reference (V3) defines the ``SubmitDdsRequest`` payload this
module mirrors: namespaces, field names, HS/species structure, and the GeoJSON
geolocation contract (polygons required above 4 ha, points allowed at or below;
WGS 84, six decimals, closed rings, no holes). Reference:

https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/help/eudr-documentation/operator/api/due-diligence-statement-v3.html
https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/help/eudr-documentation/operator/geojson-description.html

Two serializations of the same document:

- :meth:`DdsDocument.to_json` — the dossier, EUDR field names in camelCase plus a
  clearly separated ``terrasentry`` extension block (assessment, citations,
  disclosures) that would not be submitted to the Information System.
- :meth:`DdsDocument.to_xml` — the ``SubmitDdsRequest`` inside a SOAP envelope,
  without the WS-Security header (no credentials in this build). Submission is
  deliberately out of scope and disclosed.

Every DDS claim is cited in ``DdsDocument.citations`` and
:func:`validate_citations` fails if a required claim is uncited or cites a
missing ledger entry.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from terrasentry_core.domain.models import Assessment, AssessmentInput
from terrasentry_core.errors import (
    InvalidGeometryError,
    MissingAssessmentInputError,
    UncitedClaimError,
)
from terrasentry_core.evidence import EvidenceLedger

DDS_SCHEMA_VERSION = "eudr-is-v3"
DDS_NAMESPACE = "http://ec.europa.eu/tracesnt/certificate/eudr/due-diligence-statement/v3"
COMMON_NAMESPACE = "http://ec.europa.eu/tracesnt/certificate/eudr/common/v3"
SOAP_NAMESPACE = "http://schemas.xmlsoap.org/soap/envelope/"

#: Plot size at or below which the EUDR geolocation may be a point.
POINT_PLOT_MAX_HA = 4.0
GEO_DECIMALS = 6

#: Claims a DDS must be able to trace back to the ledger.
REQUIRED_DDS_CLAIMS: tuple[str, ...] = (
    "statement.internalReferenceNumber",
    "statement.activityType",
    "statement.countryOfActivity",
    "statement.borderCrossCountry",
    "statement.representedOperator.operatorName",
    "statement.representedOperator.operatorReferenceNumber",
    "statement.representedOperator.operatorAddress",
    "statement.representedOperator.operatorContact",
    "statement.commodities[0].descriptors.descriptionOfGoods",
    "statement.commodities[0].descriptors.goodsMeasure.netWeight",
    "statement.commodities[0].hsHeading",
    "statement.commodities[0].speciesInfo",
    "statement.commodities[0].producers[0].name",
    "statement.commodities[0].producers[0].country",
    "statement.commodities[0].producers[0].productionPlace",
    "statement.commodities[0].producers[0].geometryGeojson",
    "statement.geoLocationConfidential",
    "assessment.score",
    "assessment.verdict",
)

_EUDR_MODEL_CONFIG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class EudrAddress(BaseModel):
    model_config = _EUDR_MODEL_CONFIG

    country: str
    street: str
    postal_code: str
    city: str
    full_address: str | None = None


class EudrIdentifier(BaseModel):
    model_config = _EUDR_MODEL_CONFIG

    identifier_type: str
    identifier_value: str


class EudrOperator(BaseModel):
    model_config = _EUDR_MODEL_CONFIG

    operator_name: str
    operator_reference_number: EudrIdentifier | None = None
    operator_address: EudrAddress | None = None
    operator_email: str | None = None
    operator_phone: str | None = None


class EudrGoodsMeasure(BaseModel):
    model_config = _EUDR_MODEL_CONFIG

    net_weight: float | None = None
    supplementary_unit: float | None = None
    supplementary_unit_qualifier: str | None = None
    percentage_estimation_or_deviation: float | None = None


class EudrDescriptor(BaseModel):
    model_config = _EUDR_MODEL_CONFIG

    description_of_goods: str
    goods_measure: EudrGoodsMeasure


class EudrSpeciesInfo(BaseModel):
    model_config = _EUDR_MODEL_CONFIG

    scientific_name: str | None = None
    common_name: str | None = None


class EudrProducer(BaseModel):
    model_config = _EUDR_MODEL_CONFIG

    country: str
    name: str | None = None
    position: int = 1
    geometry_geojson: str


class EudrCommodity(BaseModel):
    model_config = _EUDR_MODEL_CONFIG

    hs_heading: str
    descriptors: EudrDescriptor
    position: int = 1
    species_info: EudrSpeciesInfo | None = None
    producers: list[EudrProducer] = Field(default_factory=list)


class EudrStatement(BaseModel):
    model_config = _EUDR_MODEL_CONFIG

    internal_reference_number: str
    activity_type: str
    commodities: list[EudrCommodity]
    geo_location_confidential: bool = False
    country_of_activity: str | None = None
    border_cross_country: str | None = None
    represented_operator: EudrOperator | None = None
    comment: str | None = None


class DdsFinding(BaseModel):
    """TerraSentry extension: one rubric finding with its evidence references."""

    model_config = _EUDR_MODEL_CONFIG

    code: str
    level: str
    points: int
    detail: str
    evidence_ids: list[str] = Field(default_factory=list)


class DdsAssessmentSummary(BaseModel):
    """TerraSentry extension: deterministic verdict and the findings behind it."""

    model_config = _EUDR_MODEL_CONFIG

    record_id: str | None = None
    supplier_id: str
    polygon_id: str
    rubric_version: str
    score: int
    verdict: str
    risk_level: str
    findings: list[DdsFinding] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


class ErpAction(BaseModel):
    """TerraSentry extension: the ERP action a released verdict triggered (M7).

    ``real`` is False for the schema-accurate stub and True for a sandbox/live
    SAP endpoint, so the dossier itself states exactly what happened. A failed
    action is recorded with ``status="failed"`` and ``error`` set; the DDS stays
    released because the compliance decision does not depend on ERP uptime.
    """

    model_config = _EUDR_MODEL_CONFIG

    vendor_id: str
    status: str
    purchasing_block: bool = False
    mode: str = "stub"
    real: bool = False
    external_reference: str | None = None
    performed_at: datetime | None = None
    disclosure: str = ""
    error: str | None = None


class DdsDocument(BaseModel):
    """One DDS plus the audit extension; never submitted as-is."""

    model_config = _EUDR_MODEL_CONFIG

    schema_version: str = DDS_SCHEMA_VERSION
    operator_role: str = "OPERATOR"
    statement: EudrStatement
    assessment: DdsAssessmentSummary
    citations: dict[str, list[str]] = Field(default_factory=dict)
    disclosures: list[str] = Field(default_factory=list)
    synthetic: bool = True
    erp_action: ErpAction | None = None

    def to_json(self, *, indent: int = 2) -> str:
        """The dossier (EUDR field names, camelCase) plus the audited extension."""
        exclude = {"erp_action"} if self.erp_action is None else None
        payload = self.model_dump(mode="json", by_alias=True, exclude=exclude)
        return json.dumps(payload, indent=indent, ensure_ascii=False) + "\n"

    def to_xml(self) -> str:
        """The EUDR ``SubmitDdsRequest`` wrapped in a SOAP envelope (no security header)."""
        return _render_xml(self)


def _round_coordinates(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_round_coordinates(item) for item in value]
    if isinstance(value, float):
        return round(value, GEO_DECIMALS)
    return value


def build_geojson_feature_collection(
    *,
    polygon_id: str,
    label: str,
    area_ha: float,
    centroid_lon: float,
    centroid_lat: float,
    geometry: dict[str, Any],
    producer_name: str,
    producer_country: str = "ID",
) -> dict[str, Any]:
    """A GeoJSON FeatureCollection matching the Information System's file format.

    Polygons are required above 4 ha; at or below, a point is used (the system
    defaults the point's ``Area`` to 4 ha when absent, so we always include it).
    """
    try:
        parsed: BaseGeometry = shape(geometry)
    except Exception as exc:
        raise InvalidGeometryError(polygon_id, str(exc)) from exc
    if not parsed.is_valid:
        raise InvalidGeometryError(polygon_id, "geometry is not valid")
    if parsed.is_empty:
        raise InvalidGeometryError(polygon_id, "geometry is empty")

    if area_ha > POINT_PLOT_MAX_HA:
        if parsed.geom_type not in {"Polygon", "MultiPolygon"}:
            raise InvalidGeometryError(polygon_id, f"expected a polygon, got {parsed.geom_type}")
        geometry_payload: dict[str, Any] = {
            "type": parsed.geom_type,
            "coordinates": _round_coordinates(_coordinates_of(parsed)),
        }
    else:
        geometry_payload = {
            "type": "Point",
            "coordinates": [round(centroid_lon, GEO_DECIMALS), round(centroid_lat, GEO_DECIMALS)],
        }

    properties = {
        "ProducerName": producer_name,
        "ProducerCountry": producer_country,
        "ProductionPlace": label,
        "Area": round(area_ha, 2),
    }
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": properties, "geometry": geometry_payload},
        ],
    }


def _coordinates_of(geometry: BaseGeometry) -> Any:
    return mapping(geometry)["coordinates"]


def encode_geojson(collection: dict[str, Any]) -> str:
    """Base64 of the canonical GeoJSON document, as ``geometryGeojson`` expects."""
    text = json.dumps(collection, separators=(",", ":"), ensure_ascii=False)
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def build_dds(
    input: AssessmentInput,
    assessment: Assessment,
    ledger: EvidenceLedger,
) -> DdsDocument:
    """Assemble the EUDR payload for one assessed record and cite every claim."""
    if input.consignment is None:
        raise MissingAssessmentInputError(
            f"record {input.record_id or input.parcel.polygon_id} has no consignment to declare"
        )
    if input.operator is None:
        raise MissingAssessmentInputError(
            f"record {input.record_id or input.parcel.polygon_id} has no operator profile"
        )
    consignment = input.consignment
    operator = input.operator
    parcel = input.parcel
    supplier = input.supplier

    geojson = build_geojson_feature_collection(
        polygon_id=parcel.polygon_id,
        label=consignment.production_place,
        area_ha=parcel.area_ha,
        centroid_lon=parcel.centroid_lon,
        centroid_lat=parcel.centroid_lat,
        geometry=parcel.geometry,
        producer_name=supplier.legal_name,
    )
    geometry_b64 = encode_geojson(geojson)

    internal_reference = f"TS-{supplier.supplier_id}-{input.record_id or parcel.polygon_id}"
    represented_operator = EudrOperator(
        operator_name=operator.legal_name,
        operator_reference_number=EudrIdentifier(
            identifier_type=operator.identifier_type,
            identifier_value=operator.identifier_value,
        ),
        operator_address=EudrAddress(
            country=operator.country,
            street=operator.address_line,
            postal_code=operator.postal_code,
            city=operator.city,
        ),
        operator_email=operator.email,
        operator_phone=operator.phone,
    )
    statement = EudrStatement(
        internal_reference_number=internal_reference[:50],
        activity_type=operator.activity_type,
        country_of_activity=operator.country_of_activity,
        border_cross_country=operator.border_cross_country,
        commodities=[
            EudrCommodity(
                position=1,
                descriptors=EudrDescriptor(
                    description_of_goods=consignment.description,
                    goods_measure=EudrGoodsMeasure(
                        net_weight=consignment.net_weight_kg,
                        supplementary_unit=consignment.supplementary_unit,
                        supplementary_unit_qualifier=consignment.supplementary_unit_qualifier,
                    ),
                ),
                hs_heading=consignment.hs_heading,
                species_info=EudrSpeciesInfo(
                    scientific_name=consignment.species_scientific,
                    common_name=consignment.species_common,
                ),
                producers=[
                    EudrProducer(
                        position=1,
                        country="ID",
                        name=supplier.legal_name,
                        geometry_geojson=geometry_b64,
                    ),
                ],
            )
        ],
        geo_location_confidential=False,
        represented_operator=represented_operator,
    )

    citations = _build_citations(ledger)
    disclosures = sorted({*assessment.disclosures, consignment.disclosure, operator.disclosure})
    document = DdsDocument(
        operator_role="OPERATOR",
        statement=statement,
        assessment=DdsAssessmentSummary(
            record_id=assessment.record_id,
            supplier_id=assessment.supplier_id,
            polygon_id=assessment.polygon_id,
            rubric_version=assessment.rubric_version,
            score=assessment.score,
            verdict=str(assessment.verdict),
            risk_level=str(assessment.risk_level),
            findings=[
                DdsFinding(
                    code=str(finding.code),
                    level=str(finding.level),
                    points=finding.points,
                    detail=finding.detail,
                    evidence_ids=finding.evidence_ids,
                )
                for finding in assessment.findings
            ],
            data_gaps=assessment.data_gaps,
        ),
        citations=citations,
        disclosures=[disclosure for disclosure in disclosures if disclosure],
        synthetic=supplier.synthetic or consignment.synthetic or operator.synthetic,
    )
    return document


def _first(ledger: EvidenceLedger, claim: str) -> list[str]:
    """Ids for a claim; an empty list is reported later as an uncited claim."""
    return ledger.ids_for(claim)


def _build_citations(ledger: EvidenceLedger) -> dict[str, list[str]]:
    return {
        "statement.internalReferenceNumber": _first(ledger, "supplier.identifiers"),
        "statement.activityType": _first(ledger, "operator.activity"),
        "statement.countryOfActivity": _first(ledger, "operator.activity"),
        "statement.borderCrossCountry": _first(ledger, "operator.activity"),
        "statement.representedOperator.operatorName": _first(ledger, "operator.name"),
        "statement.representedOperator.operatorReferenceNumber": _first(ledger, "operator.identifier"),
        "statement.representedOperator.operatorAddress": _first(ledger, "operator.address"),
        "statement.representedOperator.operatorContact": _first(ledger, "operator.contact"),
        "statement.commodities[0].descriptors.descriptionOfGoods": _first(ledger, "consignment.description"),
        "statement.commodities[0].descriptors.goodsMeasure.netWeight": _first(ledger, "consignment.measure"),
        "statement.commodities[0].descriptors.goodsMeasure.supplementaryUnit": _first(
            ledger, "consignment.measure"
        ),
        "statement.commodities[0].hsHeading": _first(ledger, "consignment.hs_heading"),
        "statement.commodities[0].speciesInfo": _first(ledger, "consignment.species"),
        "statement.commodities[0].producers[0].name": _first(ledger, "supplier.name"),
        "statement.commodities[0].producers[0].country": _first(ledger, "parcel.country"),
        "statement.commodities[0].producers[0].productionPlace": _first(
            ledger, "consignment.production_place"
        ),
        "statement.commodities[0].producers[0].geometryGeojson": _first(ledger, "parcel.geometry"),
        "statement.geoLocationConfidential": _first(ledger, "rubric.verdict"),
        "assessment.score": _first(ledger, "rubric.score"),
        "assessment.verdict": _first(ledger, "rubric.verdict"),
    }


def validate_citations(document: DdsDocument, ledger: EvidenceLedger) -> None:
    """Fail if a required DDS claim is uncited or cites an unknown ledger entry."""
    for claim in REQUIRED_DDS_CLAIMS:
        if not document.citations.get(claim):
            raise UncitedClaimError(claim)
    ledger.verify(document.citations)


def _render_xml(document: DdsDocument) -> str:
    ET.register_namespace("soapenv", SOAP_NAMESPACE)
    ET.register_namespace("dds", DDS_NAMESPACE)
    ET.register_namespace("eudrCommon", COMMON_NAMESPACE)

    envelope = ET.Element(f"{{{SOAP_NAMESPACE}}}Envelope")
    body = ET.SubElement(envelope, f"{{{SOAP_NAMESPACE}}}Body")
    request = ET.SubElement(body, f"{{{DDS_NAMESPACE}}}SubmitDdsRequest")
    ET.SubElement(request, f"{{{DDS_NAMESPACE}}}operatorRole").text = document.operator_role

    statement = ET.SubElement(request, f"{{{DDS_NAMESPACE}}}statement")
    statement_payload = document.statement
    ET.SubElement(
        statement, f"{{{DDS_NAMESPACE}}}internalReferenceNumber"
    ).text = statement_payload.internal_reference_number
    ET.SubElement(statement, f"{{{DDS_NAMESPACE}}}activityType").text = statement_payload.activity_type
    if statement_payload.country_of_activity is not None:
        ET.SubElement(
            statement, f"{{{DDS_NAMESPACE}}}countryOfActivity"
        ).text = statement_payload.country_of_activity
    if statement_payload.border_cross_country is not None:
        ET.SubElement(
            statement, f"{{{DDS_NAMESPACE}}}borderCrossCountry"
        ).text = statement_payload.border_cross_country

    for commodity in statement_payload.commodities:
        node = ET.SubElement(statement, f"{{{DDS_NAMESPACE}}}commodities")
        ET.SubElement(node, f"{{{DDS_NAMESPACE}}}position").text = str(commodity.position)
        descriptors = ET.SubElement(node, f"{{{DDS_NAMESPACE}}}descriptors")
        ET.SubElement(
            descriptors, f"{{{COMMON_NAMESPACE}}}descriptionOfGoods"
        ).text = commodity.descriptors.description_of_goods
        measure = ET.SubElement(descriptors, f"{{{COMMON_NAMESPACE}}}goodsMeasure")
        goods = commodity.descriptors.goods_measure
        if goods.net_weight is not None:
            ET.SubElement(measure, f"{{{COMMON_NAMESPACE}}}netWeight").text = f"{goods.net_weight:.6f}"
        if goods.supplementary_unit is not None:
            ET.SubElement(
                measure, f"{{{COMMON_NAMESPACE}}}supplementaryUnit"
            ).text = f"{goods.supplementary_unit:.6f}"
        if goods.supplementary_unit_qualifier is not None:
            ET.SubElement(
                measure, f"{{{COMMON_NAMESPACE}}}supplementaryUnitQualifier"
            ).text = goods.supplementary_unit_qualifier
        ET.SubElement(node, f"{{{DDS_NAMESPACE}}}hsHeading").text = commodity.hs_heading
        if commodity.species_info is not None:
            species = ET.SubElement(node, f"{{{DDS_NAMESPACE}}}speciesInfo")
            if commodity.species_info.scientific_name is not None:
                ET.SubElement(
                    species, f"{{{DDS_NAMESPACE}}}scientificName"
                ).text = commodity.species_info.scientific_name
            if commodity.species_info.common_name is not None:
                ET.SubElement(
                    species, f"{{{DDS_NAMESPACE}}}commonName"
                ).text = commodity.species_info.common_name
        for producer in commodity.producers:
            producer_node = ET.SubElement(node, f"{{{DDS_NAMESPACE}}}producers")
            ET.SubElement(producer_node, f"{{{DDS_NAMESPACE}}}position").text = str(producer.position)
            ET.SubElement(producer_node, f"{{{DDS_NAMESPACE}}}country").text = producer.country
            if producer.name is not None:
                ET.SubElement(producer_node, f"{{{DDS_NAMESPACE}}}name").text = producer.name
            ET.SubElement(
                producer_node, f"{{{DDS_NAMESPACE}}}geometryGeojson"
            ).text = producer.geometry_geojson

    ET.SubElement(statement, f"{{{DDS_NAMESPACE}}}geoLocationConfidential").text = str(
        statement_payload.geo_location_confidential
    ).lower()

    if statement_payload.represented_operator is not None:
        represented = ET.SubElement(statement, f"{{{DDS_NAMESPACE}}}representedOperator")
        operator = statement_payload.represented_operator
        ET.SubElement(represented, f"{{{DDS_NAMESPACE}}}operatorName").text = operator.operator_name
        if operator.operator_reference_number is not None:
            reference = ET.SubElement(represented, f"{{{DDS_NAMESPACE}}}operatorReferenceNumber")
            ET.SubElement(
                reference, f"{{{DDS_NAMESPACE}}}identifierType"
            ).text = operator.operator_reference_number.identifier_type
            ET.SubElement(
                reference, f"{{{DDS_NAMESPACE}}}identifierValue"
            ).text = operator.operator_reference_number.identifier_value
        if operator.operator_address is not None:
            address = ET.SubElement(represented, f"{{{DDS_NAMESPACE}}}operatorAddress")
            ET.SubElement(address, f"{{{DDS_NAMESPACE}}}country").text = operator.operator_address.country
            ET.SubElement(address, f"{{{DDS_NAMESPACE}}}street").text = operator.operator_address.street
            ET.SubElement(
                address, f"{{{DDS_NAMESPACE}}}postalCode"
            ).text = operator.operator_address.postal_code
            ET.SubElement(address, f"{{{DDS_NAMESPACE}}}city").text = operator.operator_address.city
        if operator.operator_email is not None:
            ET.SubElement(represented, f"{{{DDS_NAMESPACE}}}operatorEmail").text = operator.operator_email
        if operator.operator_phone is not None:
            ET.SubElement(represented, f"{{{DDS_NAMESPACE}}}operatorPhone").text = operator.operator_phone

    if statement_payload.comment is not None:
        ET.SubElement(statement, f"{{{DDS_NAMESPACE}}}comment").text = statement_payload.comment

    ET.indent(envelope, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(envelope, encoding="unicode")
