"""Deterministic offline model for tests, rehearsals, and the offline demo.

This is intentionally not a reasoning model. It replays queued turns or hands
control to a responder callable, and it emits the Bedrock-shaped stream events
the Strands event loop consumes. That protocol is the only coupling to the SDK,
so an SDK upgrade touches this file alone.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator, AsyncIterable, Callable, Mapping, Sequence
from dataclasses import dataclass
from threading import Event as CancelSignal
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel
from strands.models.model import Model
from strands.types.content import Messages, SystemContentBlock
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

from terrasentry_core.agents.investigation import format_signals_line, parse_signals
from terrasentry_core.agents.specialists import SPECIALIST_NAMES
from terrasentry_core.errors import AgentRunError
from terrasentry_core.seed.schemas import BatchRecord

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ToolCall:
    """One scripted tool request."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ScriptedTurn:
    """One scripted assistant turn: text, tool calls, or structured output."""

    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    structured_output: BaseModel | None = None


@dataclass(frozen=True)
class ScriptedContext:
    """What a responder sees: the conversation so far and the offered tools."""

    messages: Messages
    tool_specs: tuple[ToolSpec, ...]
    tool_choice: ToolChoice | None
    call_index: int

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(spec.get("name", "") for spec in self.tool_specs)

    @property
    def forced(self) -> bool:
        return self.tool_choice is not None

    def called_tools(self) -> tuple[str, ...]:
        names: list[str] = []
        for message in self.messages:
            for block in message.get("content", []):
                tool_use = block.get("toolUse")
                if tool_use is not None:
                    names.append(str(tool_use.get("name", "")))
        return tuple(names)

    def completed_tools(self) -> tuple[str, ...]:
        names_by_id = {
            str(tool_use.get("toolUseId", "")): str(tool_use.get("name", ""))
            for message in self.messages
            for block in message.get("content", [])
            if (tool_use := block.get("toolUse")) is not None
        }
        completed: list[str] = []
        for message in self.messages:
            for block in message.get("content", []):
                tool_result = block.get("toolResult")
                if tool_result is None:
                    continue
                name = names_by_id.get(str(tool_result.get("toolUseId", "")))
                if name is not None:
                    completed.append(name)
        return tuple(completed)


ScriptedResponder = Callable[[ScriptedContext], ScriptedTurn | None]


def _structured_spec(context: ScriptedContext, output: BaseModel) -> ToolSpec | None:
    name = type(output).__name__
    for spec in context.tool_specs:
        if spec.get("name") == name:
            return spec
    if context.forced and context.tool_specs:
        return context.tool_specs[0]
    return None


def _tool_use_events(name: str, tool_use_id: str, payload: dict[str, Any]) -> list[StreamEvent]:
    return [
        {"contentBlockStart": {"start": {"toolUse": {"toolUseId": tool_use_id, "name": name}}}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(payload, ensure_ascii=False)}}}},
        {"contentBlockStop": {}},
    ]


def _turn_events(turn: ScriptedTurn, context: ScriptedContext, prefix: str) -> list[StreamEvent]:
    events: list[StreamEvent] = [{"messageStart": {"role": "assistant"}}]
    stop_reason = "end_turn"
    if turn.structured_output is not None:
        spec = _structured_spec(context, turn.structured_output)
        if spec is None:
            raise AgentRunError("no structured output tool spec is offered for the scripted turn")
        events.extend(
            _tool_use_events(
                spec.get("name", "StructuredOutputTool"),
                f"{prefix}-structured-{context.call_index}",
                turn.structured_output.model_dump(mode="json"),
            )
        )
        stop_reason = "tool_use"
    elif turn.tool_calls:
        for index, call in enumerate(turn.tool_calls):
            tool_use_id = f"{prefix}-tool-{context.call_index}-{index}"
            events.extend(_tool_use_events(call.name, tool_use_id, call.arguments))
        stop_reason = "tool_use"
    elif turn.text is not None:
        events.append({"contentBlockDelta": {"delta": {"text": turn.text}}})
        events.append({"contentBlockStop": {}})
    events.append({"messageStop": {"stopReason": stop_reason}})
    events.append(
        {
            "metadata": {
                "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                "metrics": {"latencyMs": 0},
            }
        }
    )
    return events


class ScriptedModel(Model):
    """A queued/responder-driven model double with no network calls."""

    def __init__(
        self,
        turns: Sequence[ScriptedTurn] = (),
        *,
        responder: ScriptedResponder | None = None,
        default_text: str = "Done.",
        model_id: str = "scripted",
        context_window_limit: int = 200_000,
    ) -> None:
        self._turns = list(turns)
        self._responder = responder
        self._default_text = default_text
        self._prefix = f"scripted-{uuid4().hex[:8]}"
        self._config: dict[str, Any] = {
            "model_id": model_id,
            "context_window_limit": context_window_limit,
        }
        self._call_index = 0

    @property
    def call_count(self) -> int:
        return self._call_index

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return dict(self._config)

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: ToolChoice | None = None,
        system_prompt_content: list[SystemContentBlock] | None = None,
        invocation_state: dict[str, Any] | None = None,
        cancel_signal: CancelSignal | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[StreamEvent]:
        context = ScriptedContext(
            messages=messages,
            tool_specs=tuple(tool_specs or ()),
            tool_choice=tool_choice,
            call_index=self._call_index,
        )
        self._call_index += 1
        for event in _turn_events(self._resolve(context), context, self._prefix):
            yield event

    async def structured_output(
        self,
        output_model: type[T],
        prompt: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, T | Any]]:
        for index, turn in enumerate(self._turns):
            if isinstance(turn.structured_output, output_model):
                self._turns.pop(index)
                yield {"output": turn.structured_output}
                return
        raise AgentRunError(f"no scripted {output_model.__name__} turn is queued")

    def _resolve(self, context: ScriptedContext) -> ScriptedTurn:
        if self._turns:
            candidate = self._turns[0]
            if (
                candidate.structured_output is not None
                and _structured_spec(context, candidate.structured_output) is None
            ):
                return ScriptedTurn(text="Formatting the structured result.")
            return self._turns.pop(0)
        if self._responder is not None:
            turn = self._responder(context)
            if turn is not None:
                return turn
        return ScriptedTurn(text=self._default_text)


class AutopilotResponder:
    """Deterministic route used by offline demos and integration tests.

    It calls every configured tool once (in ``order``), then answers with text;
    a pending structured report is returned when its tool spec is offered. It
    never inspects task semantics, which is the point: the whole graph can run
    with zero model calls and still exercise every tool and the verifier gate.
    """

    def __init__(
        self,
        *,
        arguments: Mapping[str, Mapping[str, Any]] | None = None,
        order: Sequence[str] | None = None,
        structured_outputs: Mapping[type[BaseModel], BaseModel] | None = None,
        final_text: str = "Evidence gathered for the record.",
    ) -> None:
        self._arguments = {name: dict(value) for name, value in (arguments or {}).items()}
        self._order = list(order or ())
        self._structured = dict(structured_outputs or {})
        self._final_text = final_text

    @classmethod
    def for_record(
        cls,
        record: BatchRecord,
        *,
        structured_outputs: Mapping[type[BaseModel], BaseModel] | None = None,
        final_text: str = "Evidence gathered for the record.",
    ) -> AutopilotResponder:
        """Build the canonical route for one record: every tool once, then text."""
        arguments: dict[str, dict[str, Any]] = {
            "get_tree_cover_loss": {"polygon_id": record.polygon.id},
            "get_fire_hotspots": {"polygon_id": record.polygon.id},
            "get_legality_record": {"supplier_id": record.supplier_id},
            "get_consignment": {"record_id": record.record_id},
        }
        order = list(arguments)
        for name in SPECIALIST_NAMES:
            arguments[name] = {"input": f"Collect evidence for record {record.record_id}."}
            order.append(name)
        return cls(
            arguments=arguments,
            order=order,
            structured_outputs=structured_outputs,
            final_text=final_text,
        )

    def __call__(self, context: ScriptedContext) -> ScriptedTurn | None:
        for model, report in self._structured.items():
            if any(spec.get("name") == model.__name__ for spec in context.tool_specs):
                return ScriptedTurn(structured_output=report)
        completed = set(context.completed_tools())
        for name in self._order:
            if name in context.tool_names and name not in completed:
                return ScriptedTurn(tool_calls=(ToolCall(name, self._arguments.get(name, {})),))
        if context.tool_names:
            return ScriptedTurn(text=self._final_text)
        return None


_SIGNALS_FIELD = re.compile(r"screening_signals[\"']?\s*:\s*\[([^\]]*)\]")


def _block_texts(blocks: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        str(block["text"]) if "text" in block else json.dumps(block["json"])
        for block in blocks
        if "text" in block or "json" in block
    ]


def _tool_result_texts(context: ScriptedContext) -> list[str]:
    return [
        text
        for message in context.messages
        for block in message.get("content", [])
        if (result := block.get("toolResult")) is not None
        for text in _block_texts(result.get("content", []))
    ]


def _task_text(context: ScriptedContext) -> str:
    """The first user message: for a specialist, the supervisor's delegation input."""
    for message in context.messages:
        if message.get("role") == "user":
            return " ".join(_block_texts(message.get("content", [])))
    return ""


def _payload_signals(texts: Sequence[str]) -> list[str]:
    found: set[str] = set()
    for text in texts:
        for match in _SIGNALS_FIELD.finditer(text):
            found.update(re.findall(r"[\"']([^\"']+)[\"']", match.group(1)))
    return sorted(found)


class AdaptiveAutopilotResponder:
    """Offline stand-in for the adaptive Supervisor and its specialists.

    Role is inferred from the offered tools. Specialists run their phase tool(s) and end with a
    machine-readable ``SCREENING_SIGNALS`` line taken from their tool results. The Supervisor only
    sees those specialist reports, exactly as in a live run: it delegates phase 1, parses the
    signals, then re-tasks legality and geospatial for the deep dive. ``skip_deep_dives`` ignores the
    signals; it exists so the verifier's coverage gate has a deterministic skipped-investigation
    to catch. The fixed-route :class:`AutopilotResponder` stays for parity tests.
    """

    def __init__(
        self,
        record: BatchRecord,
        *,
        structured_outputs: Mapping[type[BaseModel], BaseModel] | None = None,
        skip_deep_dives: bool = False,
        final_text: str = "Evidence gathered for the record.",
    ) -> None:
        self._record = record
        self._structured = dict(structured_outputs or {})
        self._skip = skip_deep_dives
        self._final_text = final_text

    @classmethod
    def for_record(
        cls,
        record: BatchRecord,
        *,
        structured_outputs: Mapping[type[BaseModel], BaseModel] | None = None,
        skip_deep_dives: bool = False,
        final_text: str = "Evidence gathered for the record.",
    ) -> AdaptiveAutopilotResponder:
        return cls(
            record,
            structured_outputs=structured_outputs,
            skip_deep_dives=skip_deep_dives,
            final_text=final_text,
        )

    def __call__(self, context: ScriptedContext) -> ScriptedTurn | None:
        for model, report in self._structured.items():
            if any(spec.get("name") == model.__name__ for spec in context.tool_specs):
                return ScriptedTurn(structured_output=report)
        names = set(context.tool_names)
        if set(SPECIALIST_NAMES) <= names:
            return self._supervise(context)
        if "get_tree_cover_loss" in names:
            deep = "context layers" in _task_text(context).lower()
            wanted = [("get_context_layers" if deep else "get_tree_cover_loss", self._polygon())]
        elif "get_fire_hotspots" in names:
            wanted = [("get_fire_hotspots", self._polygon())]
        elif "get_legality_record" in names:
            wanted = [
                ("get_legality_record", {"supplier_id": self._record.supplier_id}),
                ("get_consignment", {"record_id": self._record.record_id}),
            ]
            if "concession" in _task_text(context).lower():
                wanted.append(
                    (
                        "check_concession_overlap",
                        {**self._polygon(), "supplier_id": self._record.supplier_id},
                    )
                )
            elif "search_adverse_media" in names:
                # Context lookup belongs to the standard pass, not the signal-driven deep dive.
                wanted.append(("search_adverse_media", {"supplier_id": self._record.supplier_id}))
        else:
            return None
        completed = set(context.completed_tools())
        for name, arguments in wanted:
            if name not in completed:
                return ScriptedTurn(tool_calls=(ToolCall(name, arguments),))
        signals = sorted(
            {*_payload_signals(_tool_result_texts(context)), *parse_signals(_task_text(context))}
        )
        return ScriptedTurn(text=f"{self._final_text}\n{format_signals_line(signals)}")

    def _polygon(self) -> dict[str, Any]:
        return {"polygon_id": self._record.polygon.id}

    def _supervise(self, context: ScriptedContext) -> ScriptedTurn:
        record = self._record
        completed = context.completed_tools()
        if not completed:
            return ScriptedTurn(
                tool_calls=(
                    ToolCall(
                        "geospatial_analyst",
                        {"input": f"Screen polygon {record.polygon.id}: report loss and layer overlaps."},
                    ),
                    ToolCall(
                        "thermal_analyst",
                        {"input": f"Screen polygon {record.polygon.id}: report fire hotspots."},
                    ),
                    ToolCall(
                        "legality_analyst",
                        {
                            "input": f"Standard legality pass for supplier {record.supplier_id}, "
                            f"record {record.record_id}."
                        },
                    ),
                )
            )
        signals = sorted({s for text in _tool_result_texts(context) for s in parse_signals(text)})
        if signals and not self._skip and completed.count("legality_analyst") == 1:
            line = format_signals_line(signals)
            reason = f"Screening signals {', '.join(signals)} call for a deep dive. {line}"
            return ScriptedTurn(
                tool_calls=(
                    ToolCall(
                        "legality_analyst",
                        {
                            "input": f"check concession overlap and permit coverage for polygon "
                            f"{record.polygon.id}, supplier {record.supplier_id}. {reason}"
                        },
                    ),
                    ToolCall(
                        "geospatial_analyst",
                        {"input": f"get context layers for polygon {record.polygon.id}. {reason}"},
                    ),
                )
            )
        if signals and not self._skip:
            return ScriptedTurn(text=f"{self._final_text} Deep dives ran for signals: {', '.join(signals)}.")
        return ScriptedTurn(text=self._final_text)


__all__ = [
    "AdaptiveAutopilotResponder",
    "AutopilotResponder",
    "ScriptedContext",
    "ScriptedModel",
    "ScriptedResponder",
    "ScriptedTurn",
    "ToolCall",
]
