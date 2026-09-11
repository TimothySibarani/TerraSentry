"""Persistence for the run audit trail.

This is the deep module between the API/worker and SQLAlchemy: routers and the
run manager call these methods and never see a session, a JSON column, or a
mapper detail. Every write is idempotent where a replay is plausible (seed
upserts, step appends, result persistence).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from terrasentry_core.agents.schemas import AgentRunResult, ReviewDecision
from terrasentry_core.agents.verification import VerificationReport
from terrasentry_core.assessment.pipeline import RecordAssessment
from terrasentry_core.dds import DdsDocument as DdsPayload
from terrasentry_core.domain.enums import Decision, RunState
from terrasentry_core.domain.models import Assessment, Finding
from terrasentry_core.evidence import EvidenceEntry
from terrasentry_core.seed.schemas import (
    AmbiguityReason,
    Archetype,
    BatchRecord,
    ExpectedSignal,
)
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_core.tools.trace import TraceKind, TraceStep, utc_now

from terrasentry_api.models import (
    DdsDocument as DdsRow,
)
from terrasentry_api.models import (
    Evidence as EvidenceRow,
)
from terrasentry_api.models import (
    Parcel,
    Run,
    RunStep,
    RunVerdict,
    Supplier,
)


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; normalise so arithmetic stays valid."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _elapsed_seconds(started: datetime, finished: datetime) -> float:
    start = started if started.tzinfo is not None else started.replace(tzinfo=UTC)
    end = finished if finished.tzinfo is not None else finished.replace(tzinfo=UTC)
    return (end - start).total_seconds()


class RunStore:
    """One transactional view over the audit tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    # -- seed -----------------------------------------------------------------

    async def count_suppliers(self) -> int:
        return int(await self._session.scalar(select(func.count()).select_from(Supplier)) or 0)

    async def seed_suppliers_and_parcels(self, datasets: SeedDatasets) -> int:
        """Upsert the seed suppliers/parcels; returns the number of parcels seen."""
        supplier_ids = set((await self._session.scalars(select(Supplier.supplier_id))).all())
        parcel_ids = set((await self._session.scalars(select(Parcel.polygon_id))).all())
        for record in datasets.records:
            legality = record.legality
            if legality.supplier_id not in supplier_ids:
                self._session.add(Supplier(**legality.model_dump()))
                supplier_ids.add(legality.supplier_id)
            polygon = record.polygon
            if polygon.id not in parcel_ids:
                self._session.add(
                    Parcel(
                        polygon_id=polygon.id,
                        supplier_id=record.supplier_id,
                        label=polygon.label,
                        region=polygon.region,
                        province=polygon.province,
                        area_ha=polygon.area_ha,
                        centroid_lat=polygon.centroid_lat,
                        centroid_lon=polygon.centroid_lon,
                        geometry=polygon.geometry,
                        archetype=polygon.archetype,
                        scenario=polygon.scenario,
                        is_demo=polygon.is_demo,
                    )
                )
                parcel_ids.add(polygon.id)
        await self._session.flush()
        return len(parcel_ids)

    # -- suppliers ------------------------------------------------------------

    async def list_suppliers(self, *, limit: int = 100, offset: int = 0) -> list[Supplier]:
        result = await self._session.scalars(
            select(Supplier).order_by(Supplier.supplier_id).limit(limit).offset(offset)
        )
        return list(result)

    async def get_supplier(self, supplier_id: str) -> Supplier | None:
        return await self._session.scalar(
            select(Supplier)
            .where(Supplier.supplier_id == supplier_id)
            .options(selectinload(Supplier.parcels))
        )

    # -- runs -----------------------------------------------------------------

    async def create_run(
        self,
        *,
        run_id: str,
        kind: str,
        model: str = "scripted",
        record: BatchRecord | None = None,
        parent_run_id: str | None = None,
        state: RunState = RunState.QUEUED,
        metrics: dict[str, Any] | None = None,
    ) -> Run:
        row = Run(
            id=run_id,
            kind=kind,
            parent_run_id=parent_run_id,
            record_id=record.record_id if record is not None else None,
            supplier_id=record.supplier_id if record is not None else None,
            polygon_id=record.polygon.id if record is not None else None,
            state=state,
            model=model,
            metrics=metrics or {},
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_run(self, run_id: str) -> Run | None:
        return await self._session.get(Run, run_id)

    async def list_runs(
        self,
        *,
        kind: str | None = None,
        parent_run_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Run]:
        statement = select(Run).order_by(Run.created_at.desc(), Run.id.desc())
        if kind is not None:
            statement = statement.where(Run.kind == kind)
        if parent_run_id is not None:
            statement = statement.where(Run.parent_run_id == parent_run_id)
        result = await self._session.scalars(statement.limit(limit).offset(offset))
        return list(result)

    async def set_state(
        self,
        run_id: str,
        state: RunState,
        *,
        summary: str | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        elapsed_seconds: float | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> Run | None:
        run = await self.get_run(run_id)
        if run is None:
            return None
        run.state = state
        if summary is not None:
            run.summary = summary
        if error is not None:
            run.error = error
        if started_at is not None:
            run.started_at = started_at
        if finished_at is not None:
            run.finished_at = finished_at
        if elapsed_seconds is not None:
            run.elapsed_seconds = elapsed_seconds
        if metrics is not None:
            run.metrics = metrics
        await self._session.flush()
        return run

    # -- steps ----------------------------------------------------------------

    async def append_step(self, run_id: str, step: TraceStep, seq: int) -> bool:
        """Insert one step; a replayed ``step_id`` is ignored. Returns True when new."""
        exists = await self._session.scalar(
            select(RunStep.id).where(RunStep.run_id == run_id, RunStep.step_id == step.step_id)
        )
        if exists is not None:
            return False
        self._session.add(
            RunStep(
                run_id=run_id,
                step_id=step.step_id,
                seq=seq,
                kind=step.kind,
                name=step.name,
                detail=step.detail,
                at=step.at,
                payload=step.payload,
            )
        )
        await self._session.flush()
        return True

    async def list_steps(self, run_id: str) -> list[RunStep]:
        result = await self._session.scalars(
            select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.seq)
        )
        return list(result)

    async def step_count(self, run_id: str) -> int:
        count = await self._session.scalar(
            select(func.count()).select_from(RunStep).where(RunStep.run_id == run_id)
        )
        return int(count or 0)

    # -- verdict / evidence / dds ---------------------------------------------

    async def persist_result(self, result: AgentRunResult) -> None:
        """Write the run fields plus the verdict/evidence/DDS of an agent result."""
        run = await self.get_run(result.run_id)
        if run is None:
            return
        run.state = result.state
        run.summary = result.summary
        run.disclosures = result.disclosures
        run.started_at = result.started_at
        run.finished_at = result.finished_at
        run.elapsed_seconds = _elapsed_seconds(result.started_at, result.finished_at)
        if result.verification is not None:
            run.verification = result.verification.model_dump(mode="json")
        if result.state is RunState.FAILED and result.summary:
            run.error = result.summary

        assessment = result.assessment or result.pending_assessment
        if assessment is not None:
            await self._upsert_verdict(result.run_id, assessment, pending=result.assessment is None)
            await self._upsert_dds(result.run_id, assessment, released=result.assessment is not None)
            await self._insert_evidence(result.run_id, assessment.evidence)

        if result.review is not None:
            run.review_decision = result.review.decision.value
            run.review_reviewer = result.review.reviewer
            run.review_note = result.review.note
            run.reviewed_at = result.finished_at
        await self._session.flush()

    async def _upsert_verdict(
        self, run_id: str, assessment: RecordAssessment, *, pending: bool
    ) -> RunVerdict:
        row = await self._session.scalar(select(RunVerdict).where(RunVerdict.run_id == run_id))
        values: dict[str, Any] = {
            "record_id": assessment.record_id,
            "supplier_id": assessment.supplier_id,
            "polygon_id": assessment.polygon_id,
            "rubric_version": assessment.assessment.rubric_version,
            "score": assessment.assessment.score,
            "verdict": assessment.assessment.verdict,
            "risk_level": assessment.assessment.risk_level,
            "fingerprint": assessment.fingerprint,
            "findings": [finding.model_dump(mode="json") for finding in assessment.assessment.findings],
            "citations": assessment.assessment.citations,
            "disclosures": assessment.assessment.disclosures,
            "data_gaps": assessment.assessment.data_gaps,
            "expected_archetype": assessment.expected_archetype,
            "expected_signal": assessment.expected_signal,
            "expected_ambiguity": assessment.expected_ambiguity,
            "pending": pending,
        }
        if row is None:
            row = RunVerdict(run_id=run_id, **values)
            self._session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        return row

    async def _upsert_dds(self, run_id: str, assessment: RecordAssessment, *, released: bool) -> DdsRow:
        row = await self._session.scalar(select(DdsRow).where(DdsRow.run_id == run_id))
        document = assessment.dds.model_dump(mode="json", by_alias=True)
        xml = assessment.dds.to_xml()
        if row is None:
            row = DdsRow(run_id=run_id, document=document, xml=xml, released=released)
            self._session.add(row)
        else:
            row.document = document
            row.xml = xml
            row.released = released
        return row

    async def _insert_evidence(self, run_id: str, entries: list[EvidenceEntry]) -> None:
        existing = set(
            (
                await self._session.scalars(
                    select(EvidenceRow.evidence_id).where(EvidenceRow.run_id == run_id)
                )
            ).all()
        )
        for entry in entries:
            if entry.evidence_id in existing:
                continue
            self._session.add(
                EvidenceRow(
                    run_id=run_id,
                    evidence_id=entry.evidence_id,
                    schema_version=entry.schema_version,
                    claim=entry.claim,
                    value=entry.value,
                    unit=entry.unit,
                    source=str(entry.source),
                    artifact=entry.artifact,
                    retrieved_at=entry.retrieved_at,
                    cached=entry.cached,
                    synthetic=entry.synthetic,
                    disclosure=entry.disclosure,
                )
            )
            existing.add(entry.evidence_id)

    async def get_verdict(self, run_id: str) -> RunVerdict | None:
        return await self._session.scalar(select(RunVerdict).where(RunVerdict.run_id == run_id))

    async def get_dds(self, run_id: str) -> DdsRow | None:
        return await self._session.scalar(select(DdsRow).where(DdsRow.run_id == run_id))

    async def release_dds(self, run_id: str) -> None:
        """Approve a pending verdict and release its DDS (HITL decision)."""
        verdict = await self.get_verdict(run_id)
        if verdict is not None:
            verdict.pending = False
        dds = await self.get_dds(run_id)
        if dds is not None:
            dds.released = True
        await self._session.flush()

    async def list_evidence(self, run_id: str) -> list[EvidenceRow]:
        result = await self._session.scalars(
            select(EvidenceRow).where(EvidenceRow.run_id == run_id).order_by(EvidenceRow.evidence_id)
        )
        return list(result)

    # -- reconstruction ---------------------------------------------------------

    async def load_result(self, run_id: str) -> AgentRunResult | None:
        """Rebuild the M3 result from persisted rows (used by the HITL resume path)."""
        run = await self.get_run(run_id)
        if run is None:
            return None
        steps = await self.list_steps(run_id)
        verification = VerificationReport.model_validate(run.verification) if run.verification else None
        assessment: RecordAssessment | None = None
        pending: RecordAssessment | None = None
        verdict = await self.get_verdict(run_id)
        if verdict is not None:
            record = await self._record_assessment(verdict, await self.get_dds(run_id))
            if verdict.pending:
                pending = record
            else:
                assessment = record
        review = None
        if run.review_decision is not None:
            review = ReviewDecision(
                decision=Decision(run.review_decision),
                reviewer=run.review_reviewer or "human",
                note=run.review_note or "",
            )
        return AgentRunResult(
            run_id=run.id,
            record_id=run.record_id or "",
            supplier_id=run.supplier_id or "",
            polygon_id=run.polygon_id or "",
            state=run.state,
            summary=run.summary,
            verification=verification,
            assessment=assessment,
            pending_assessment=pending,
            trace=[
                TraceStep(
                    step_id=step.step_id,
                    kind=cast(TraceKind, step.kind),
                    name=step.name,
                    detail=step.detail,
                    at=_as_utc(step.at) or utc_now(),
                    payload=step.payload,
                )
                for step in steps
            ],
            disclosures=run.disclosures,
            started_at=_as_utc(run.started_at) or _as_utc(run.created_at) or utc_now(),
            finished_at=_as_utc(run.finished_at) or _as_utc(run.created_at) or utc_now(),
            review=review,
        )

    async def _record_assessment(self, verdict: RunVerdict, dds: DdsRow | None) -> RecordAssessment:
        assessment = Assessment(
            record_id=verdict.record_id,
            supplier_id=verdict.supplier_id,
            polygon_id=verdict.polygon_id,
            rubric_version=verdict.rubric_version,
            score=verdict.score,
            verdict=verdict.verdict,
            risk_level=verdict.risk_level,
            findings=[Finding.model_validate(finding) for finding in verdict.findings],
            citations=verdict.citations,
            disclosures=verdict.disclosures,
            data_gaps=verdict.data_gaps,
        )
        evidence = [
            EvidenceEntry.model_validate(
                {
                    "schema_version": row.schema_version,
                    "evidence_id": row.evidence_id,
                    "claim": row.claim,
                    "value": row.value,
                    "unit": row.unit,
                    "source": row.source,
                    "artifact": row.artifact,
                    "retrieved_at": _as_utc(row.retrieved_at),
                    "cached": row.cached,
                    "synthetic": row.synthetic,
                    "disclosure": row.disclosure,
                }
            )
            for row in await self.list_evidence(verdict.run_id)
        ]
        payload = DdsPayload.model_validate(dds.document) if dds is not None else None
        if payload is None:
            raise ValueError(f"run {verdict.run_id!r} has a verdict but no persisted DDS")
        return RecordAssessment(
            record_id=verdict.record_id,
            supplier_id=verdict.supplier_id,
            polygon_id=verdict.polygon_id,
            expected_archetype=cast(Archetype, verdict.expected_archetype),
            expected_signal=cast(ExpectedSignal | None, verdict.expected_signal),
            expected_ambiguity=cast(AmbiguityReason | None, verdict.expected_ambiguity),
            run_state=RunState.AWAITING_REVIEW if verdict.pending else RunState.COMPLETE,
            assessment=assessment,
            dds=payload,
            fingerprint=verdict.fingerprint,
            evidence=evidence,
        )

    # -- batch ------------------------------------------------------------------

    async def batch_state_counts(self, parent_run_id: str) -> dict[str, int]:
        rows = await self._session.execute(
            select(Run.state, func.count()).where(Run.parent_run_id == parent_run_id).group_by(Run.state)
        )
        counts = {state.value: 0 for state in RunState}
        for state, count in rows.all():
            counts[str(state)] = int(count)
        return counts

    async def batch_verdict_breakdown(self, parent_run_id: str) -> dict[str, int]:
        rows = await self._session.execute(
            select(RunVerdict.verdict, func.count())
            .join(Run, Run.id == RunVerdict.run_id)
            .where(Run.parent_run_id == parent_run_id)
            .group_by(RunVerdict.verdict)
        )
        breakdown = {"compliant": 0, "high_risk": 0, "ambiguous": 0}
        for verdict, count in rows.all():
            breakdown[str(verdict)] = int(count)
        return breakdown

    async def batch_average_seconds(self, parent_run_id: str) -> float:
        average = await self._session.scalar(
            select(func.avg(Run.elapsed_seconds)).where(Run.parent_run_id == parent_run_id)
        )
        return round(float(average), 3) if average is not None else 0.0


__all__ = ["RunStore"]
