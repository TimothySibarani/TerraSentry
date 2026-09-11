"""Strands graph nodes for deterministic steps and the verifier gate.

Graph executors must be ``AgentBase`` or ``MultiAgentBase``; these adapters let
the deterministic core (assessment, DDS release) and the gated verifier
participate without pretending to be model agents.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from strands import Agent
from strands.agent.agent_result import AgentResult
from strands.multiagent.base import MultiAgentBase, MultiAgentResult, NodeResult, Status
from strands.telemetry.metrics import EventLoopMetrics
from strands.types.content import Message

from terrasentry_core.agents.verification import (
    VerificationChallenge,
    VerificationReport,
    code_checks,
    merge_reports,
)
from terrasentry_core.scoring import RubricConfig
from terrasentry_core.seed.schemas import BatchRecord
from terrasentry_core.tools.agent_tools import ToolContext
from terrasentry_core.tools.sources import PolygonSources


def _assistant_result(text: str) -> Message:
    return {"role": "assistant", "content": [{"text": text}]}


def _completed(node_id: str, text: str, structured: BaseModel | None = None) -> MultiAgentResult:
    result = AgentResult(
        stop_reason="end_turn",
        message=_assistant_result(text),
        metrics=EventLoopMetrics(),
        state={},
        structured_output=structured,
    )
    return MultiAgentResult(
        status=Status.COMPLETED,
        results={node_id: NodeResult(result=result, status=Status.COMPLETED)},
    )


class FunctionNode(MultiAgentBase):
    """Deterministic graph node: runs an async function and wraps its text result."""

    def __init__(self, node_id: str, func: Callable[[], Awaitable[str]]) -> None:
        super().__init__()
        self.id = node_id
        self._func = func

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        text = await self._func()
        return _completed(self.id, text)


class VerifierNode(MultiAgentBase):
    """Runs deterministic checks, then the verifier agent, and merges both reports.

    The node exposes exactly one structured result: a
    :class:`VerificationReport`. The graph's verify-before-write edge reads it.
    """

    def __init__(
        self,
        *,
        agent: Agent,
        context: ToolContext,
        record: BatchRecord,
        retrieved_at: datetime | None = None,
        config: RubricConfig | None = None,
    ) -> None:
        super().__init__()
        self.id = "verifier"
        self._agent = agent
        self._context = context
        self._record = record
        self._retrieved_at = retrieved_at
        self._config = config

    def _prompt(self, sources: PolygonSources) -> str:
        return "\n".join(
            [
                f"Verify record {self._record.record_id} for polygon {self._record.polygon.id} "
                f"and supplier {self._record.supplier_id}.",
                f"Observed sources: loss={'present' if sources.loss else 'missing'}, "
                f"hotspots={'present' if sources.hotspots else 'missing'}, errors={len(sources.errors)}.",
                f"Supervisor summary: {self._context.summary or '(no summary)'}",
                "Inspect the evidence with your tools and return the VerificationReport.",
            ]
        )

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        candidate = self._context.candidate
        if candidate is None:
            report = VerificationReport(
                accepted=False,
                challenges=[
                    VerificationChallenge(
                        kind="missing_source",
                        severity="error",
                        detail="no candidate assessment was produced before verification",
                    )
                ],
            )
            return self._finish(report)

        sources = await self._context.polygon_sources(self._record.polygon.id)
        report = code_checks(
            candidate,
            self._record,
            sources,
            retrieved_at=self._retrieved_at,
            config=self._config,
        )
        if report.accepted:
            report = await self._llm_review(sources, report)
        return self._finish(report)

    async def _llm_review(
        self, sources: PolygonSources, deterministic: VerificationReport
    ) -> VerificationReport:
        try:
            result = await self._agent.invoke_async(self._prompt(sources))
        except Exception as exc:
            return deterministic.model_copy(
                update={
                    "accepted": False,
                    "challenges": [
                        *deterministic.challenges,
                        VerificationChallenge(
                            kind="llm_review",
                            severity="error",
                            detail=f"verifier model failed: {exc}",
                        ),
                    ],
                }
            )
        review = result.structured_output
        if not isinstance(review, VerificationReport):
            return deterministic.model_copy(
                update={
                    "accepted": False,
                    "challenges": [
                        *deterministic.challenges,
                        VerificationChallenge(
                            kind="llm_review",
                            severity="error",
                            detail="verifier model returned no structured VerificationReport",
                        ),
                    ],
                }
            )
        return merge_reports(deterministic, review, model_id=self._model_id())

    def _model_id(self) -> str | None:
        config = self._agent.model.get_config() if self._agent.model else None
        if isinstance(config, dict):
            value = config.get("model_id")
            return str(value) if value is not None else None
        return None

    def _finish(self, report: VerificationReport) -> MultiAgentResult:
        self._context.verification = report
        outcome = "accepted" if report.accepted else "rejected"
        self._context.trace.add(
            "verifier",
            "verification",
            f"{outcome}: {len(report.challenges)} challenge(s), {len(report.checked_claims)} check(s)",
            payload={"accepted": report.accepted},
        )
        return _completed(self.id, f"verification {outcome}", structured=report)


__all__ = ["FunctionNode", "VerifierNode"]
