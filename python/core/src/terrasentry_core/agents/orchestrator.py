"""RunOrchestrator: the deep seam for one agent run.

Interface::

    run(record_id) -> AgentRunResult
    resume(result, decision) -> AgentRunResult

Behind that interface: Strands graph assembly, model routing, the run-state
machine, the verify-before-write edge, and the human-review hold. Callers
(CLI today, M4 API tomorrow) never touch a Strands object.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import uuid4

from strands.multiagent import GraphBuilder
from strands.multiagent.graph import Graph, GraphState
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient

from terrasentry_core.agents.models import ModelBundle
from terrasentry_core.agents.nodes import FunctionNode, VerifierNode
from terrasentry_core.agents.schemas import AgentRunResult, ReviewDecision
from terrasentry_core.agents.specialists import build_specialists
from terrasentry_core.agents.supervisor import build_supervisor
from terrasentry_core.agents.verification import VerificationReport
from terrasentry_core.agents.verifier import build_verifier_agent
from terrasentry_core.assessment.pipeline import RecordAssessment, assess_record
from terrasentry_core.domain.enums import RunState
from terrasentry_core.domain.run_state import advance, decision_event
from terrasentry_core.errors import AgentRunError, InvalidReviewDecisionError
from terrasentry_core.reference.pipeline import PolygonReport
from terrasentry_core.scoring import RubricConfig
from terrasentry_core.seed.schemas import BatchRecord
from terrasentry_core.tools.agent_tools import ToolContext
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_core.tools.sources import LossWindow
from terrasentry_core.tools.trace import TraceCollector, TraceKind, TraceStep, utc_now

_NODE_KINDS: dict[str, TraceKind] = {
    "supervisor": "agent",
    "verifier": "verifier",
}


def _verification_accepted(state: GraphState) -> bool:
    node_result = state.results.get("verifier")
    if node_result is None:
        return False
    for agent_result in node_result.get_agent_results():
        if isinstance(agent_result.structured_output, VerificationReport):
            return agent_result.structured_output.accepted
    return False


class RunOrchestrator:
    """Owns one supervisor -> assessor -> verifier -> writer run and its review gate."""

    def __init__(
        self,
        *,
        gfw: GfwClient,
        firms: FirmsClient,
        datasets: SeedDatasets,
        models: ModelBundle | None = None,
        window_days: int = 30,
        years: int = 5,
        rubric: RubricConfig | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._gfw = gfw
        self._firms = firms
        self._datasets = datasets
        self._models = models
        self._window_days = window_days
        self._years = years
        self._rubric = rubric
        self._clock = clock

    async def run(self, record_id: str, *, refresh: bool = False) -> AgentRunResult:
        """Run the graph for one seed record and return its state and artifacts."""
        started = self._clock()
        record = self._datasets.get_record(record_id)
        run_id = f"agent-{started:%Y%m%dT%H%M%S}-{uuid4().hex[:6]}"
        trace = TraceCollector(clock=self._clock)
        trace.add("state", "queued", record_id)
        trace.add("state", "running", f"{record_id}: {record.polygon.id}")
        context = ToolContext(
            gfw=self._gfw,
            firms=self._firms,
            datasets=self._datasets,
            trace=trace,
            window_days=self._window_days,
            loss_window=LossWindow.from_now(self._years, now=started),
            retrieved_at=started,
            refresh=refresh,
        )
        models = self._models or ModelBundle.from_settings()
        graph = self._build_graph(record, context, models)

        try:
            async for event in graph.stream_async(self._task(record), invocation_state={"run_id": run_id}):
                await self._record_event(event, trace)
        except Exception as exc:
            trace.add("state", "failed", f"{type(exc).__name__}: {exc}")
            return self._result(
                run_id, record, started, trace, state=RunState.FAILED, summary=f"run failed: {exc}"
            )

        return self._finish(run_id, record, started, trace, context, refresh=refresh)

    async def resume(self, result: AgentRunResult, decision: ReviewDecision) -> AgentRunResult:
        """Record the human decision on an awaiting run and release the DDS."""
        if result.state is not RunState.AWAITING_REVIEW:
            raise InvalidReviewDecisionError(str(result.state))
        if result.pending_assessment is None:
            raise AgentRunError("run is awaiting review but has no pending assessment")
        state = advance(result.state, decision_event(decision.decision))
        finished = self._clock()
        step = TraceStep(
            step_id=f"STEP-{len(result.trace) + 1:03d}",
            kind="review",
            name=decision.decision.value,
            detail=decision.note or f"human decision by {decision.reviewer}",
            at=finished,
        )
        return result.model_copy(
            update={
                "state": state,
                "assessment": result.pending_assessment,
                "pending_assessment": None,
                "review": decision,
                "finished_at": finished,
                "trace": [*result.trace, step],
            }
        )

    def _task(self, record: BatchRecord) -> str:
        return (
            f"Assess EUDR compliance for record {record.record_id}, supplier {record.supplier_id}, "
            f"polygon {record.polygon.id} in {record.polygon.region}. Delegate to every specialist "
            "exactly once, then summarise the evidence you received."
        )

    def _build_graph(self, record: BatchRecord, context: ToolContext, models: ModelBundle) -> Graph:
        specialists = build_specialists(models.extraction, context)
        supervisor = build_supervisor(models.orchestrator, specialists, context=context)
        verifier_agent = build_verifier_agent(models.orchestrator, context)

        builder = GraphBuilder()
        builder.set_graph_id("terrasentry-agent-run")
        builder.set_max_node_executions(8)
        builder.add_node(supervisor, "supervisor")
        builder.add_node(FunctionNode("assessor", self._assess_node(record, context)), "assessor")
        builder.add_node(
            VerifierNode(
                agent=verifier_agent,
                context=context,
                record=record,
                retrieved_at=context.retrieved_at,
                config=self._rubric,
            ),
            "verifier",
        )
        builder.add_node(FunctionNode("dds_writer", self._commit_node(record, context)), "dds_writer")
        builder.add_edge("supervisor", "assessor")
        builder.add_edge("assessor", "verifier")
        builder.add_edge("verifier", "dds_writer", condition=_verification_accepted)
        return builder.build()

    def _assess_node(
        self, record: BatchRecord, context: ToolContext
    ) -> Callable[[], Awaitable[str]]:
        async def assess() -> str:
            sources = await context.polygon_sources(record.polygon.id)
            polygon = record.polygon
            report = PolygonReport(
                polygon_id=polygon.id,
                label=polygon.label,
                region=polygon.region,
                archetype=polygon.archetype,
                area_ha=polygon.area_ha,
                loss=sources.loss,
                hotspots=sources.hotspots,
                errors=list(sources.errors),
            )
            candidate = assess_record(
                report,
                record,
                self._datasets.operator,
                retrieved_at=context.retrieved_at,
                config=self._rubric,
            )
            context.candidate = candidate
            context.trace.add(
                "run",
                "assessor",
                f"{record.record_id}: {candidate.assessment.verdict} score {candidate.assessment.score}",
                payload={"fingerprint": candidate.fingerprint},
            )
            return f"candidate assessment: {candidate.assessment.verdict} ({candidate.assessment.score})"

        return assess

    def _commit_node(
        self, record: BatchRecord, context: ToolContext
    ) -> Callable[[], Awaitable[str]]:
        async def commit() -> str:
            candidate = context.candidate
            if candidate is None:
                raise AgentRunError("dds_writer ran without a candidate assessment")
            withheld = candidate.run_state is RunState.AWAITING_REVIEW
            context.trace.add(
                "writer",
                "dds_writer",
                f"{record.record_id}: DDS {'withheld for review' if withheld else 'released'}",
                payload={"verdict": candidate.assessment.verdict.value, "fingerprint": candidate.fingerprint},
            )
            return f"DDS {'withheld for review' if withheld else 'released'}: {candidate.record_id}"

        return commit

    async def _record_event(self, event: dict, trace: TraceCollector) -> None:
        event_type = event.get("type")
        if event_type not in {"multiagent_node_start", "multiagent_node_stop"}:
            return
        node_id = str(event.get("node_id", ""))
        kind = _NODE_KINDS.get(node_id)
        if kind is None:
            return
        trace.add(kind, node_id, "started" if event_type.endswith("start") else "finished")

    def _finish(
        self,
        run_id: str,
        record: BatchRecord,
        started: datetime,
        trace: TraceCollector,
        context: ToolContext,
        *,
        refresh: bool,
    ) -> AgentRunResult:
        candidate = context.candidate
        verification = context.verification
        state = RunState.FAILED
        assessment: RecordAssessment | None = None
        pending: RecordAssessment | None = None
        if candidate is not None and verification is not None and verification.accepted:
            if candidate.run_state is RunState.AWAITING_REVIEW:
                state = RunState.AWAITING_REVIEW
                pending = candidate
            else:
                state = RunState.COMPLETE
                assessment = candidate
        trace.add("state", state.value, f"{record.record_id} ({'refresh' if refresh else 'cached-or-live'})")
        return self._result(
            run_id,
            record,
            started,
            trace,
            state=state,
            summary=context.summary,
            verification=verification,
            assessment=assessment,
            pending=pending,
        )

    def _result(
        self,
        run_id: str,
        record: BatchRecord,
        started: datetime,
        trace: TraceCollector,
        *,
        state: RunState,
        summary: str = "",
        verification: VerificationReport | None = None,
        assessment: RecordAssessment | None = None,
        pending: RecordAssessment | None = None,
    ) -> AgentRunResult:
        return AgentRunResult(
            run_id=run_id,
            record_id=record.record_id,
            supplier_id=record.supplier_id,
            polygon_id=record.polygon.id,
            state=state,
            summary=summary,
            verification=verification,
            assessment=assessment,
            pending_assessment=pending,
            trace=trace.steps,
            disclosures=self._datasets.disclosures,
            started_at=started,
            finished_at=self._clock(),
        )


__all__ = ["RunOrchestrator"]
