"""Submitted plot records: create, validate, list, and bulk-import.

This is the intake surface that replaces "seed data only". Every write goes
through ``terrasentry_core.intake`` (the single validation boundary) and is
registered in the live record registry, so ``POST /runs {record_id}`` and
``POST /batch-runs {record_ids}`` work immediately and after a restart.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import ValidationError
from shapely import wkt
from shapely.errors import ShapelyError
from shapely.geometry import mapping
from sqlalchemy.ext.asyncio import AsyncSession
from terrasentry_core.intake import (
    GeometryReport,
    IntakeError,
    RecordSubmission,
    build_submitted_record,
    validate_geometry,
)
from terrasentry_core.seed.schemas import BatchRecord

from terrasentry_api.models import SubmittedRecord
from terrasentry_api.schemas import GeometryCheck, ImportResult, ImportRowError, RecordOut
from terrasentry_api.services import AppServices, get_services, get_session
from terrasentry_api.store import RunStore

router = APIRouter(prefix="/records", tags=["records"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[AppServices, Depends(get_services)]

MAX_IMPORT_ROWS = 500


def _unprocessable(field: str, message: str) -> HTTPException:
    # Same shape as FastAPI's own validation errors so clients map it to a field.
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[{"loc": ["body", *field.split(".")], "msg": message, "type": "intake"}],
    )


async def _record_out(store: RunStore, row: Any) -> RecordOut:
    latest = await store.latest_run_for_record(row.record_id)
    verdict = await store.get_verdict(latest.id) if latest is not None else None
    return RecordOut.from_parts(row, latest=latest, verdict=verdict)


async def _create(
    store: RunStore, submission: RecordSubmission, *, source: str
) -> tuple[SubmittedRecord, BatchRecord]:
    record, report = build_submitted_record(submission)
    row = await store.create_submitted_record(record, geometry=report.geometry, source=source)
    return row, record


@router.post("/validate-geometry", response_model=GeometryReport)
async def validate_plot_geometry(payload: GeometryCheck) -> GeometryReport:
    """Server-measured area/centroid for a geometry, or the reason it is rejected."""
    try:
        return validate_geometry(payload.geometry, declared_area_ha=payload.declared_area_ha)
    except IntakeError as exc:
        raise _unprocessable(exc.field, exc.message) from exc


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RecordOut)
async def create_record(
    payload: RecordSubmission,
    services: ServicesDep,
    session: SessionDep,
) -> RecordOut:
    """Register one submitted plot; start screening with ``POST /runs {record_id}``."""
    store = RunStore(session)
    try:
        row, record = await _create(store, payload, source="submitted")
    except IntakeError as exc:
        raise _unprocessable(exc.field, exc.message) from exc
    await session.commit()
    services.datasets.register(record)
    return await _record_out(store, row)


@router.get("", response_model=list[RecordOut])
async def list_records(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    source: Annotated[str | None, Query(pattern="^(submitted|import)$")] = None,
) -> list[RecordOut]:
    store = RunStore(session)
    return [
        await _record_out(store, row)
        for row in await store.list_submitted_records(limit=limit, offset=offset, source=source)
    ]


@router.get("/{record_id}", response_model=RecordOut)
async def get_record(record_id: str, session: SessionDep) -> RecordOut:
    store = RunStore(session)
    row = await store.get_submitted_record(record_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no submitted record {record_id!r}"
        )
    return await _record_out(store, row)


# -- bulk import ------------------------------------------------------------------


def _split(value: Any) -> list[str]:
    return [item.strip() for item in str(value or "").split(";") if item.strip()]


def _num(value: Any) -> float | None:
    text = str(value if value is not None else "").strip()
    number = float(text) if text else None
    if number is not None and not math.isfinite(number):
        raise IntakeError("row", "numeric values must be finite")
    return number


def _row_geometry(row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(row.get("geometry"), dict):
        return row["geometry"]
    text = str(row.get("wkt") or "").strip()
    if text:
        try:
            return dict(mapping(wkt.loads(text)))
        except (ShapelyError, ValueError) as exc:
            raise IntakeError("plot.geometry", f"unreadable WKT: {exc}") from exc
    lat, lon = _num(row.get("lat")), _num(row.get("lon"))
    if lat is None or lon is None:
        raise IntakeError("plot.geometry", "provide a wkt column, or lat and lon (with area_ha <= 4)")
    return {"type": "Point", "coordinates": [lon, lat]}


def _row_submission(row: dict[str, Any]) -> RecordSubmission:
    """Map one flat CSV row / GeoJSON feature to the intake model."""
    return RecordSubmission.model_validate(
        {
            "plot": {
                "geometry": _row_geometry(row),
                "country": row.get("country") or "",
                "label": row.get("label") or row.get("plot_label") or "",
                "province": row.get("province") or "",
                "kabupaten": row.get("kabupaten") or "",
                "declared_area_ha": _num(row.get("area_ha")),
            },
            "supplier": {
                "legal_name": row.get("legal_name") or row.get("supplier") or "",
                "trading_name": row.get("trading_name") or "",
                "group": row.get("group") or "",
                "nib": row.get("nib") or "",
                "npwp": row.get("npwp") or "",
                "certifications": _split(row.get("certifications")),
                "beneficial_owners": _split(row.get("beneficial_owners")),
            },
            "legality": {
                "permit_type": _text(row, "permit_type", "none").lower(),
                "permit_number": row.get("permit_number") or "",
                "permit_status": _text(row, "permit_status", "active").lower(),
                "permit_expiry": row.get("permit_expiry") or None,
                "declared_holder": row.get("declared_holder") or "",
                "concession_area_ha": _num(row.get("concession_area_ha")),
            },
            "consignment": {
                "commodity": _text(row, "commodity").lower(),
                "description": row.get("description") or "",
                "hs_heading": row.get("hs_heading") or "",
                "net_weight_kg": _num(row.get("net_weight_kg")),
                "harvest_year": _num(row.get("harvest_year")) or 0,
            },
        }
    )


def _text(row: dict[str, Any], field: str, default: str = "") -> str:
    value = row.get(field)
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        raise IntakeError(field, "must be text")
    return value.strip()


def _parse_rows(filename: str, content: bytes) -> list[dict[str, Any] | IntakeError]:
    text = content.decode("utf-8-sig")
    if filename.lower().endswith((".geojson", ".json")):
        payload = json.loads(text)
        features = (
            payload.get("features")
            if isinstance(payload, dict) and payload.get("type") == "FeatureCollection"
            else None
        )
        if not isinstance(features, list):
            raise _unprocessable("file", "GeoJSON import needs a FeatureCollection")
        rows: list[dict[str, Any] | IntakeError] = []
        for feature in features:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                rows.append(IntakeError("row", "must be a GeoJSON Feature"))
                continue
            properties = feature.get("properties")
            if properties is not None and not isinstance(properties, dict):
                rows.append(IntakeError("properties", "must be an object"))
                continue
            rows.append({**(properties or {}), "geometry": feature.get("geometry")})
        return rows
    dialect = csv.Sniffer().sniff(text.splitlines()[0] if text else ",", delimiters=",;\t")
    return [
        {str(key).strip().lower(): value for key, value in row.items() if key}
        for row in csv.DictReader(io.StringIO(text), dialect=dialect)
    ]


def _first_error(exc: ValidationError) -> tuple[str, str]:
    error = exc.errors()[0]
    return ".".join(str(part) for part in error["loc"]), str(error["msg"])


@router.post("/import", response_model=ImportResult)
async def import_records(
    services: ServicesDep,
    session: SessionDep,
    file: Annotated[
        UploadFile, File(description="CSV (wkt or lat/lon columns) or GeoJSON FeatureCollection")
    ],
) -> ImportResult:
    """Import a supplier portfolio; valid rows are created, invalid rows are reported."""
    limit = services.settings.import_max_bytes
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=f"file exceeds {limit // (1024 * 1024)} MB"
        )
    try:
        rows = _parse_rows(file.filename or "", content)
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
        raise _unprocessable("file", f"could not read the file: {exc}") from exc
    if len(rows) > MAX_IMPORT_ROWS:
        raise _unprocessable("file", f"{len(rows)} rows; import at most {MAX_IMPORT_ROWS} per file")

    store = RunStore(session)
    result = ImportResult(total_rows=len(rows))
    committed: list[BatchRecord] = []
    for index, row in enumerate(rows, start=1):
        try:
            if isinstance(row, IntakeError):
                raise row
            async with session.begin_nested():
                created, record = await _create(store, _row_submission(row), source="import")
        except IntakeError as exc:
            result.errors.append(ImportRowError(row=index, field=exc.field, message=exc.message))
            continue
        except ValidationError as exc:
            field, message = _first_error(exc)
            result.errors.append(ImportRowError(row=index, field=field, message=message))
            continue
        except (TypeError, ValueError) as exc:
            result.errors.append(ImportRowError(row=index, field="row", message=str(exc)))
            continue
        result.created.append(await _record_out(store, created))
        committed.append(record)
    await session.commit()
    for record in committed:
        services.datasets.register(record)
    return result


__all__ = ["router"]
