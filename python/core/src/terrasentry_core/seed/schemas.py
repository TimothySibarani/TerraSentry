"""Pydantic schemas for the synthetic seed datasets."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from terrasentry_core.countries import normalize_country

Archetype = Literal["compliant", "high_risk", "ambiguous"]
Scenario = Literal["compliant_live", "high_risk_live", "fire_live"]
ExpectedSignal = Literal["deforestation", "fire", "legal"]
AmbiguityReason = Literal["borderline_area", "old_fire_scar", "permit_gap"]
Commodity = Literal["oil_palm", "wood", "rubber", "cocoa", "coffee"]
#: Where a legality/consignment value came from; shown next to every evidence row.
Provenance = Literal[
    "synthetic",
    "supplier_declared",
    "document_extracted",
    "sap_import",
    "real_source",
    "operator_configured",
    "derived",
    "legacy_unknown",
]

SEED_SCHEMA_VERSION = 2

LEGALITY_DISCLOSURE = (
    "SYNTHETIC TEST DATA — companies, permits, people, and identifiers are invented for "
    "TerraSentry and do not describe any real organisation or person."
)
POLYGON_DISCLOSURE = (
    "Coordinates are synthetic but placed inside real forest regions of Sumatra and Kalimantan "
    "so Hansen GFC and NASA FIRMS return real data for them."
)
CONSIGNMENT_DISCLOSURE = (
    "SYNTHETIC TEST DATA — consignment quantities, products, and the EU operator are invented "
    "for TerraSentry. Only the HS heading and product structure follow the real EUDR formats."
)


class SeedPolygon(BaseModel):
    country: str | None = None
    provenance: Provenance = "synthetic"
    id: str
    label: str
    region: str
    province: str
    #: Seed design label; ``None`` for submitted (unlabelled) plots.
    archetype: Archetype | None = None
    scenario: Scenario | None = None
    is_demo: bool = False
    area_ha: float
    centroid_lat: float
    centroid_lon: float
    geometry: dict[str, Any]
    input_geometry: dict[str, Any] | None = None

    @field_validator("country")
    @classmethod
    def _country(cls, value: str | None) -> str | None:
        return normalize_country(value) if value is not None else None


class SeedDataset(BaseModel):
    schema_version: int = SEED_SCHEMA_VERSION
    rng_seed: int
    disclosure: str = POLYGON_DISCLOSURE
    generated_by: str = "terrasentry_core.seed"
    polygons: list[SeedPolygon]

    @model_validator(mode="after")
    def _seed_country(self) -> SeedDataset:
        for polygon in self.polygons:
            if polygon.country is None:
                polygon.country = "ID"
        return self


class LegalityRecord(BaseModel):
    permit_expiry: date | None = None
    declared_holder: str | None = None
    supplier_id: str
    legal_name: str
    trading_name: str
    group: str
    nib: str
    npwp: str
    hgu_number: str | None = None
    pbp_number: str | None = None
    permit_status: Literal["active", "expired", "suspended", "none"] = "active"
    concession_area_ha: float
    province: str
    kabupaten: str
    beneficial_owners: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    sanctions: list[str] = Field(default_factory=list)
    synthetic: bool = True
    provenance: Provenance = "synthetic"
    disclosure: str = LEGALITY_DISCLOSURE


class LegalityDataset(BaseModel):
    schema_version: int = SEED_SCHEMA_VERSION
    rng_seed: int
    disclosure: str = LEGALITY_DISCLOSURE
    records: list[LegalityRecord]


class ConsignmentRecord(BaseModel):
    """One product lot declared in the DDS, with realistic HS/species structure."""

    supplier_id: str
    commodity: Commodity
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
    provenance: Provenance = "synthetic"
    disclosure: str = CONSIGNMENT_DISCLOSURE


class OperatorRecord(BaseModel):
    """The synthetic EU operator on whose behalf the DDS is prepared."""

    operator_id: str
    legal_name: str
    identifier_type: Literal["eori", "vat", "tin", "comp_num", "oni"] = "eori"
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
    provenance: Provenance = "synthetic"
    synthetic: bool = True
    disclosure: str = LEGALITY_DISCLOSURE


class OperatorDataset(BaseModel):
    schema_version: int = SEED_SCHEMA_VERSION
    rng_seed: int
    disclosure: str = LEGALITY_DISCLOSURE
    operator: OperatorRecord


class BatchRecord(BaseModel):
    record_id: str
    supplier_id: str
    polygon: SeedPolygon
    legality: LegalityRecord
    consignment: ConsignmentRecord
    #: Seed design label; ``None`` for submitted records, which are unlabelled.
    expected_archetype: Archetype | None = None
    expected_signal: ExpectedSignal | None = None
    expected_ambiguity: AmbiguityReason | None = None


class BatchDataset(BaseModel):
    schema_version: int = SEED_SCHEMA_VERSION
    rng_seed: int
    distribution: dict[str, int]
    disclosure: str = POLYGON_DISCLOSURE
    records: list[BatchRecord]

    @model_validator(mode="after")
    def _seed_country(self) -> BatchDataset:
        for record in self.records:
            if record.legality.synthetic and record.polygon.country is None:
                record.polygon.country = "ID"
        return self
