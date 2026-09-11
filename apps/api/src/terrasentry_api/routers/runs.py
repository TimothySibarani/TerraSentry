"""Run lifecycle endpoints: start, list, inspect, stream, and review."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from terrasentry_core.agents.schemas import ReviewDecision
from terrasentry_core.domain.enums import Decision
from terrasentry_core.errors import InvalidReviewDecisionError, SeedLookupError
from terrasentry_core.evidence import EvidenceEntry
from terrasentry_core.tools.trace import TraceKind, TraceStep

from terrasentry_api.schemas import DecisionCreate, RunCreate, RunDetail, RunSummary
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
    try:
        run_id = await services.run_manager.start_run(
            record_id=payload.record_id,
            scenario=payload.scenario,
            model=payload.model or services.settings.agent_model,
            refresh=payload.refresh,
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
    parent_run_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunSummary]:
    store = RunStore(session)
    runs = await store.list_runs(kind=kind, parent_run_id=parent_run_id, limit=limit, offset=offset)
    summaries: list[RunSummary] = []
    for run in runs:
        verdict = await store.get_verdict(run.id)
        summaries.append(RunSummary.from_row(run, verdict=verdict, step_count=await store.step_count(run.id)))
    return summaries


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


__all__ = ["router"]
