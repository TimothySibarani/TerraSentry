"""Pydantic results of an agent run: the contract M4 persists and M5 renders."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from terrasentry_core.agents.verification import VerificationReport
from terrasentry_core.assessment.pipeline import RecordAssessment
from terrasentry_core.domain.enums import Decision, RunState
from terrasentry_core.tools.trace import TraceStep


class ReviewDecision(BaseModel):
    """A human decision recorded on the Ambiguous/HITL branch."""

    decision: Decision
    reviewer: str = "human"
    note: str = ""


class AgentRunResult(BaseModel):
    """Everything one agent run produced, including the withheld DDS pending review."""

    run_id: str
    record_id: str
    supplier_id: str
    polygon_id: str
    state: RunState
    summary: str = ""
    verification: VerificationReport | None = None
    assessment: RecordAssessment | None = None
    pending_assessment: RecordAssessment | None = None
    trace: list[TraceStep] = Field(default_factory=list)
    disclosures: list[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime
    review: ReviewDecision | None = None

    @property
    def finalized(self) -> bool:
        """True when the run completed and the DDS is released."""
        return self.state is RunState.COMPLETE


__all__ = ["AgentRunResult", "ReviewDecision"]
