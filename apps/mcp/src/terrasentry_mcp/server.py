"""MCP server: TerraSentry's screening, evidence and review tools for Claude Code and other agents.

The server is a thin client of the running TerraSentry API, so every run it starts appears in the
cockpit and the verdict is still the deterministic rubric's. Two things are deliberately gated on a
person: recording a review decision and applying a pending SAP change. Both ask the human through
MCP elicitation, and a client that cannot ask gets an error instead of a silent approval.

No ``from __future__ import annotations`` here: the SDK evaluates tool signatures, and the
resolver functions are closures over the API client, so annotations must resolve at definition.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal
from urllib.parse import quote

from mcp.server import MCPServer
from mcp.server.mcpserver import (
    AcceptedElicitation,
    Elicit,
    ElicitationResult,
    Resolve,
)
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from terrasentry_mcp.client import ApiError, TerraSentryApi
from terrasentry_mcp.settings import McpSettings

TERMINAL_STATES = frozenset({"complete", "failed", "awaiting_review"})

ErpChoice = Literal["off", "confirm", "auto"]
Commodity = Literal["oil_palm", "wood", "rubber", "cocoa", "coffee"]
Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]

INSTRUCTIONS = """\
TerraSentry screens supplier plots for EU Deforestation Regulation risk.

How it works: agents gather real Hansen tree-cover loss, NASA FIRMS fire and GFW context-layer
evidence. A fixed, versioned rubric (never a model) sets the verdict: compliant, ambiguous or high_risk.
Compliant results release on their own. Ambiguous and high_risk results are HELD until a person decides.
Legality (permits, holders) is what the supplier declared; it is not checked against a government registry.

SAP: `erp` controls what a run may change in the ERP. `off` (default) never touches SAP. `confirm`
computes the change and waits for confirm_erp_action. `auto` applies it as soon as it is planned
(compliant results, or after a review decision). Choose `auto` only when you mean it.

record_review_decision and confirm_erp_action ask the user to confirm through the client. If the
client cannot ask, the call fails; tell the user to decide in the cockpit instead.
"""


class Confirmation(BaseModel):
    confirm: bool = Field(description="Tick to confirm and go ahead")


def _sap_effect(decision: str, erp_mode: str) -> str:
    verb = "approved" if decision == "approve" else "blocked"
    if erp_mode == "off":
        return "SAP will not be touched for this run."
    if erp_mode == "confirm":
        return f"SAP stays unchanged until the change is confirmed; then the vendor is {verb}."
    return f"SAP: the vendor is set to {verb} immediately."


def _next_step(run: dict[str, Any]) -> str:
    state = run["state"]
    if state == "awaiting_review":
        return (
            "A person has to decide. Call record_review_decision (it asks the user to confirm) "
            "or have them open the cockpit link."
        )
    if run.get("erp_pending"):
        return (
            f"A SAP change ('{run['erp_pending']}') is waiting. Call confirm_erp_action "
            "(it asks the user to confirm)."
        )
    if state in {"queued", "running"}:
        return "Still running. Call get_run again in a few seconds."
    if state == "failed":
        return f"The run failed: {run.get('error') or 'no reason recorded'}. Start it again if needed."
    return "Done."


def run_view(run: dict[str, Any], cockpit_base_url: str) -> dict[str, Any]:
    """The compact, agent-facing view of one run; the full dossier stays in the cockpit."""
    held = run.get("assessment") or run.get("pending_assessment") or {}
    assessment = held.get("assessment") or {}
    findings = [
        {key: item.get(key) for key in ("code", "level", "points", "detail")}
        for item in assessment.get("findings", [])
        if item.get("level") != "clear"
    ]
    action = run.get("sap_action")
    review = run.get("review")
    return {
        "run_id": run["run_id"],
        "state": run["state"],
        "record_id": run.get("record_id"),
        "supplier_id": run.get("supplier_id"),
        "verdict": run.get("verdict"),
        "score": run.get("score"),
        "rubric_version": assessment.get("rubric_version"),
        "findings": findings[:8],
        "data_gaps": assessment.get("data_gaps", []),
        "needs_decision": run["state"] == "awaiting_review",
        "dds_released": bool((run.get("dds") or {}).get("released")),
        "erp": {
            "mode": run.get("erp_mode", "auto"),
            "pending": run.get("erp_pending"),
            "applied": {key: action.get(key) for key in ("status", "purchasing_block", "mode", "real")}
            if action
            else None,
        },
        "review": {key: review.get(key) for key in ("decision", "reviewer", "note")} if review else None,
        "agent_brief": None if run.get("model") == "deterministic" else (run.get("summary") or None),
        "model": run.get("model"),
        "error": run.get("error"),
        "cockpit_url": f"{cockpit_base_url.rstrip('/')}/runs/{quote(run['run_id'], safe='')}",
        "next_step": _next_step(run),
    }


def build_server(
    api: TerraSentryApi,
    settings: McpSettings,
    *,
    sleep: Sleep = asyncio.sleep,
    clock: Clock = time.monotonic,
) -> MCPServer:
    mcp = MCPServer("TerraSentry", instructions=INSTRUCTIONS)
    cockpit = settings.cockpit_base_url

    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    writes = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
    consequential = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)

    async def wait_for_run(run_id: str, wait_seconds: float | None) -> dict[str, Any]:
        budget = settings.mcp_wait_seconds if wait_seconds is None else wait_seconds
        deadline = clock() + budget
        while True:
            run = await api.get_run(run_id)
            if run["state"] in TERMINAL_STATES or clock() >= deadline:
                return run
            await sleep(settings.mcp_poll_interval_seconds)

    # -- screening --------------------------------------------------------------------------

    @mcp.tool(annotations=writes)
    async def screen_plot(
        geometry: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "GeoJSON Polygon, MultiPolygon or Point in WGS84 (lon, lat). "
                    "A Point needs declared_area_ha <= 4."
                )
            ),
        ],
        country: Annotated[str, Field(description="ISO 3166 alpha-2 production country, for example ID")],
        label: Annotated[str, Field(description="A short name for the plot")],
        supplier_name: Annotated[str, Field(description="Legal name of the supplier")],
        commodity: Commodity,
        description: Annotated[str, Field(description="Description of goods, for example 'Wood pulp'")],
        net_weight_kg: Annotated[float, Field(gt=0)],
        harvest_year: Annotated[int, Field(ge=2000, le=2100)],
        permit_type: Literal["hgu", "pbph", "none"] = "none",
        permit_number: str = "",
        permit_expiry: Annotated[str | None, Field(description="YYYY-MM-DD, as declared")] = None,
        declared_holder: str = "",
        hs_heading: Annotated[str, Field(description="4 to 10 digit HS code; defaults per commodity")] = "",
        declared_area_ha: float | None = None,
        mode: Annotated[
            Literal["screening", "agent"],
            Field(
                description=(
                    "screening: rubric only, seconds. "
                    "agent: the agent graph investigates and writes a brief, about a minute"
                )
            ),
        ] = "screening",
        erp: Annotated[
            ErpChoice,
            Field(
                description=(
                    "off: never touch SAP. confirm: wait for confirm_erp_action. "
                    "auto: apply as soon as planned"
                )
            ),
        ] = "off",
        wait_seconds: Annotated[float | None, Field(ge=0, le=300)] = None,
    ) -> dict[str, Any]:
        """Register a supplier plot and screen it against real satellite and concession data.

        Returns the rubric verdict, score and non-clear findings. The verdict comes from a fixed
        rubric, not a model. Legality fields are declared, not verified. Ambiguous and high_risk
        results are held for a person (see needs_decision). If the run outlasts wait_seconds, the
        run id is returned to poll with get_run.
        """
        submission = {
            "plot": {
                "geometry": geometry,
                "country": country,
                "label": label,
                "declared_area_ha": declared_area_ha,
            },
            "supplier": {"legal_name": supplier_name},
            "legality": {
                "permit_type": permit_type,
                "permit_number": permit_number,
                "permit_expiry": permit_expiry,
                "declared_holder": declared_holder,
            },
            "consignment": {
                "commodity": commodity,
                "description": description,
                "hs_heading": hs_heading,
                "net_weight_kg": net_weight_kg,
                "harvest_year": harvest_year,
            },
        }
        record = await api.create_record(submission)
        record_id = record["record_id"]
        if mode == "agent":
            started = await api.start_run(record_id=record_id, model=None, erp_mode=erp)
            run_id = started["run_id"]
        else:
            batch = await api.start_batch(record_ids=[record_id], mode="screening", model=None, erp_mode=erp)
            run_id = f"{batch['run_id']}:{record_id}"
        view = run_view(await wait_for_run(run_id, wait_seconds), cockpit)
        view["record"] = {
            key: record.get(key) for key in ("record_id", "supplier_id", "polygon_id", "area_ha")
        }
        return view

    @mcp.tool(annotations=writes)
    async def import_records(
        csv_text: Annotated[str, Field(description="CSV text with a header row; see the portfolio template")],
        filename: str = "portfolio.csv",
    ) -> dict[str, Any]:
        """Import a supplier portfolio (CSV, or GeoJSON when the filename ends in .geojson).

        Valid rows become records; rejected rows come back with the reason. Screen the created
        records with start_batch.
        """
        result = await api.import_records(filename, csv_text.encode("utf-8"))
        return {
            "total_rows": result["total_rows"],
            "created": [
                {key: item.get(key) for key in ("record_id", "supplier_id", "legal_name", "label")}
                for item in result["created"]
            ],
            "errors": result["errors"],
            "next_step": "Call start_batch with the created record_ids to screen them."
            if result["created"]
            else "Fix the rejected rows and import again.",
        }

    @mcp.tool(annotations=writes)
    async def start_batch(
        record_ids: Annotated[list[str], Field(min_length=1, max_length=500)],
        mode: Literal["screening", "agent"] = "screening",
        erp: ErpChoice = "off",
    ) -> dict[str, Any]:
        """Screen many records at once. Agent mode is limited to 50 records. Returns the batch id."""
        batch = await api.start_batch(record_ids=record_ids, mode=mode, model=None, erp_mode=erp)
        return {
            "batch_id": batch["run_id"],
            "state": batch["state"],
            "record_count": batch["record_count"],
            "cockpit_url": f"{cockpit.rstrip('/')}/batch/{quote(batch['run_id'], safe='')}",
            "next_step": (
                "Call get_batch to follow progress; held runs appear in list_runs(state='awaiting_review')."
            ),
        }

    # -- reading ----------------------------------------------------------------------------

    @mcp.tool(annotations=read_only)
    async def get_run(run_id: str) -> dict[str, Any]:
        """Current state, verdict, findings, ERP status and next step of a run."""
        return run_view(await api.get_run(run_id), cockpit)

    @mcp.tool(annotations=read_only)
    async def get_batch(batch_id: str) -> dict[str, Any]:
        """Progress and results of a batch: state counts, verdict breakdown and SAP actions."""
        batch = await api.get_batch(batch_id)
        return {
            **{
                key: batch.get(key)
                for key in (
                    "run_id",
                    "state",
                    "mode",
                    "record_count",
                    "states",
                    "verdict_breakdown",
                    "sap_actions",
                    "wall_clock_seconds",
                )
            },
            "cockpit_url": f"{cockpit.rstrip('/')}/batch/{quote(batch_id, safe='')}",
        }

    @mcp.tool(annotations=read_only)
    async def list_runs(
        state: Annotated[
            Literal["queued", "running", "awaiting_review", "complete", "failed"] | None,
            Field(description="Filter by state; awaiting_review lists what needs a decision"),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> list[dict[str, Any]]:
        """Recent runs, newest first. Batch parents are excluded."""
        rows = await api.list_runs(state=state, limit=limit)
        return [
            {
                key: row.get(key)
                for key in ("run_id", "state", "record_id", "supplier_id", "verdict", "score", "erp_mode")
            }
            for row in rows
            if row.get("kind") != "batch"
        ]

    @mcp.tool(annotations=read_only)
    async def list_suppliers(
        search: Annotated[str | None, Field(description="Matches name, id or group")] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> list[dict[str, Any]]:
        """Suppliers with their declared permit status and where the data came from."""
        needle = (search or "").strip().lower()
        rows = [
            row
            for row in await api.list_suppliers()
            if not needle
            or needle
            in " ".join(
                str(row.get(key, "")) for key in ("supplier_id", "legal_name", "trading_name", "group")
            ).lower()
        ]
        return [
            {
                key: row.get(key)
                for key in ("supplier_id", "legal_name", "permit_status", "provenance", "synthetic")
            }
            for row in rows[:limit]
        ]

    @mcp.tool(annotations=read_only)
    async def get_evidence(
        run_id: str,
        claim_prefix: Annotated[
            str | None, Field(description="Only claims starting with this, e.g. 'loss.' or 'context.'")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 40,
    ) -> list[dict[str, Any]]:
        """The cited evidence ledger behind a verdict: claim, source, provenance and a short value."""
        entries = await api.get_evidence(run_id)
        picked = [
            item
            for item in entries
            if not claim_prefix or str(item.get("claim", "")).startswith(claim_prefix)
        ]
        return [
            {
                "evidence_id": item.get("evidence_id"),
                "claim": item.get("claim"),
                "source": item.get("source"),
                "provenance": item.get("provenance"),
                "synthetic": item.get("synthetic"),
                "cached": item.get("cached"),
                "value": json.dumps(item.get("value"), default=str)[:240],
            }
            for item in picked[:limit]
        ]

    @mcp.tool(annotations=read_only)
    async def get_dds(run_id: str, format: Literal["json", "xml"] = "json") -> dict[str, Any]:
        """The due diligence statement of a released run. A held run has none yet (409)."""
        return {"format": format, "document": await api.get_dds(run_id, xml=format == "xml")}

    @mcp.resource("terrasentry://runs/{run_id}/dds", mime_type="application/json")
    async def dds_resource(run_id: str) -> str:
        """The released due diligence statement as JSON."""
        return json.dumps(await api.get_dds(run_id), indent=2)

    # -- steering ---------------------------------------------------------------------------

    @mcp.tool(annotations=writes)
    async def cancel_run(run_id: str) -> dict[str, Any]:
        """Stop a run or batch that is still executing; it is marked failed."""
        await api.cancel_run(run_id)
        return run_view(await api.get_run(run_id), cockpit)

    async def ask_decision(
        run_id: str, decision: Literal["approve", "override"], note: str = ""
    ) -> Elicit[Confirmation]:
        run = await api.get_run(run_id)
        if run["state"] != "awaiting_review":
            raise ApiError(f"Run {run_id} is {run['state']}; only runs awaiting review can be decided.")
        if decision == "approve" and run.get("verdict") == "high_risk" and not note.strip():
            raise ApiError("Approving a high-risk supplier overrides the rubric: pass a note saying why.")
        label = "Approve" if decision == "approve" else "Block"
        suffix = f" Note: {note.strip()}" if note.strip() else ""
        return Elicit(
            f"{label} supplier {run.get('supplier_id')} ({run.get('record_id')})? "
            f"Rubric verdict: {run.get('verdict')}. "
            f"{_sap_effect(decision, run.get('erp_mode', 'auto'))}{suffix}",
            Confirmation,
        )

    @mcp.tool(annotations=consequential)
    async def record_review_decision(
        run_id: str,
        decision: Annotated[
            Literal["approve", "override"],
            Field(description="approve = approve the supplier; override = block the supplier"),
        ],
        note: Annotated[str, Field(description="Required when approving a high_risk supplier")] = "",
        reviewer: str = "mcp-user",
        *,
        confirmation: Annotated[ElicitationResult[Confirmation], Resolve(ask_decision)],
    ) -> dict[str, Any]:
        """Record the human decision on a held run. The user is asked to confirm before anything happens.

        Releases the statement. What happens in SAP depends on the run's erp mode. The rubric verdict
        stays on the record whatever is decided.
        """
        if not (isinstance(confirmation, AcceptedElicitation) and confirmation.data.confirm):
            return {"recorded": False, "reason": "The user did not confirm the decision."}
        await api.decide(run_id, decision=decision, reviewer=reviewer, note=note)
        return {"recorded": True, **run_view(await api.get_run(run_id), cockpit)}

    async def ask_erp(run_id: str) -> Elicit[Confirmation]:
        run = await api.get_run(run_id)
        pending = run.get("erp_pending")
        if not pending:
            raise ApiError(f"Run {run_id} has no SAP change waiting ({_next_step(run)})")
        verb = "approve" if pending == "approved" else "block"
        return Elicit(
            f"Apply to SAP now: {verb} vendor {run.get('supplier_id')} (run {run_id}, "
            f"rubric verdict {run.get('verdict')})?",
            Confirmation,
        )

    @mcp.tool(annotations=consequential)
    async def confirm_erp_action(
        run_id: str,
        *,
        confirmation: Annotated[ElicitationResult[Confirmation], Resolve(ask_erp)],
    ) -> dict[str, Any]:
        """Apply the SAP change a finished run is waiting on. The user is asked to confirm first."""
        if not (isinstance(confirmation, AcceptedElicitation) and confirmation.data.confirm):
            return {"applied": False, "reason": "The user did not confirm the SAP change."}
        await api.confirm_erp_action(run_id)
        return {"applied": True, **run_view(await api.get_run(run_id), cockpit)}

    return mcp


__all__ = ["INSTRUCTIONS", "Confirmation", "build_server", "run_view"]
