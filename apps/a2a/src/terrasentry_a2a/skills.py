"""The three things Joule can ask for, each returning a markdown reply.

Joule's ``agent-request`` is synchronous with a 60 s limit, so ``screen`` waits only up to a reply
budget and otherwise answers "still screening" with a link, and ``investigate`` (a live agent run
that takes minutes) starts the run and answers at once.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from urllib.parse import quote

from terrasentry_a2a.client import TERMINAL_STATES, ApiError, Batch, Run, Supplier, TerraSentryClient
from terrasentry_a2a.intent import (
    Intent,
    match_suppliers,
    message_text,
    parse_intent,
    record_id_for_supplier,
)
from terrasentry_a2a.settings import A2ASettings

_VERDICT = {"compliant": "Compliant", "high_risk": "High risk", "ambiguous": "Ambiguous, needs review"}
_STATE = {
    "complete": "complete",
    "awaiting_review": "awaiting a reviewer's decision",
    "failed": "failed",
    "running": "running",
    "queued": "queued",
}
_HELP = (
    "I can help with EUDR supplier screening in TerraSentry:\n\n"
    "- **Screen a supplier**: `screen PT Sumber Sejahtera Sriwijaya` (or a record id such as `REC-001`)\n"
    "- **Investigate with the AI agents**: `investigate SUP-001` (starts a live run, takes a few minutes)\n"
    "- **Check progress**: `status run-1a2b3c4d5e6f`"
)

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class Skills:
    def __init__(
        self,
        client: TerraSentryClient,
        settings: A2ASettings,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        self._client = client
        self._settings = settings
        self._sleep = sleep
        self._clock = clock
        self._agent_runs: deque[float] = deque()

    async def handle(self, raw: str) -> str:
        """Answer one Joule message; API failures become a plain reply rather than a failed task."""
        intent = parse_intent(message_text(raw))
        try:
            if intent.kind == "status":
                return await self._status(intent)
            if intent.kind in {"screen", "investigate"}:
                resolved = await self._resolve(intent)
                if isinstance(resolved, str):
                    return resolved
                if intent.kind == "screen":
                    return await self._screen(*resolved)
                return await self._investigate(*resolved)
        except ApiError as exc:
            return f"Sorry, I couldn't do that: {exc}"
        return _HELP

    # -- resolution ---------------------------------------------------------------------------

    async def _resolve(self, intent: Intent) -> tuple[str, str] | str:
        """Return ``(record_id, label)`` or a reply asking the user to disambiguate."""
        if intent.record_id:
            return intent.record_id, intent.record_id
        if intent.supplier_id:
            return record_id_for_supplier(intent.supplier_id), intent.supplier_id
        suppliers = await self._client.list_suppliers()
        matches = match_suppliers(intent.name or "", suppliers)
        if not matches:
            return (
                f"I couldn't find a supplier matching **{intent.name}**. Try its id, for example `SUP-001`."
            )
        if len(matches) > 1:
            return "Which supplier did you mean?\n\n" + "\n".join(_supplier_line(item) for item in matches)
        match = matches[0]
        return record_id_for_supplier(match.supplier_id), f"{match.legal_name} ({match.supplier_id})"

    # -- skills -------------------------------------------------------------------------------

    async def _screen(self, record_id: str, label: str) -> str:
        batch = await self._client.start_screening(record_id)
        deadline = self._clock() + self._settings.a2a_reply_budget_seconds
        while batch.state not in TERMINAL_STATES and self._clock() < deadline:
            await self._sleep(self._settings.a2a_poll_interval_seconds)
            batch = await self._client.get_batch(batch.run_id)
        run_id = f"{batch.run_id}:{record_id}"
        if batch.state not in TERMINAL_STATES:
            return (
                f"Still screening **{label}**; it hasn't finished within my reply window.\n\n"
                f"{self._link('Follow it in the cockpit', run_id)}"
            )
        return self._screen_reply(label, await self._client.get_run(run_id))

    async def _investigate(self, record_id: str, label: str) -> str:
        if not self._allow_agent_run():
            return "Agent runs are limited per hour on this proxy. Please try again later, or use `screen`."
        model = self._settings.a2a_agent_model
        run = await self._client.start_agent_run(record_id, model)
        return (
            f"Started an AI-agent investigation of **{label}** on `{run.model or model}`.\n"
            "Live runs take a few minutes, so I'll leave it running.\n\n"
            f"{self._link('Watch the trace in the cockpit', run.run_id)}\n\n"
            f"Ask me `status {run.run_id}` for the outcome."
        )

    async def _status(self, intent: Intent) -> str:
        run_id = intent.run_id or ""
        if run_id.startswith("batch-") and ":" not in run_id:
            batch = await self._client.get_batch(run_id)
            return self._batch_reply(batch)
        run = await self._client.get_run(run_id)
        return self._screen_reply(run.record_id or run.run_id, run)

    # -- formatting ---------------------------------------------------------------------------

    def _screen_reply(self, label: str, run: Run) -> str:
        state = _STATE.get(run.state, run.state)
        lines = [f"**{label}**: {state}."]
        if run.verdict:
            score = f", score {run.score}" if run.score is not None else ""
            lines.append(f"Verdict: **{_VERDICT.get(run.verdict, run.verdict)}**{score}.")
        flagged = [item for item in run.findings if item.level != "clear"][:3]
        if flagged:
            lines.append("Top findings:\n" + "\n".join(f"- {item.detail or item.code}" for item in flagged))
        if run.state == "awaiting_review":
            lines.append("A reviewer has to decide before anything changes in SAP.")
        if run.state == "failed" and run.error:
            lines.append(f"Reason: {run.error}")
        lines.append(self._link("Open the full assessment in the cockpit", run.run_id))
        return "\n\n".join(lines)

    def _batch_reply(self, batch: Batch) -> str:
        breakdown = ", ".join(
            f"{count} {key.replace('_', ' ')}" for key, count in batch.verdict_breakdown.items() if count
        )
        done = batch.states.get("complete", 0) + batch.states.get("awaiting_review", 0)
        state = _STATE.get(batch.state, batch.state)
        lines = [f"Batch `{batch.run_id}` is **{state}**: {done} of {batch.record_count} records done."]
        if breakdown:
            lines.append(f"So far: {breakdown}.")
        lines.append(f"[Open the batch in the cockpit]({self._cockpit('batch/' + batch.run_id)})")
        return "\n\n".join(lines)

    def _cockpit(self, path: str) -> str:
        return f"{self._settings.cockpit_base_url.rstrip('/')}/{path}"

    def _link(self, text: str, run_id: str) -> str:
        return f"[{text}]({self._cockpit('runs/' + quote(run_id, safe=''))})"

    def _allow_agent_run(self) -> bool:
        now = self._clock()
        while self._agent_runs and now - self._agent_runs[0] > 3600:
            self._agent_runs.popleft()
        if len(self._agent_runs) >= self._settings.a2a_max_agent_runs_per_hour:
            return False
        self._agent_runs.append(now)
        return True


def _supplier_line(supplier: Supplier) -> str:
    extra = (
        f" (trading as {supplier.trading_name})"
        if supplier.trading_name and supplier.trading_name != supplier.legal_name
        else ""
    )
    return f"- `{supplier.supplier_id}`: {supplier.legal_name}{extra}"


__all__ = ["Skills"]
