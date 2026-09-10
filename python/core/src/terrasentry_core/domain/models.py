"""Domain models shared by scoring, the evidence ledger, and the DDS builder.

Source result types (``TreeCoverLossResult``, ``FirmsHotspotResult``) are reused
from ``terrasentry-integrations`` on purpose: the reference pipeline and the M3
agent tools produce exactly these shapes, so the deterministic core consumes the
same structured outputs in both paths (architecture cross-cutting rule 5).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from terrasentry_integrations.sources.firms import FirmsHotspotResult
from terrasentry_integrations.sources.gfw import TreeCoverLossResult

from terrasentry_core.domain.enums import FindingCode, FindingLevel, RiskLevel, Verdict

PermitStatus = Literal["active", "expired", "suspended", "none"]


class Parcel(BaseModel):
    """A plot of land under assessment."""

    polygon_id: str
    label: str
    region: str
    province: str
    area_ha: float
    centroid_lat: float
    centroid_lon: float
    geometry: dict[str, Any]


class SupplierProfile(BaseModel):
    """Synthetic legality/entity profile of the supplier operating the parcel."""

    supplier_id: str
    legal_name: str
    trading_name: str
    group: str
    nib: str
    npwp: str
    hgu_number: str | None = None
    pbp_number: str | None = None
    permit_status: PermitStatus = "active"
    concession_area_ha: float
    province: str
    kabupaten: str
    beneficial_owners: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    sanctions: list[str] = Field(default_factory=list)
    synthetic: bool = True
    disclosure: str = ""


class Consignment(BaseModel):
    """The product lot declared in the DDS (synthetic values, real HS structure)."""

    supplier_id: str
    commodity: str
    description: str
    hs_heading: str
    species_scientific: str | None = None
    species_common: str | None = None
    net_weight_kg: float
    supplementary_unit: float | None = None
    supplementary_unit_qualifier: str | None = None
    production_place: str
    harvest_year: int
    synthetic: bool = True
    disclosure: str = ""


class OperatorProfile(BaseModel):
    """The EU operator on whose behalf the DDS is prepared (synthetic)."""

    operator_id: str
    legal_name: str
    identifier_type: str = "eori"
    identifier_value: str
    address_line: str
    postal_code: str
    city: str
    country: str = "NL"
    email: str
    phone: str
    activity_type: Literal["IMPORT", "EXPORT", "DOMESTIC"] = "IMPORT"
    country_of_activity: str = "NL"
    border_cross_country: str = "NL"
    synthetic: bool = True
    disclosure: str = ""


class AssessmentInput(BaseModel):
    """Everything the rubric needs for one record, with no clock or network access."""

    record_id: str | None = None
    parcel: Parcel
    supplier: SupplierProfile
    loss: TreeCoverLossResult | None = None
    hotspots: FirmsHotspotResult | None = None
    consignment: Consignment | None = None
    operator: OperatorProfile | None = None
    source_errors: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """One deterministic signal, with the evidence ids that support it."""

    code: FindingCode
    level: FindingLevel
    points: int
    detail: str
    metrics: dict[str, float | int | str] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    mitigating: bool = False


class Assessment(BaseModel):
    """Reproducible outcome of the rubric for one supplier/parcel."""

    record_id: str | None = None
    supplier_id: str
    polygon_id: str
    rubric_version: str
    score: int
    verdict: Verdict
    risk_level: RiskLevel
    findings: list[Finding] = Field(default_factory=list)
    citations: dict[str, list[str]] = Field(default_factory=dict)
    disclosures: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
