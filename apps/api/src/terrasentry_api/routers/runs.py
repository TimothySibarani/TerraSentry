"""Run lifecycle endpoints: start, list, inspect, stream, and review."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from terrasentry_core.agents.factory import FAULT_SCENARIOS
from terrasentry_core.agents.schemas import ReviewDecision
from terrasentry_core.domain.enums import Decision, RunState, Verdict
from terrasentry_core.errors import InvalidReviewDecisionError, SeedLookupError
from terrasentry_core.evidence import EvidenceEntry
from terrasentry_core.tools.trace import TraceKind, TraceStep

from terrasentry_api.schemas import DecisionCreate, RunCreate, RunDetail, RunSummary, SapActionOut
from terrasentry_api.services import AppServices, get_services, get_session
from terrasentry_api.sse import event_source_response
from terrasentry_api.store import RunStore

router = APIRouter(prefix="/runs", tags=["runs"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[AppServices, Depends(get_services)]


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=RunSummary)
async def create_run(
    payload: RunCreate,
    services: ServicesDep,
    session: SessionDep,
) -> RunSummary:
    """Start the supervisor -> specialists -> verifier graph for one seed record."""
    model = payload.model or services.settings.agent_model
    if payload.scenario in FAULT_SCENARIOS and model != "scripted":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"scenario {payload.scenario!r} is scripted fault injection and cannot run on {model!r}",
        )
    try:
        run_id = await services.run_manager.start_run(
            record_id=payload.record_id,
            scenario=payload.scenario,
            model=model,
            refresh=payload.refresh,
            erp_mode=payload.erp_mode,
        )
    except SeedLookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    store = RunStore(session)
    run = await store.get_run(run_id)
    if run is None:  # pragma: no cover - the run was just created
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="run lost")
    return RunSummary.from_row(run)


@router.get("", response_model=list[RunSummary])
async def list_runs(
    session: SessionDep,
    kind: Annotated[str | None, Query()] = None,
    state: Annotated[RunState | None, Query(description="Only runs in this state")] = None,
    parent_run_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunSummary]:
    store = RunStore(session)
    runs = await store.list_runs(
        kind=kind, state=state, parent_run_id=parent_run_id, limit=limit, offset=offset
    )
    ids = [run.id for run in runs]
    verdicts = await store.verdicts_for(ids)
    counts = await store.step_counts(ids)
    return [
        RunSummary.from_row(run, verdict=verdicts.get(run.id), step_count=counts.get(run.id, 0))
        for run in runs
    ]


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, session: SessionDep) -> RunDetail:
    store = RunStore(session)
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no run {run_id!r}")
    steps = [
        TraceStep(
            step_id=row.step_id,
            kind=cast(TraceKind, row.kind),
            name=row.name,
            detail=row.detail,
            at=row.at,
            payload=row.payload,
        )
        for row in await store.list_steps(run_id)
    ]
    return RunDetail.from_parts(
        run,
        verdict=await store.get_verdict(run_id),
        dds=await store.get_dds(run_id),
        steps=steps,
        sap_action=await store.get_sap_action(run_id),
    )


@router.get("/{run_id}/evidence", response_model=list[EvidenceEntry])
async def get_evidence(run_id: str, session: SessionDep) -> list[EvidenceEntry]:
    store = RunStore(session)
    if await store.get_run(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no run {run_id!r}")
    rows = await store.list_evidence(run_id)
    return [
        EvidenceEntry.model_validate(
            {
                "schema_version": row.schema_version,
                "evidence_id": row.evidence_id,
                "claim": row.claim,
                "value": row.value,
                "unit": row.unit,
                "source": row.source,
                "artifact": row.artifact,
                "retrieved_at": row.retrieved_at,
                "cached": row.cached,
                "synthetic": row.synthetic,
                "provenance": row.provenance,
                "disclosure": row.disclosure,
            }
        )
        for row in rows
    ]


@router.get("/{run_id}/stream")
async def stream_run(run_id: str, services: ServicesDep, session: SessionDep) -> EventSourceResponse:
    """SSE stream of ``snapshot``, ``step``, ``state``, and ``done`` events."""
    store = RunStore(session)
    if await store.get_run(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no run {run_id!r}")
    return event_source_response(
        services.run_manager,
        run_id,
        ping=services.settings.sse_ping_seconds,
    )


@router.post("/{run_id}/decision", response_model=RunSummary)
async def decide_run(
    run_id: str,
    payload: DecisionCreate,
    services: ServicesDep,
    session: SessionDep,
) -> RunSummary:
    """Approve or override an ambiguous run and release (or keep) its DDS."""
    store = RunStore(session)
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no run {run_id!r}")
    held = await store.get_verdict(run_id)
    if (
        payload.decision == "approve"
        and held is not None
        and held.verdict is Verdict.HIGH_RISK
        and not payload.note.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="approving a high-risk supplier contradicts the rubric; a note explaining why is required",
        )
    try:
        resumed = await services.run_manager.decide(
            run_id,
            ReviewDecision(
                decision=Decision(payload.decision),
                reviewer=payload.reviewer,
                note=payload.note,
            ),
        )
    except InvalidReviewDecisionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.refresh(run)
    verdict = await store.get_verdict(run_id)
    return RunSummary.from_row(run, verdict=verdict, step_count=len(resumed.trace))


@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED, response_model=RunSummary)
async def cancel_run(run_id: str, services: ServicesDep, session: SessionDep) -> RunSummary:
    """Stop a run or batch that is executing and mark it failed; 409 when nothing is running."""
    store = RunStore(session)
    if await store.get_run(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no run {run_id!r}")
    await services.run_manager.cancel_run(run_id)
    session.expire_all()
    run = await store.get_run(run_id)
    if run is None:  # pragma: no cover - the run exists
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no run {run_id!r}")
    return RunSummary.from_row(run)


@router.post("/{run_id}/erp-action", response_model=SapActionOut)
async def confirm_erp_action(run_id: str, services: ServicesDep) -> SapActionOut:
    """Apply the ERP action a finished run is waiting on (``confirm`` mode, or a retry after a failure)."""
    action = await services.run_manager.confirm_erp_action(run_id)
    return SapActionOut(
        run_id=action.run_id,
        supplier_id=action.supplier_id,
        vendor_id=action.vendor_id,
        mode=action.mode,
        status=action.status,
        purchasing_block=action.purchasing_block,
        real=action.real,
        external_reference=action.external_reference,
        error=action.error,
        performed_at=action.performed_at,
    )


__all__ = ["router"]
