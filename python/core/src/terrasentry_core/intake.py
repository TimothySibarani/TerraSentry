"""Intake for user-submitted plots: validate untrusted input, build a record.

This is the trust boundary for everything that is not seed data. A submission
is turned into the same :class:`BatchRecord` shape the seed uses, so the agent
graph, rubric, verifier, and DDS writer run unchanged. Nothing here calls the
network or a model; geometry is validated with shapely and measured
geodesically with pyproj.
"""

from __future__ import annotations

import math
from typing import Any, Literal
from uuid import uuid4

import shapely
from pydantic import BaseModel, Field, field_validator
from pyproj import Geod
from shapely.geometry import MultiPolygon, Point, Polygon, mapping, shape
from shapely.validation import explain_validity

from terrasentry_core.errors import CoreError
from terrasentry_core.seed.schemas import (
    BatchRecord,
    Commodity,
    ConsignmentRecord,
    LegalityRecord,
    SeedPolygon,
)

_GEOD = Geod(ellps="WGS84")

#: EUDR Art. 2(28): plots above 4 ha must be described by a polygon.
POINT_MAX_HA = 4.0
MIN_AREA_HA = 0.01
MAX_AREA_HA = 10_000.0
MAX_VERTICES = 5_000
_COORD_PRECISION = 1e-6
_POINT_BUFFER_SEGMENTS = 32

DECLARED_DISCLOSURE = (
    "Declared by the supplier through TerraSentry intake; not verified against a government "
    "permit registry. Geospatial and thermal evidence for this plot is real (GFW, NASA FIRMS)."
)

PermitType = Literal["hgu", "pbph", "none"]
PermitStatus = Literal["active", "expired", "suspended", "none"]

#: Default HS headings (EUDR Annex I) when the submitter leaves the field empty.
DEFAULT_HS: dict[str, str] = {
    "oil_palm": "1511",
    "wood": "4403",
    "rubber": "4001",
    "cocoa": "1801",
    "coffee": "0901",
}


class IntakeError(CoreError):
    """A submission failed validation; ``field`` names the offending input."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class PlotInput(BaseModel):
    geometry: dict[str, Any] = Field(
        description="GeoJSON Polygon, MultiPolygon, Point, or a Feature wrapping one."
    )
    label: str = Field(min_length=1, max_length=120)
    province: str = Field(default="", max_length=64)
    kabupaten: str = Field(default="", max_length=64)
    declared_area_ha: float | None = Field(
        default=None, gt=0, description="Required for a Point; must be <= 4 ha (EUDR)."
    )


class SupplierInput(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    trading_name: str = Field(default="", max_length=200)
    group: str = Field(default="", max_length=200)
    nib: str = Field(default="", max_length=32, description="Nomor Induk Berusaha (business id).")
    npwp: str = Field(default="", max_length=32, description="Tax id.")
    beneficial_owners: list[str] = Field(default_factory=list, max_length=20)
    certifications: list[str] = Field(default_factory=list, max_length=20)


class LegalityInput(BaseModel):
    permit_type: PermitType = "none"
    permit_number: str = Field(default="", max_length=64)
    permit_status: PermitStatus = "active"
    concession_area_ha: float | None = Field(default=None, gt=0)
    sanctions: list[str] = Field(default_factory=list, max_length=20)


class ConsignmentInput(BaseModel):
    commodity: Commodity
    description: str = Field(min_length=2, max_length=300)
    hs_heading: str = Field(default="", max_length=10)
    species_scientific: str = Field(default="", max_length=120)
    species_common: str = Field(default="", max_length=120)
    net_weight_kg: float = Field(gt=0, le=1e10)
    harvest_year: int = Field(ge=2000, le=2100)

    @field_validator("hs_heading")
    @classmethod
    def _digits(cls, value: str) -> str:
        value = value.strip().replace(".", "")
        if value and (not value.isdigit() or len(value) not in (4, 6, 8, 10)):
            raise ValueError("HS heading must be 4, 6, 8, or 10 digits")
        return value


class RecordSubmission(BaseModel):
    """Everything a user declares for one plot."""

    plot: PlotInput
    supplier: SupplierInput
    legality: LegalityInput = Field(default_factory=LegalityInput)
    consignment: ConsignmentInput


class GeometryReport(BaseModel):
    """Normalized geometry plus what the server measured."""

    geometry: dict[str, Any]
    query_geometry: dict[str, Any]
    geometry_type: str
    area_ha: float
    centroid_lat: float
    centroid_lon: float
    vertex_count: int


def geodesic_area_ha(geometry: Polygon | MultiPolygon) -> float:
    area, _ = _GEOD.geometry_area_perimeter(geometry)
    return abs(area) / 10_000.0


def _unwrap(raw: dict[str, Any]) -> dict[str, Any]:
    kind = raw.get("type")
    if kind == "Feature":
        inner = raw.get("geometry")
        if not isinstance(inner, dict):
            raise IntakeError("plot.geometry", "Feature has no geometry")
        return inner
    if kind == "FeatureCollection":
        features = raw.get("features")
        if not isinstance(features, list) or len(features) != 1 or not isinstance(features[0], dict):
            raise IntakeError("plot.geometry", "FeatureCollection must contain exactly one feature per plot")
        return _unwrap(features[0])
    return raw


def _point_buffer(point: Point, area_ha: float) -> Polygon:
    """A geodesic circle of ``area_ha`` around ``point``, used for source queries."""
    radius_m = math.sqrt(area_ha * 10_000.0 / math.pi)
    lons, lats, _ = _GEOD.fwd(
        [point.x] * _POINT_BUFFER_SEGMENTS,
        [point.y] * _POINT_BUFFER_SEGMENTS,
        [i * 360.0 / _POINT_BUFFER_SEGMENTS for i in range(_POINT_BUFFER_SEGMENTS)],
        [radius_m] * _POINT_BUFFER_SEGMENTS,
    )
    ring = list(zip(lons, lats, strict=True))
    return Polygon([*ring, ring[0]])


def validate_geometry(raw: dict[str, Any], *, declared_area_ha: float | None = None) -> GeometryReport:
    """Validate and normalize one plot geometry (WGS84 lon/lat)."""
    try:
        parsed = shape(_unwrap(raw))
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError("plot.geometry", f"not a GeoJSON geometry: {exc}") from exc
    if parsed.is_empty:
        raise IntakeError("plot.geometry", "geometry is empty")
    if parsed.geom_type not in {"Polygon", "MultiPolygon", "Point"}:
        raise IntakeError(
            "plot.geometry", f"unsupported geometry type {parsed.geom_type}; use Polygon or Point"
        )
    if parsed.has_z:
        parsed = shapely.force_2d(parsed)
    min_lon, min_lat, max_lon, max_lat = parsed.bounds
    if min_lon < -180 or max_lon > 180 or min_lat < -90 or max_lat > 90:
        raise IntakeError(
            "plot.geometry", "coordinates must be WGS84 longitude/latitude (lon -180..180, lat -90..90)"
        )
    vertices = int(shapely.get_num_coordinates(parsed))
    if vertices > MAX_VERTICES:
        raise IntakeError(
            "plot.geometry", f"geometry has {vertices} vertices; simplify it to at most {MAX_VERTICES}"
        )

    if not parsed.is_valid:
        raise IntakeError("plot.geometry", f"invalid geometry: {explain_validity(parsed)}")
    # Round to 6 decimals (~0.1 m, the DDS precision) and re-check: rounding
    # can collapse or self-intersect a sliver.
    parsed = shapely.set_precision(parsed, _COORD_PRECISION, mode="pointwise")
    if parsed.is_empty or not parsed.is_valid:
        raise IntakeError(
            "plot.geometry", "geometry becomes invalid at 6-decimal precision; the plot is too thin"
        )

    if isinstance(parsed, Point):
        if declared_area_ha is None:
            raise IntakeError("plot.declared_area_ha", "a point plot needs a declared area (at most 4 ha)")
        if declared_area_ha > POINT_MAX_HA:
            raise IntakeError(
                "plot.declared_area_ha",
                f"plots over {POINT_MAX_HA:g} ha must be described by a polygon (EUDR Art. 2(28))",
            )
        area = declared_area_ha
        query: Polygon | MultiPolygon | Point = _point_buffer(parsed, declared_area_ha)
        centroid = parsed
    else:
        assert isinstance(parsed, Polygon | MultiPolygon)
        area = geodesic_area_ha(parsed)
        query = parsed
        centroid = parsed.centroid

    if area < MIN_AREA_HA:
        raise IntakeError("plot.geometry", f"plot area {area:.4f} ha is below the {MIN_AREA_HA} ha minimum")
    if area > MAX_AREA_HA:
        raise IntakeError(
            "plot.geometry", f"plot area {area:,.0f} ha exceeds {MAX_AREA_HA:,.0f} ha; split it into plots"
        )
    return GeometryReport(
        geometry=dict(mapping(parsed)),
        query_geometry=dict(mapping(query)),
        geometry_type=parsed.geom_type,
        area_ha=round(area, 4),
        centroid_lat=round(centroid.y, 6),
        centroid_lon=round(centroid.x, 6),
        vertex_count=vertices,
    )


def _short_id() -> str:
    return uuid4().hex[:10].upper()


def build_submitted_record(submission: RecordSubmission) -> tuple[BatchRecord, GeometryReport]:
    """Validate a submission and return the record the agent graph consumes."""
    plot = submission.plot
    report = validate_geometry(plot.geometry, declared_area_ha=plot.declared_area_ha)
    legality_in = submission.legality
    if legality_in.permit_type != "none" and not legality_in.permit_number.strip():
        raise IntakeError("legality.permit_number", "enter the permit number for the declared permit type")
    permit_status = "none" if legality_in.permit_type == "none" else legality_in.permit_status

    suffix = _short_id()
    supplier_id = f"SUP-U-{suffix}"
    polygon_id = f"PLY-U-{suffix}"
    record_id = f"REC-U-{suffix}"
    region = (
        ", ".join(part for part in (plot.kabupaten.strip(), plot.province.strip()) if part)
        or "Submitted plot"
    )
    polygon = SeedPolygon(
        id=polygon_id,
        label=plot.label.strip(),
        region=region,
        province=plot.province.strip(),
        archetype=None,
        scenario=None,
        is_demo=False,
        area_ha=report.area_ha,
        centroid_lat=report.centroid_lat,
        centroid_lon=report.centroid_lon,
        # Sources query the (buffered for points) query geometry; the DDS writes
        # a point for plots <= 4 ha from the centroid, so both stay correct.
        geometry=report.query_geometry,
    )
    supplier = submission.supplier
    legality = LegalityRecord(
        supplier_id=supplier_id,
        legal_name=supplier.legal_name.strip(),
        trading_name=supplier.trading_name.strip() or supplier.legal_name.strip(),
        group=supplier.group.strip(),
        nib=supplier.nib.strip(),
        npwp=supplier.npwp.strip(),
        hgu_number=legality_in.permit_number.strip() if legality_in.permit_type == "hgu" else None,
        pbp_number=legality_in.permit_number.strip() if legality_in.permit_type == "pbph" else None,
        permit_status=permit_status,
        # An undeclared concession area defaults to the plot, so no mismatch is
        # invented from missing data.
        concession_area_ha=legality_in.concession_area_ha or report.area_ha,
        province=plot.province.strip(),
        kabupaten=plot.kabupaten.strip(),
        beneficial_owners=[owner.strip() for owner in supplier.beneficial_owners if owner.strip()],
        certifications=[cert.strip() for cert in supplier.certifications if cert.strip()],
        sanctions=[item.strip() for item in legality_in.sanctions if item.strip()],
        synthetic=False,
        provenance="supplier_declared",
        disclosure=DECLARED_DISCLOSURE,
    )
    consignment_in = submission.consignment
    consignment = ConsignmentRecord(
        supplier_id=supplier_id,
        commodity=consignment_in.commodity,
        description=consignment_in.description.strip(),
        hs_heading=consignment_in.hs_heading or DEFAULT_HS[consignment_in.commodity],
        species_scientific=consignment_in.species_scientific.strip() or None,
        species_common=consignment_in.species_common.strip() or None,
        net_weight_kg=consignment_in.net_weight_kg,
        production_place=plot.label.strip(),
        harvest_year=consignment_in.harvest_year,
        synthetic=False,
        provenance="supplier_declared",
        disclosure=DECLARED_DISCLOSURE,
    )
    record = BatchRecord(
        record_id=record_id,
        supplier_id=supplier_id,
        polygon=polygon,
        legality=legality,
        consignment=consignment,
    )
    return record, report


__all__ = [
    "DECLARED_DISCLOSURE",
    "DEFAULT_HS",
    "GeometryReport",
    "IntakeError",
    "RecordSubmission",
    "build_submitted_record",
    "geodesic_area_ha",
    "validate_geometry",
]
