"""Request/response models for the public API.

These are the OpenAPI contract: routers build them from the audit rows and the
generated TypeScript client mirrors them. Nested domain payloads (assessment,
verification, trace steps, evidence) come straight from the deterministic core
so the API cannot drift from the engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from terrasentry_core.agents.verification import VerificationReport
from terrasentry_core.domain.enums import RunState, Verdict
from terrasentry_core.domain.models import Assessment, Finding
from terrasentry_core.tools.trace import TraceStep
from terrasentry_integrations.sap import VendorStatus

from terrasentry_api.models import DdsDocument as DdsRow
from terrasentry_api.models import Parcel as ParcelRow
from terrasentry_api.models import Run, RunVerdict
from terrasentry_api.models import SapAction as SapActionRow
from terrasentry_api.models import Supplier as SupplierRow
from terrasentry_api.sap_actions import disclosure_for_mode

ModelMode = Literal["scripted", "bedrock"]


def _opt_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


class HealthResponse(BaseModel):
    """Process health plus the offline-rehearsal and SAP-mode state the cockpit badges."""

    status: str
    offline: bool = False
    fixtures_loaded: int = 0
    sap_mode: str = "stub"
    sap_real: bool = False


class RunCreate(BaseModel):
    """Start one scenario run for a seed record or a named demo scenario."""

    record_id: str | None = None
    scenario: str | None = None
    model: ModelMode | None = None
    refresh: bool = False

    @model_validator(mode="after")
    def _exactly_one_target(self) -> RunCreate:
        if bool(self.record_id) == bool(self.scenario):
            raise ValueError("provide exactly one of record_id or scenario")
        return self


class DecisionCreate(BaseModel):
    """Record the human decision on an ``awaiting_review`` run."""

    decision: Literal["approve", "override"]
    reviewer: str = "human"
    note: str = ""


class BatchCreate(BaseModel):
    """Queue a deterministic batch run over the seed records."""

    size: int = Field(default=50, ge=1, le=50)
    refresh: bool = False


class ReviewOut(BaseModel):
    decision: str
    reviewer: str
    note: str = ""
    reviewed_at: datetime | None = None


class VerdictOut(BaseModel):
    """The deterministic assessment of one record, pending or released."""

    record_id: str
    supplier_id: str
    polygon_id: str
    run_state: RunState
    expected_archetype: str
    expected_signal: str | None = None
    expected_ambiguity: str | None = None
    fingerprint: str
    pending: bool
    assessment: Assessment

    @classmethod
    def from_row(cls, row: RunVerdict) -> VerdictOut:
        return cls(
            record_id=row.record_id,
            supplier_id=row.supplier_id,
            polygon_id=row.polygon_id,
            run_state=RunState.AWAITING_REVIEW if row.pending else RunState.COMPLETE,
            expected_archetype=row.expected_archetype,
            expected_signal=row.expected_signal,
            expected_ambiguity=row.expected_ambiguity,
            fingerprint=row.fingerprint,
            pending=row.pending,
            assessment=Assessment(
                record_id=row.record_id,
                supplier_id=row.supplier_id,
                polygon_id=row.polygon_id,
                rubric_version=row.rubric_version,
                score=row.score,
                verdict=row.verdict,
                risk_level=row.risk_level,
                findings=[Finding.model_validate(finding) for finding in row.findings],
                citations=row.citations,
                disclosures=row.disclosures,
                data_gaps=row.data_gaps,
            ),
        )


class DdsMeta(BaseModel):
    """Presence and release state of the DDS; the document lives at /dds/{run_id}."""

    released: bool
    schema_version: str
    created_at: datetime

    @classmethod
    def from_row(cls, row: DdsRow) -> DdsMeta:
        return cls(
            released=row.released,
            schema_version=str(row.document.get("schemaVersion", "")),
            created_at=row.created_at,
        )


class RunSummary(BaseModel):
    """One run row as it appears in list views and the cockpit table."""

    run_id: str
    kind: str
    state: RunState
    record_id: str | None = None
    supplier_id: str | None = None
    polygon_id: str | None = None
    parent_run_id: str | None = None
    model: str
    summary: str = ""
    error: str | None = None
    verdict: Verdict | None = None
    score: int | None = None
    expected_archetype: str | None = None
    step_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_seconds: float | None = None
    created_at: datetime
    metrics: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_row(
        cls,
        run: Run,
        *,
        verdict: RunVerdict | None = None,
        step_count: int = 0,
    ) -> RunSummary:
        return cls(
            run_id=run.id,
            kind=run.kind,
            state=run.state,
            record_id=run.record_id,
            supplier_id=run.supplier_id,
            polygon_id=run.polygon_id,
            parent_run_id=run.parent_run_id,
            model=run.model,
            summary=run.summary,
            error=run.error,
            verdict=verdict.verdict if verdict is not None else None,
            score=verdict.score if verdict is not None else None,
            expected_archetype=verdict.expected_archetype if verdict is not None else None,
            step_count=step_count,
            started_at=run.started_at,
            finished_at=run.finished_at,
            elapsed_seconds=run.elapsed_seconds,
            created_at=run.created_at,
            metrics=run.metrics,
        )


class RunDetail(RunSummary):
    """Full dossier: trace, verification, assessment, review, SAP action, and DDS metadata."""

    disclosures: list[str] = Field(default_factory=list)
    verification: VerificationReport | None = None
    assessment: VerdictOut | None = None
    pending_assessment: VerdictOut | None = None
    review: ReviewOut | None = None
    sap_action: SapActionOut | None = None
    steps: list[TraceStep] = Field(default_factory=list)
    dds: DdsMeta | None = None

    @classmethod
    def from_parts(
        cls,
        run: Run,
        *,
        verdict: RunVerdict | None,
        dds: DdsRow | None,
        steps: list[TraceStep],
        sap_action: SapActionRow | None = None,
    ) -> RunDetail:
        summary = RunSummary.from_row(run, verdict=verdict, step_count=len(steps))
        review = None
        if run.review_decision is not None:
            review = ReviewOut(
                decision=run.review_decision,
                reviewer=run.review_reviewer or "human",
                note=run.review_note or "",
                reviewed_at=run.reviewed_at,
            )
        verdict_out = VerdictOut.from_row(verdict) if verdict is not None else None
        return cls(
            **summary.model_dump(),
            disclosures=run.disclosures,
            verification=(VerificationReport.model_validate(run.verification) if run.verification else None),
            assessment=verdict_out if verdict_out is not None and not verdict_out.pending else None,
            pending_assessment=(verdict_out if verdict_out is not None and verdict_out.pending else None),
            review=review,
            sap_action=SapActionOut.from_row(sap_action) if sap_action is not None else None,
            steps=steps,
            dds=DdsMeta.from_row(dds) if dds is not None else None,
        )


class BatchSummary(BaseModel):
    """Aggregate throughput view over one batch parent run."""

    run_id: str
    state: RunState
    record_count: int
    states: dict[str, int] = Field(default_factory=dict)
    verdict_breakdown: dict[str, int] = Field(default_factory=dict)
    expected_breakdown: dict[str, int] = Field(default_factory=dict)
    wall_clock_seconds: float | None = None
    average_seconds_per_record: float | None = None
    median_seconds_per_record: float | None = None
    p95_seconds_per_record: float | None = None
    throughput_records_per_second: float | None = None
    total_record_seconds: float | None = None
    cache_stats: dict[str, int] | None = None
    confusion: dict[str, dict[str, int]] = Field(default_factory=dict)
    batch_concurrency: int | None = None
    sap_actions: dict[str, int] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_run(
        cls,
        run: Run,
        *,
        states: dict[str, int],
        breakdown: dict[str, int],
        average_seconds: float,
    ) -> BatchSummary:
        metrics = run.metrics or {}
        confusion = metrics.get("confusion")
        cache_stats = metrics.get("cache_stats")
        concurrency = metrics.get("batch_concurrency")
        sap_actions = metrics.get("sap_actions")
        return cls(
            run_id=run.id,
            state=run.state,
            record_count=int(metrics.get("record_count", 0)) or sum(states.values()),
            states=states,
            verdict_breakdown=breakdown,
            expected_breakdown=metrics.get("expected_breakdown", {}),
            wall_clock_seconds=run.elapsed_seconds,
            average_seconds_per_record=average_seconds,
            median_seconds_per_record=_opt_float(metrics.get("median_seconds_per_record")),
            p95_seconds_per_record=_opt_float(metrics.get("p95_seconds_per_record")),
            throughput_records_per_second=_opt_float(metrics.get("throughput_records_per_second")),
            total_record_seconds=_opt_float(metrics.get("total_record_seconds")),
            cache_stats=cache_stats if isinstance(cache_stats, dict) else None,
            confusion=confusion if isinstance(confusion, dict) else {},
            batch_concurrency=int(concurrency) if isinstance(concurrency, (int, float)) else None,
            sap_actions=sap_actions if isinstance(sap_actions, dict) else {},
            started_at=run.started_at,
            finished_at=run.finished_at,
            metrics=metrics,
        )


class ParcelOut(BaseModel):
    polygon_id: str
    supplier_id: str
    label: str
    region: str
    province: str
    area_ha: float
    centroid_lat: float
    centroid_lon: float
    geometry: dict[str, Any]
    archetype: str
    scenario: str | None = None
    is_demo: bool

    @classmethod
    def from_row(cls, row: ParcelRow) -> ParcelOut:
        return cls(
            polygon_id=row.polygon_id,
            supplier_id=row.supplier_id,
            label=row.label,
            region=row.region,
            province=row.province,
            area_ha=row.area_ha,
            centroid_lat=row.centroid_lat,
            centroid_lon=row.centroid_lon,
            geometry=row.geometry,
            archetype=row.archetype,
            scenario=row.scenario,
            is_demo=row.is_demo,
        )


class SupplierOut(BaseModel):
    supplier_id: str
    legal_name: str
    trading_name: str
    group: str
    nib: str
    npwp: str
    hgu_number: str | None = None
    pbp_number: str | None = None
    permit_status: str
    concession_area_ha: float
    province: str
    kabupaten: str
    beneficial_owners: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    sanctions: list[str] = Field(default_factory=list)
    synthetic: bool
    disclosure: str = ""

    @classmethod
    def from_row(cls, row: SupplierRow) -> SupplierOut:
        return cls(
            supplier_id=row.supplier_id,
            legal_name=row.legal_name,
            trading_name=row.trading_name,
            group=row.group,
            nib=row.nib,
            npwp=row.npwp,
            hgu_number=row.hgu_number,
            pbp_number=row.pbp_number,
            permit_status=row.permit_status,
            concession_area_ha=row.concession_area_ha,
            province=row.province,
            kabupaten=row.kabupaten,
            beneficial_owners=row.beneficial_owners,
            certifications=row.certifications,
            sanctions=row.sanctions,
            synthetic=row.synthetic,
            disclosure=row.disclosure,
        )


class SapActionOut(BaseModel):
    """One recorded ERP action from the M7 closed loop."""

    run_id: str
    supplier_id: str
    vendor_id: str
    mode: str
    status: str
    purchasing_block: bool
    real: bool
    external_reference: str | None = None
    error: str | None = None
    performed_at: datetime

    @classmethod
    def from_row(cls, row: SapActionRow) -> SapActionOut:
        return cls(
            run_id=row.run_id,
            supplier_id=row.supplier_id,
            vendor_id=row.vendor_id,
            mode=row.mode,
            status=row.status,
            purchasing_block=row.purchasing_block,
            real=row.real,
            external_reference=row.external_reference,
            error=row.error,
            performed_at=row.performed_at,
        )


class SupplierSapOut(BaseModel):
    """Current ERP state for one supplier plus its most recent action, if any."""

    vendor_id: str
    status: str
    purchasing_block: bool
    mode: str
    real: bool
    disclosure: str
    last_action: SapActionOut | None = None

    @classmethod
    def from_parts(
        cls,
        supplier_id: str,
        *,
        current: VendorStatus | None,
        last_action: SapActionRow | None,
        mode: str,
        real: bool,
    ) -> SupplierSapOut:
        vendor = current or VendorStatus(vendor_id=supplier_id)
        return cls(
            vendor_id=vendor.vendor_id,
            status=vendor.status,
            purchasing_block=vendor.purchasing_block,
            mode=mode,
            real=real,
            disclosure=disclosure_for_mode(mode),
            last_action=SapActionOut.from_row(last_action) if last_action is not None else None,
        )


class SupplierDetail(SupplierOut):
    parcels: list[ParcelOut] = Field(default_factory=list)
    sap: SupplierSapOut | None = None


class SapVendorOut(BaseModel):
    vendor_id: str
    status: str
    purchasing_block: bool

    @classmethod
    def from_vendor(cls, vendor: VendorStatus) -> SapVendorOut:
        return cls(
            vendor_id=vendor.vendor_id,
            status=vendor.status,
            purchasing_block=vendor.purchasing_block,
        )


class SapStatusIn(BaseModel):
    status: str = Field(min_length=1, max_length=32)


class SapBlockIn(BaseModel):
    blocked: bool


__all__ = [
    "BatchCreate",
    "BatchSummary",
    "DdsMeta",
    "DecisionCreate",
    "ParcelOut",
    "ReviewOut",
    "RunCreate",
    "RunDetail",
    "RunSummary",
    "SapActionOut",
    "SapBlockIn",
    "SapStatusIn",
    "SapVendorOut",
    "SupplierDetail",
    "SupplierOut",
    "SupplierSapOut",
    "VerdictOut",
]
