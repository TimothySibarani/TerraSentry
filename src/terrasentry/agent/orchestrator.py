"""The agent loop.

Deliberately thin. The orchestrator decides *which* tool to call next and *when it has
seen enough*; the tools do the real work and the rubric does the scoring. If this file
starts growing domain logic, that logic is in the wrong place.

Uses the Amazon Bedrock **Converse API**, which gives one uniform request shape across
model families -- so switching between Claude and Amazon Nova is a config change, not
a rewrite. That property is worth demonstrating on stage: run the same screening on two
models and show the tool-call traces side by side.

Model routing (see ``config.py``):
  * ``MODEL_ORCHESTRATOR`` -- the branching decisions and the final synthesis.
  * ``MODEL_EXTRACTION``  -- high-volume, low-judgement work (parsing, normalising
    names, tidying fields). Cheaper model, called far more often.

Hackathon credits are finite. Routing is not premature optimisation here.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ..evidence import EvidenceLedger

log = logging.getLogger(__name__)

ToolFn = Callable[..., dict[str, Any]]


@dataclass
class TurnRecord:
    """One iteration of the loop, kept for the reasoning panel and the audit trail."""

    index: int
    text: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "text": self.text,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
        }


@dataclass
class RunResult:
    supplier: str
    turns: list[TurnRecord]
    final_text: str
    stop_reason: str
    ledger: EvidenceLedger

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier": self.supplier,
            "stop_reason": self.stop_reason,
            "final_text": self.final_text,
            "turns": [t.to_dict() for t in self.turns],
            "evidence": self.ledger.to_dict(),
        }


class Orchestrator:
    """Supervisor agent over a registry of tools.

    Args:
        client: A boto3 ``bedrock-runtime`` client. Injected so tests can pass a fake.
        model_id: Bedrock model identifier.
        tools: Mapping of tool name -> callable. Each callable takes keyword arguments
            matching its schema and returns a JSON-serialisable dict.
        tool_specs: Bedrock ``toolConfig`` tool specifications (see ``toolspec.py``).
        max_turns: Hard stop. An agent that has not concluded in this many turns has
            lost the plot and should hand over to a human.
    """

    def __init__(
        self,
        client: Any,
        model_id: str,
        tools: dict[str, ToolFn],
        tool_specs: list[dict[str, Any]],
        system_prompt: str,
        max_turns: int = 12,
        temperature: float = 0.2,
        ledger: EvidenceLedger | None = None,
    ) -> None:
        self.client = client
        self.model_id = model_id
        self.tools = tools
        self.tool_specs = tool_specs
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.temperature = temperature
        # Tools own the ledger: a claim exists only because a tool observed something.
        # Pass the session's ledger in so RunResult carries the real one.
        self.ledger = ledger

    def run(self, supplier: str, task: str) -> RunResult:
        ledger = self.ledger if self.ledger is not None else EvidenceLedger(supplier=supplier)
        messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": task}]}]
        turns: list[TurnRecord] = []
        final_text = ""
        stop_reason = "max_turns"

        for index in range(self.max_turns):
            response = self.client.converse(
                modelId=self.model_id,
                messages=messages,
                system=[{"text": self.system_prompt}],
                toolConfig={"tools": self.tool_specs},
                inferenceConfig={"temperature": self.temperature, "maxTokens": 4096},
            )

            output_message = response["output"]["message"]
            messages.append(output_message)

            record = TurnRecord(index=index, text=_text_of(output_message))
            reason = response.get("stopReason")

            if reason != "tool_use":
                record.text = _text_of(output_message)
                turns.append(record)
                final_text = record.text or ""
                stop_reason = reason or "end_turn"
                break

            tool_result_blocks: list[dict[str, Any]] = []
            for block in output_message.get("content", []):
                use = block.get("toolUse")
                if not use:
                    continue

                name = use["name"]
                args = use.get("input") or {}
                record.tool_calls.append({"name": name, "input": args})
                log.info("tool_use %s(%s)", name, json.dumps(args)[:200])

                try:
                    result = self._invoke(name, args)
                    status = "success"
                except Exception as exc:  # surfaced to the model so it can adapt
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                    status = "error"
                    log.warning("tool %s failed: %s", name, exc)

                record.tool_results.append({"name": name, "status": status, "result": result})
                tool_result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": use["toolUseId"],
                            "content": [{"json": result}],
                            "status": status,
                        }
                    }
                )

            messages.append({"role": "user", "content": tool_result_blocks})
            turns.append(record)

        return RunResult(
            supplier=supplier,
            turns=turns,
            final_text=final_text,
            stop_reason=stop_reason,
            ledger=ledger,
        )

    def _invoke(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        fn = self.tools.get(name)
        if fn is None:
            raise KeyError(f"Unknown tool: {name}")
        return fn(**args)


def _text_of(message: dict[str, Any]) -> str:
    return "".join(b.get("text", "") for b in message.get("content", []) if "text" in b).strip()
