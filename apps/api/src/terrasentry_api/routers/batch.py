"""Batch endpoints: queue the 50-record run, inspect metrics, follow progress."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from terrasentry_api.schemas import BatchCreate, BatchSummary, RunSummary
from terrasentry_api.services import AppServices, get_services, get_session
from terrasentry_api.sse import event_source_response
from terrasentry_api.store import RunStore

router = APIRouter(prefix="/batch-runs", tags=["batch"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[AppServices, Depends(get_services)]


async def _summary(store: RunStore, batch_run_id: str) -> BatchSummary:
    run = await store.get_run(batch_run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no batch run {batch_run_id!r}")
    return BatchSummary.from_run(
        run,
        states=await store.batch_state_counts(batch_run_id),
        breakdown=await store.batch_verdict_breakdown(batch_run_id),
        average_seconds=await store.batch_average_seconds(batch_run_id),
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=BatchSummary)
async def create_batch(
    payload: BatchCreate,
    services: ServicesDep,
    session: SessionDep,
) -> BatchSummary:
    """Queue a batch; records run concurrently on the deterministic assess path."""
    batch_run_id = await services.run_manager.start_batch(
        size=payload.size,
        refresh=payload.refresh,
    )
    return await _summary(RunStore(session), batch_run_id)


@router.get("", response_model=list[BatchSummary])
async def list_batch_runs(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BatchSummary]:
    store = RunStore(session)
    runs = await store.list_runs(kind="batch", limit=limit, offset=offset)
    return [
        BatchSummary.from_run(
            run,
            states=await store.batch_state_counts(run.id),
            breakdown=await store.batch_verdict_breakdown(run.id),
            average_seconds=await store.batch_average_seconds(run.id),
        )
        for run in runs
    ]


@router.get("/{batch_run_id}", response_model=BatchSummary)
async def get_batch_run(batch_run_id: str, session: SessionDep) -> BatchSummary:
    return await _summary(RunStore(session), batch_run_id)


@router.get("/{batch_run_id}/records", response_model=list[RunSummary])
async def list_batch_records(batch_run_id: str, session: SessionDep) -> list[RunSummary]:
    store = RunStore(session)
    if await store.get_run(batch_run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no batch run {batch_run_id!r}")
    runs = await store.list_runs(parent_run_id=batch_run_id, limit=200)
    summaries: list[RunSummary] = []
    for run in runs:
        summaries.append(
            RunSummary.from_row(
                run,
                verdict=await store.get_verdict(run.id),
                step_count=await store.step_count(run.id),
            )
        )
    return summaries


@router.get("/{batch_run_id}/stream")
async def stream_batch_run(
    batch_run_id: str,
    services: ServicesDep,
    session: SessionDep,
) -> EventSourceResponse:
    """SSE stream of ``progress`` events and a terminal ``done`` event."""
    store = RunStore(session)
    if await store.get_run(batch_run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no batch run {batch_run_id!r}")
    return event_source_response(
        services.run_manager,
        batch_run_id,
        ping=services.settings.sse_ping_seconds,
    )


__all__ = ["router"]
