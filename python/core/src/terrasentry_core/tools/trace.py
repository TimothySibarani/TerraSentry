"""In-memory run trace for the agent path.

The API (M4) persists these steps and the cockpit (M5) streams them; keeping the
shape here lets both the agents and the tests record the same deterministic
artifact. Times come from an injectable clock so tests can pin them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TraceKind = Literal["run", "agent", "tool", "verifier", "writer", "review", "state", "sap"]
StepHook = Callable[["TraceStep"], None]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class TraceStep(BaseModel):
    """One visible step of a run: a delegation, a tool call, a check, a write."""

    step_id: str
    kind: TraceKind
    name: str
    detail: str = ""
    at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class TraceCollector:
    """Append-only collector with stable step ids and an injectable clock.

    ``on_step`` is an optional synchronous hook invoked after every append. The
    M4 API uses it to persist and broadcast steps as they happen; the hook must
    not block (the API only enqueues).
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        on_step: StepHook | None = None,
    ) -> None:
        self._clock = clock
        self._on_step = on_step
        self._steps: list[TraceStep] = []

    def add(
        self,
        kind: TraceKind,
        name: str,
        detail: str = "",
        *,
        payload: dict[str, Any] | None = None,
    ) -> TraceStep:
        step = TraceStep(
            step_id=f"STEP-{len(self._steps) + 1:03d}",
            kind=kind,
            name=name,
            detail=detail,
            at=self._clock(),
            payload=payload or {},
        )
        self._steps.append(step)
        if self._on_step is not None:
            self._on_step(step)
        return step

    @property
    def steps(self) -> list[TraceStep]:
        return list(self._steps)

    def of_kind(self, kind: TraceKind) -> list[TraceStep]:
        return [step for step in self._steps if step.kind == kind]

    def names_of_kind(self, kind: TraceKind) -> list[str]:
        return [step.name for step in self._steps if step.kind == kind]


__all__ = ["StepHook", "TraceCollector", "TraceKind", "TraceStep", "utc_now"]
