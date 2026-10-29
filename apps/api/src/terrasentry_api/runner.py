"""Background run execution and SSE fan-out.

The API starts runs here and never touches a Strands object: scenarios go
through :class:`RunOrchestrator` (supervisor -> specialists -> verifier ->
writer), while batch records use the deterministic assess + verifier path that
M3's 50-record harness established. Steps are persisted and broadcast as they
are produced; HITL runs pause in ``awaiting_review`` until ``decide`` records a
human decision.
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from terrasentry_core.agents.factory import FAULT_SCENARIOS, model_bundle_for
from terrasentry_core.agents.models import ModelBundle
from terrasentry_core.agents.orchestrator import RunOrchestrator
from terrasentry_core.agents.schemas import AgentRunResult, ReviewDecision
from terrasentry_core.agents.verification import code_checks
from terrasentry_core.assessment.pipeline import assess_record
from terrasentry_core.domain.enums import Decision, RunState
from terrasentry_core.errors import (
    CoreError,
    ErpActionError,
    InvalidReviewDecisionError,
    RunNotCancellableError,
    SeedLookupError,
)
from terrasentry_core.intake import IntakeError
from terrasentry_core.reference.pipeline import PolygonReport
from terrasentry_core.scoring import RubricConfig
from terrasentry_core.seed.schemas import BatchRecord, OperatorRecord
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_core.tools.sources import LossWindow, fetch_polygon_sources
from terrasentry_core.tools.trace import StepHook, TraceCollector, TraceKind, TraceStep, utc_now
from terrasentry_integrations.cache import CacheBackend
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient
from terrasentry_integrations.sources.media import MediaSearch

from terrasentry_api.config import Settings
from terrasentry_api.sap_actions import ErpMode, SapActionRecord, SapActionService, planned_status
from terrasentry_api.store import RunStore

logger = logging.getLogger(__name__)

RunEvent = dict[str, Any]
_TERMINAL = {RunState.COMPLETE, RunState.FAILED, RunState.AWAITING_REVIEW}


def nearest_rank_percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile over an ascending sample (no interpolation).

    Deliberately deterministic and dependency-free: the M6 numbers must be
    reproducible from the same inputs, not sensitive to float interpolation.
    """
    if not sorted_values:
        return 0.0
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return round(sorted_values[min(rank, len(sorted_values)) - 1], 3)


def _elapsed_since(started: datetime | None, now: datetime) -> float | None:
    if started is None:
        return None
    start = started if started.tzinfo is not None else started.replace(tzinfo=UTC)
    return round((now - start).total_seconds(), 3)


class RunBroadcaster:
    """In-process publish/subscribe keyed by run id (single-worker MVP)."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[RunEvent | None]]] = {}

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[RunEvent | None]]:
        queue: asyncio.Queue[RunEvent | None] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        try:
            yield queue
        finally:
            subscribers = self._subscribers.get(run_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(run_id, None)

    def publish(self, run_id: str, event: RunEvent) -> None:
        for queue in self._subscribers.get(run_id, set()):
            queue.put_nowait(event)


class RunManager:
    """Owns background run tasks, step persistence, and live subscriptions."""

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        datasets: SeedDatasets,
        gfw: GfwClient,
        firms: FirmsClient,
        rubric: RubricConfig | None = None,
        clock: Callable[[], datetime] = utc_now,
        cache: CacheBackend | None = None,
        sap: SapActionService | None = None,
        media: MediaSearch | None = None,
    ) -> None:
        self._media = media
        self._settings = settings
        self._session_factory = session_factory
        self._datasets = datasets
        self._gfw = gfw
        self._firms = firms
        self._rubric = rubric
        self._clock = clock
        self._cache = cache
        self._sap = sap
        self._broadcaster = RunBroadcaster()
        self._tasks: set[asyncio.Task[None]] = set()
        self._run_tasks: dict[str, asyncio.Task[None]] = {}
        self._cancelled: set[str] = set()
        self._decision_locks: dict[str, asyncio.Lock] = {}
        self._closed = False

    # -- lifecycle --------------------------------------------------------------

    async def shutdown(self) -> None:
        self._closed = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _spawn(self, run_id: str, coro: Awaitable[None]) -> None:
        if self._closed:
            return
        task = asyncio.create_task(self._guard(run_id, coro))
        self._tasks.add(task)
        self._run_tasks[run_id] = task

        def _done(finished: asyncio.Task[None]) -> None:
            self._tasks.discard(finished)
            if self._run_tasks.get(run_id) is finished:
                del self._run_tasks[run_id]

        task.add_done_callback(_done)

    async def recover_interrupted(self) -> int:
        """Startup sweep: runs are in-process tasks, so any open run belongs to a dead process."""
        async with self._session_factory() as session:
            ids = await RunStore(session).fail_open_runs("interrupted by an API restart; run it again")
            await session.commit()
        return len(ids)

    async def cancel_run(self, run_id: str) -> None:
        """Stop a scenario run or a batch that this process is executing, then mark it failed."""
        task = self._run_tasks.get(run_id)
        if task is None or task.done():
            raise RunNotCancellableError(run_id)
        self._cancelled.add(run_id)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def is_executing(self, run_id: str) -> bool:
        """True while this process is still driving the run's task."""
        task = self._run_tasks.get(run_id)
        return task is not None and not task.done()

    async def _guard(self, run_id: str, coro: Awaitable[None]) -> None:
        """Last-resort net: an unexpected task failure marks the run failed."""
        try:
            await coro
        except asyncio.CancelledError:
            if run_id not in self._cancelled:
                raise
            self._cancelled.discard(run_id)
            async with self._session_factory() as session:
                await RunStore(session).fail_open_runs("cancelled by a reviewer", parent_run_id=run_id)
                await session.commit()
            await self._fail(run_id, "cancelled by a reviewer")
        except Exception as exc:
            logger.exception("run task %s raised unexpectedly", run_id)
            try:
                await self._fail(run_id, f"internal error: {type(exc).__name__}: {exc}")
            except Exception:  # pragma: no cover - the database itself is unavailable
                logger.exception("could not mark run %s failed", run_id)

    def _decision_lock(self, run_id: str) -> asyncio.Lock:
        return self._decision_locks.setdefault(run_id, asyncio.Lock())

    # -- entry points -------------------------------------------------------------

    async def start_run(
        self,
        *,
        record_id: str | None,
        scenario: str | None,
        model: str,
        refresh: bool = False,
        erp_mode: ErpMode = "auto",
    ) -> str:
        skip_deep_dives = False
        options = {"scenario": scenario, "refresh": refresh}
        if scenario in FAULT_SCENARIOS:
            scenario, skip_deep_dives = FAULT_SCENARIOS[scenario]
        record = self._resolve_record(record_id=record_id, scenario=scenario)
        self._require_country(record)
        run_id = f"run-{uuid4().hex[:12]}"
        await self._create_run(
            run_id, "scenario", record=record, model=model, erp_mode=erp_mode, options=options
        )
        self._spawn(
            run_id,
            self._execute_scenario(run_id, record, model, refresh, skip_deep_dives=skip_deep_dives),
        )
        return run_id

    async def start_batch(
        self,
        *,
        size: int,
        refresh: bool = False,
        record_ids: list[str] | None = None,
        mode: str = "screening",
        model: str | None = None,
        erp_mode: ErpMode = "auto",
    ) -> str:
        batch_run_id = f"batch-{uuid4().hex[:12]}"
        # runs.model holds the mode string: "deterministic" for screening, else scripted/sap.
        run_model = (model or self._settings.agent_model) if mode == "agent" else "deterministic"
        # Explicit ids screen submitted (or chosen) records; otherwise the seed demo batch.
        records = (
            [self._datasets.get_record(record_id) for record_id in dict.fromkeys(record_ids)]
            if record_ids
            else self._datasets.records[:size]
        )
        for record in records:
            self._require_country(record)
        assessment_date = self._settings.rehearsal_date or self._clock().astimezone(UTC).date()
        options = {"refresh": refresh, "batch_mode": mode}
        async with self._session_factory() as session:
            store = RunStore(session)
            operator = await store.operator_profile(self._datasets.operator)
            await store.create_run(
                run_id=batch_run_id,
                options=options,
                kind="batch",
                model=run_model,
                assessment_date=assessment_date,
                operator=operator,
                erp_mode=erp_mode,
                metrics={
                    "mode": mode,
                    "model": run_model if mode == "agent" else None,
                    "record_count": len(records),
                    "unlabelled_count": sum(record.expected_archetype is None for record in records),
                },
            )
            for record in records:
                await store.create_run(
                    run_id=self.record_run_id(batch_run_id, record),
                    kind="record",
                    record=record,
                    parent_run_id=batch_run_id,
                    options=options,
                    model=run_model,
                    assessment_date=assessment_date,
                    operator=operator,
                    erp_mode=erp_mode,
                )
            await session.commit()
        self._spawn(batch_run_id, self._execute_batch(batch_run_id, records, refresh, mode, run_model))
        return batch_run_id

    async def decide(self, run_id: str, decision: ReviewDecision) -> AgentRunResult:
        # Serialise decisions per run so two concurrent approvals cannot both resume.
        async with self._decision_lock(run_id):
            return await self._decide_locked(run_id, decision)

    async def _decide_locked(self, run_id: str, decision: ReviewDecision) -> AgentRunResult:
        async with self._session_factory() as session:
            store = RunStore(session)
            run = await store.get_run(run_id)
            if run is None:
                raise SeedLookupError("run", run_id)
            result = await store.load_result(run_id)
        if result is None:
            raise InvalidReviewDecisionError("unknown")
        if result.state is not RunState.AWAITING_REVIEW:
            raise InvalidReviewDecisionError(str(result.state))

        orchestrator = self._orchestrator(on_step=None)
        resumed = await orchestrator.resume(result, decision)
        action = await self._erp_action(resumed, decision.decision)
        if action is not None:
            resumed = self._attach_sap(resumed, action)
        await self._store_result(resumed, sap_action=action)
        async with self._session_factory() as session:
            store = RunStore(session)
            await store.release_dds(run_id)
            await session.commit()
        self._publish_state(run_id, resumed.state)
        self._publish_done(run_id, resumed.state)
        return resumed

    async def stream(self, run_id: str) -> AsyncIterator[RunEvent]:
        """Replay persisted steps, then follow live events until terminal."""
        async with self._broadcaster.subscribe(run_id) as queue:
            snapshot, steps, terminal = await self._snapshot(run_id)
            yield {"event": "snapshot", "data": snapshot}
            seen: set[str] = set()
            for step in steps:
                seen.add(step.step_id)
                yield {"event": "step", "data": step.model_dump(mode="json")}
            if terminal:
                yield {"event": "done", "data": snapshot}
                return
            while True:
                event = await queue.get()
                if event is None:
                    return
                if event["event"] == "step" and event["data"].get("step_id") in seen:
                    continue
                yield event
                if event["event"] == "done":
                    return

    # -- scenario execution ---------------------------------------------------------

    async def _execute_scenario(
        self,
        run_id: str,
        record: BatchRecord,
        model: str,
        refresh: bool,
        *,
        skip_deep_dives: bool = False,
    ) -> None:
        await self._orchestrate(run_id, record, model, refresh, skip_deep_dives=skip_deep_dives)

    async def _orchestrate(
        self,
        run_id: str,
        record: BatchRecord,
        model: str,
        refresh: bool,
        *,
        skip_deep_dives: bool = False,
    ) -> tuple[RunState, str | None]:
        """Run the agent graph for one persisted run; shared by scenarios and agent batches.

        Returns the final state and the released/pending verdict (``None`` when the run failed).
        A failure of any kind marks only this run FAILED; it never raises.
        """
        started = self._clock()
        trace_queue: asyncio.Queue[TraceStep | None] = asyncio.Queue()

        def on_step(step: TraceStep) -> None:
            trace_queue.put_nowait(step)

        try:
            models = model_bundle_for(model, record, skip_deep_dives=skip_deep_dives)
            assessment_date, operator = await self._accepted_context(run_id)
        except CoreError as exc:
            await self._fail(run_id, str(exc))
            return RunState.FAILED, None

        await self._set_state(run_id, RunState.RUNNING, started_at=started)
        writer = asyncio.create_task(self._persist_steps(run_id, trace_queue))
        orchestrator = self._orchestrator(
            on_step=on_step, models=models, as_of=assessment_date, operator=operator
        )
        failure: str | None = None
        result: AgentRunResult | None = None
        try:
            result = await asyncio.wait_for(
                orchestrator.run(record.record_id, refresh=refresh, run_id=run_id),
                timeout=self._settings.run_timeout_seconds,
            )
        except TimeoutError:
            failure = f"run timed out after {self._settings.run_timeout_seconds}s"
        except Exception as exc:  # pragma: no cover - defensive wrapper
            failure = f"{type(exc).__name__}: {exc}"
        finally:
            trace_queue.put_nowait(None)
            await writer

        if result is None:
            await self._fail(run_id, failure or "run failed")
            return RunState.FAILED, None
        action = await self._erp_action(result, None)
        if action is not None:
            result = self._attach_sap(result, action)
        await self._store_result(result, sap_action=action)
        if result.usage is not None:
            async with self._session_factory() as session:
                await RunStore(session).merge_metrics(
                    run_id, {"usage": result.usage, "usage_scope": "graph-level"}
                )
                await session.commit()
        self._publish_done(run_id, result.state)
        candidate = result.assessment or result.pending_assessment
        return result.state, candidate.assessment.verdict.value if candidate is not None else None

    async def _persist_steps(self, run_id: str, queue: asyncio.Queue[TraceStep | None]) -> None:
        seq = 0
        async with self._session_factory() as session:
            store = RunStore(session)
            while True:
                step = await queue.get()
                if step is None:
                    break
                seq += 1
                if await store.append_step(run_id, step, seq):
                    await session.commit()
                    self._publish_step(run_id, step)

    # -- batch execution -----------------------------------------------------------

    async def _execute_batch(
        self,
        batch_run_id: str,
        records: list[BatchRecord],
        refresh: bool,
        mode: str = "screening",
        model: str = "deterministic",
    ) -> None:
        started = self._clock()
        concurrency = max(
            1, self._settings.batch_agent_concurrency if mode == "agent" else self._settings.batch_concurrency
        )
        await self._set_state(batch_run_id, RunState.RUNNING, started_at=started)
        expected = Counter(record.expected_archetype for record in records if record.expected_archetype)
        progress: dict[str, Any] = {
            "run_id": batch_run_id,
            "total": len(records),
            "completed": 0,
            "failed": 0,
            "awaiting_review": 0,
            "verdict_breakdown": {"compliant": 0, "high_risk": 0, "ambiguous": 0},
        }
        lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(concurrency)
        cache_before = self._cache.stats().as_dict() if self._cache is not None else None

        async def one(record: BatchRecord) -> None:
            async with semaphore:
                if mode == "agent":
                    state, verdict = await self._orchestrate(
                        self.record_run_id(batch_run_id, record), record, model, refresh
                    )
                else:
                    state, verdict = await self._execute_batch_record(batch_run_id, record, refresh)
            async with lock:
                if state is RunState.COMPLETE:
                    progress["completed"] += 1
                elif state is RunState.AWAITING_REVIEW:
                    progress["awaiting_review"] += 1
                else:
                    progress["failed"] += 1
                if verdict is not None:
                    progress["verdict_breakdown"][verdict] += 1
                progress["elapsed_seconds"] = _elapsed_since(started, self._clock())
                self._broadcaster.publish(batch_run_id, {"event": "progress", "data": dict(progress)})

        results = await asyncio.gather(*(one(record) for record in records), return_exceptions=True)
        escaped = [result for result in results if isinstance(result, BaseException)]
        if escaped:
            await self._set_state(
                batch_run_id,
                RunState.FAILED,
                error=f"{len(escaped)} record task(s) escaped: {escaped[0]!r}",
                finished_at=self._clock(),
            )
            self._publish_done(batch_run_id, RunState.FAILED)
            return

        finished = self._clock()
        metrics = await self._batch_metrics(
            batch_run_id,
            started=started,
            finished=finished,
            expected=dict(expected),
            record_count=len(records),
            unlabelled_count=sum(record.expected_archetype is None for record in records),
            mode=mode,
            model=model,
            concurrency=concurrency,
            cache_before=cache_before,
        )
        await self._set_state(
            batch_run_id,
            RunState.COMPLETE,
            finished_at=finished,
            elapsed_seconds=metrics["wall_clock_seconds"],
            metrics=metrics,
        )
        self._publish_done(batch_run_id, RunState.COMPLETE)

    async def _execute_batch_record(
        self, parent_run_id: str, record: BatchRecord, refresh: bool
    ) -> tuple[RunState, str | None]:
        run_id = self.record_run_id(parent_run_id, record)
        started = self._clock()
        trace = TraceCollector(clock=self._clock)
        await self._set_state(run_id, RunState.RUNNING, started_at=started)
        verdict: str | None = None
        try:
            pinned, operator = await self._accepted_context(run_id)
        except CoreError as exc:
            # A child without its accepted snapshot fails alone; it must not fail the batch.
            await self._fail(run_id, str(exc))
            return RunState.FAILED, None
        try:
            sources = await fetch_polygon_sources(
                record.polygon,
                gfw=self._gfw,
                firms=self._firms,
                window_days=self._settings.firms_window_days,
                # Pinned rehearsals let the fetch derive the window from ``as_of``
                # so prefetch and offline run share cache keys across days.
                loss_window=None
                if pinned is not None
                else LossWindow.from_now(self._settings.loss_window_years, now=started),
                refresh=refresh,
                as_of=pinned,
            )
            report = PolygonReport(
                polygon_id=record.polygon.id,
                label=record.polygon.label,
                region=record.polygon.region,
                archetype=record.polygon.archetype,
                area_ha=record.polygon.area_ha,
                loss=sources.loss,
                hotspots=sources.hotspots,
                layers=sources.layers,
                errors=list(sources.errors),
            )
            trace.add(
                "run",
                "sources",
                f"{record.record_id}: loss={'present' if sources.loss else 'missing'}, "
                f"hotspots={'present' if sources.hotspots else 'missing'}",
            )
            candidate = assess_record(
                report,
                record,
                operator,
                assessment_date=pinned,
                retrieved_at=started,
                config=self._rubric,
            )
            trace.add(
                "run",
                "assessor",
                f"{record.record_id}: {candidate.assessment.verdict} score {candidate.assessment.score}",
                payload={"fingerprint": candidate.fingerprint},
            )
            verification = code_checks(
                candidate,
                record,
                sources,
                operator=operator,
                assessment_date=pinned,
                retrieved_at=started,
                config=self._rubric,
            )
            trace.add(
                "verifier",
                "verification",
                f"{'accepted' if verification.accepted else 'rejected'}: "
                f"{len(verification.challenges)} challenge(s)",
                payload={"accepted": verification.accepted},
            )
            if not verification.accepted:
                state = RunState.FAILED
            elif candidate.run_state is RunState.AWAITING_REVIEW:
                state = RunState.AWAITING_REVIEW
            else:
                state = RunState.COMPLETE
            verdict = candidate.assessment.verdict.value
            result = AgentRunResult(
                run_id=run_id,
                record_id=record.record_id,
                supplier_id=record.supplier_id,
                polygon_id=record.polygon.id,
                state=state,
                summary=(
                    f"{candidate.assessment.verdict} score {candidate.assessment.score}"
                    if verification.accepted
                    else "verification rejected the candidate assessment"
                ),
                verification=verification,
                assessment=candidate if state is RunState.COMPLETE else None,
                pending_assessment=candidate if state is RunState.AWAITING_REVIEW else None,
                trace=trace.steps,
                disclosures=self._datasets.disclosures_for(record, operator=operator),
                started_at=started,
                finished_at=self._clock(),
            )
        except Exception as exc:
            trace.add("state", "failed", f"{type(exc).__name__}: {exc}")
            result = AgentRunResult(
                run_id=run_id,
                record_id=record.record_id,
                supplier_id=record.supplier_id,
                polygon_id=record.polygon.id,
                state=RunState.FAILED,
                summary=f"run failed: {exc}",
                trace=trace.steps,
                disclosures=self._datasets.disclosures_for(record, operator=operator),
                started_at=started,
                finished_at=self._clock(),
            )
        action = await self._erp_action(result, None)
        if action is not None:
            result = self._attach_sap(result, action)
        await self._store_result(result, sap_action=action)
        return result.state, verdict

    # -- persistence helpers ---------------------------------------------------------

    async def _create_run(
        self,
        run_id: str,
        kind: str,
        *,
        record: BatchRecord,
        model: str,
        erp_mode: ErpMode = "auto",
        options: dict[str, Any] | None = None,
    ) -> None:
        async with self._session_factory() as session:
            store = RunStore(session)
            operator = await store.operator_profile(self._datasets.operator)
            assessment_date = self._settings.rehearsal_date or self._clock().astimezone(UTC).date()
            await store.create_run(
                run_id=run_id,
                kind=kind,
                record=record,
                model=model,
                assessment_date=assessment_date,
                operator=operator,
                erp_mode=erp_mode,
                options=options,
            )
            await session.commit()

    @staticmethod
    def _require_country(record: BatchRecord) -> None:
        if record.polygon.country is None:
            raise IntakeError(
                "plot.country",
                "Production country is missing on this legacy record. "
                "Resubmit it with an ISO country before screening.",
            )

    async def _accepted_context(self, run_id: str) -> tuple[date, OperatorRecord]:
        async with self._session_factory() as session:
            row = await RunStore(session).get_run(run_id)
            if row is None or row.assessment_date is None or row.operator_profile is None:
                raise CoreError("accepted run has no immutable assessment context")
            return row.assessment_date, OperatorRecord.model_validate(row.operator_profile)

    async def _set_state(
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
    ) -> None:
        async with self._session_factory() as session:
            store = RunStore(session)
            await store.set_state(
                run_id,
                state,
                summary=summary,
                error=error,
                started_at=started_at,
                finished_at=finished_at,
                elapsed_seconds=elapsed_seconds,
                metrics=metrics,
            )
            await session.commit()
        self._publish_state(run_id, state)

    async def _store_result(
        self,
        result: AgentRunResult,
        *,
        sap_action: SapActionRecord | None = None,
    ) -> None:
        async with self._session_factory() as session:
            store = RunStore(session)
            await store.persist_result(result)
            if sap_action is not None:
                await store.record_sap_action(
                    run_id=sap_action.run_id,
                    supplier_id=sap_action.supplier_id,
                    vendor_id=sap_action.vendor_id,
                    mode=sap_action.mode,
                    status=sap_action.status,
                    purchasing_block=sap_action.purchasing_block,
                    real=sap_action.real,
                    external_reference=sap_action.external_reference,
                    error=sap_action.error,
                    performed_at=sap_action.performed_at,
                )
            fresh: list[TraceStep] = []
            for seq, step in enumerate(result.trace, start=1):
                if await store.append_step(result.run_id, step, seq):
                    fresh.append(step)
            await session.commit()
        for step in fresh:
            self._publish_step(result.run_id, step)
        self._publish_state(result.run_id, result.state)

    async def _erp_mode(self, run_id: str) -> str:
        async with self._session_factory() as session:
            run = await RunStore(session).get_run(run_id)
        return run.erp_mode if run is not None else "auto"

    async def _erp_action(self, result: AgentRunResult, decision: Decision | None) -> SapActionRecord | None:
        """Apply the vendor status a finished run calls for, when its ERP mode is ``auto``.

        Held runs have no released assessment, so nothing is applied until a human decides.
        ``confirm`` and ``off`` runs never act here; ``confirm_erp_action`` applies a pending one.
        """
        if self._sap is None or result.assessment is None:
            return None
        if await self._erp_mode(result.run_id) != "auto":
            return None
        status = planned_status(verdict=result.assessment.assessment.verdict, decision=decision)
        if status is None:
            return None
        return await self._sap.apply_status(
            run_id=result.run_id, supplier_id=result.supplier_id, status=status
        )

    async def confirm_erp_action(self, run_id: str) -> SapActionRecord:
        """Apply the pending ERP action of a finished run (the explicit confirmation path)."""
        if self._sap is None:
            raise ErpActionError("no ERP gateway is configured")
        async with self._decision_lock(run_id):
            async with self._session_factory() as session:
                store = RunStore(session)
                if await store.get_run(run_id) is None:
                    raise SeedLookupError("run", run_id)
                result = await store.load_result(run_id)
                existing = await store.get_sap_action(run_id)
            if result is None or result.state is not RunState.COMPLETE or result.assessment is None:
                raise ErpActionError("the run is not finished; a held run needs a review decision first")
            if existing is not None and existing.status != "failed":
                raise ErpActionError("an ERP action was already applied to this run")
            status = planned_status(
                verdict=result.assessment.assessment.verdict,
                decision=result.review.decision if result.review is not None else None,
            )
            if status is None:
                raise ErpActionError("this run plans no ERP action")
            action = await self._sap.apply_status(
                run_id=run_id, supplier_id=result.supplier_id, status=status
            )
            await self._store_result(self._attach_sap(result, action), sap_action=action)
            return action

    def _attach_sap(self, result: AgentRunResult, action: SapActionRecord) -> AgentRunResult:
        """Fold the ERP action into the run: DDS extension, disclosure, trace step."""
        assessment = result.assessment
        if assessment is not None:
            assessment.dds.erp_action = action.to_erp_action()
        disclosures = list(result.disclosures)
        if action.disclosure not in disclosures:
            disclosures.append(action.disclosure)
        step = action.to_trace_step(len(result.trace) + 1)
        return result.model_copy(update={"trace": [*result.trace, step], "disclosures": disclosures})

    async def _fail(self, run_id: str, detail: str) -> None:
        async with self._session_factory() as session:
            store = RunStore(session)
            await store.set_state(
                run_id,
                RunState.FAILED,
                summary=detail,
                error=detail,
                finished_at=self._clock(),
            )
            await session.commit()
        self._publish_state(run_id, RunState.FAILED)
        self._publish_done(run_id, RunState.FAILED)

    async def _batch_metrics(
        self,
        batch_run_id: str,
        *,
        started: datetime,
        finished: datetime,
        expected: dict[str, int],
        record_count: int,
        unlabelled_count: int = 0,
        mode: str = "screening",
        model: str = "deterministic",
        concurrency: int | None = None,
        cache_before: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        async with self._session_factory() as session:
            store = RunStore(session)
            counts = await store.batch_state_counts(batch_run_id)
            breakdown = await store.batch_verdict_breakdown(batch_run_id)
            average = await store.batch_average_seconds(batch_run_id)
            durations = await store.batch_record_durations(batch_run_id)
            confusion = await store.batch_confusion(batch_run_id)
            sap_actions = await store.batch_sap_action_counts(batch_run_id)
            usage = await store.batch_usage(batch_run_id)
        wall_clock = round((finished - started).total_seconds(), 3)
        metrics: dict[str, Any] = {
            "mode": mode,
            "model": model if mode == "agent" else None,
            "record_count": record_count,
            "unlabelled_count": unlabelled_count,
            "expected_breakdown": expected,
            "verdict_breakdown": breakdown,
            "state_counts": counts,
            "wall_clock_seconds": wall_clock,
            "average_seconds_per_record": average,
            "median_seconds_per_record": round(statistics.median(durations), 3) if durations else 0.0,
            "p95_seconds_per_record": nearest_rank_percentile(durations, 0.95),
            "throughput_records_per_second": round(record_count / wall_clock, 3) if wall_clock > 0 else 0.0,
            "total_record_seconds": round(sum(durations), 3),
            "confusion": confusion,
            "batch_concurrency": concurrency or max(1, self._settings.batch_concurrency),
            "sap_actions": sap_actions,
        }
        if usage is not None:
            metrics["token_usage"] = usage
            metrics["token_usage_scope"] = "graph-level"
        if cache_before is not None and self._cache is not None:
            cache_after = self._cache.stats().as_dict()
            metrics["cache_stats"] = {
                key: cache_after.get(key, 0) - cache_before.get(key, 0)
                for key in ("hits", "misses", "writes", "offline_misses")
            }
        return metrics

    async def _snapshot(self, run_id: str) -> tuple[dict[str, Any], list[TraceStep], bool]:
        progress: dict[str, Any] | None = None
        async with self._session_factory() as session:
            store = RunStore(session)
            run = await store.get_run(run_id)
            if run is None:
                raise SeedLookupError("run", run_id)
            verdict = await store.get_verdict(run_id)
            dds = await store.get_dds(run_id)
            rows = await store.list_steps(run_id)
            if run.kind == "batch":
                progress = await store.batch_progress(run_id)
                progress["run_id"] = run_id
                progress["total"] = int(run.metrics.get("record_count", 0)) or progress["total"]
                progress["elapsed_seconds"] = _elapsed_since(run.started_at, self._clock())
        steps = [
            TraceStep(
                step_id=row.step_id,
                kind=cast(TraceKind, row.kind),
                name=row.name,
                detail=row.detail,
                at=row.at,
                payload=row.payload,
            )
            for row in rows
        ]
        payload = {
            "run_id": run.id,
            "kind": run.kind,
            "state": run.state.value,
            "record_id": run.record_id,
            "parent_run_id": run.parent_run_id,
            "verdict": verdict.verdict.value if verdict is not None else None,
            "score": verdict.score if verdict is not None else None,
            "dds_released": bool(dds.released) if dds is not None else False,
        }
        if progress is not None:
            payload["progress"] = progress
        return payload, steps, run.state in _TERMINAL

    # -- misc ---------------------------------------------------------------------

    def _resolve_record(self, *, record_id: str | None, scenario: str | None) -> BatchRecord:
        if record_id:
            return self._datasets.get_record(record_id)
        if scenario:
            return self._datasets.record_for_scenario(scenario)
        raise SeedLookupError("record or scenario", "")

    def _orchestrator(
        self,
        *,
        on_step: StepHook | None,
        models: ModelBundle | None = None,
        as_of: date | None = None,
        operator: OperatorRecord | None = None,
    ) -> RunOrchestrator:
        return RunOrchestrator(
            gfw=self._gfw,
            firms=self._firms,
            datasets=self._datasets,
            models=models,
            window_days=self._settings.firms_window_days,
            years=self._settings.loss_window_years,
            as_of=as_of,
            operator=operator,
            rubric=self._rubric,
            clock=self._clock,
            on_step=on_step,
            media=self._media,
        )

    @staticmethod
    def record_run_id(parent_run_id: str, record: BatchRecord) -> str:
        return f"{parent_run_id}:{record.record_id}"

    def _publish_step(self, run_id: str, step: TraceStep) -> None:
        self._broadcaster.publish(run_id, {"event": "step", "data": step.model_dump(mode="json")})

    def _publish_state(self, run_id: str, state: RunState) -> None:
        self._broadcaster.publish(
            run_id, {"event": "state", "data": {"run_id": run_id, "state": state.value}}
        )

    def _publish_done(self, run_id: str, state: RunState) -> None:
        self._broadcaster.publish(run_id, {"event": "done", "data": {"run_id": run_id, "state": state.value}})


__all__ = ["RunBroadcaster", "RunEvent", "RunManager"]
