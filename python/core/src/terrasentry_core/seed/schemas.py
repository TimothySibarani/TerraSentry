"""Pydantic schemas for the synthetic seed datasets."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Archetype = Literal["compliant", "high_risk", "ambiguous"]
Scenario = Literal["compliant_live", "high_risk_live"]

LEGALITY_DISCLOSURE = (
    "SYNTHETIC TEST DATA — companies, permits, people, and identifiers are invented for "
    "TerraSentry and do not describe any real organisation or person."
)
POLYGON_DISCLOSURE = (
    "Coordinates are synthetic but placed inside real forest regions of Sumatra and Kalimantan "
    "so Hansen GFC and NASA FIRMS return real data for them."
)


class SeedPolygon(BaseModel):
    id: str
    label: str
    region: str
    province: str
    archetype: Archetype
    scenario: Scenario | None = None
    is_demo: bool = False
    area_ha: float
    centroid_lat: float
    centroid_lon: float
    geometry: dict[str, Any]


class SeedDataset(BaseModel):
    schema_version: int = 1
    rng_seed: int
    disclosure: str = POLYGON_DISCLOSURE
    generated_by: str = "terrasentry_core.seed"
    polygons: list[SeedPolygon]


class LegalityRecord(BaseModel):
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
    disclosure: str = LEGALITY_DISCLOSURE


class LegalityDataset(BaseModel):
    schema_version: int = 1
    rng_seed: int
    disclosure: str = LEGALITY_DISCLOSURE
    records: list[LegalityRecord]


class BatchRecord(BaseModel):
    record_id: str
    supplier_id: str
    polygon: SeedPolygon
    legality: LegalityRecord
    expected_archetype: Archetype


class BatchDataset(BaseModel):
    schema_version: int = 1
    rng_seed: int
    distribution: dict[str, int]
    disclosure: str = POLYGON_DISCLOSURE
    records: list[BatchRecord]
