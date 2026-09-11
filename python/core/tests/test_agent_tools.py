"""Tool contract: ids in, canonical source payloads out, trace appended."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import agent_helpers
import terrasentry_core.tools.agent_tools as agent_tools
from shapely.geometry import shape
from terrasentry_core.assessment.pipeline import assess_record
from terrasentry_core.reference.pipeline import PolygonReport
from terrasentry_core.tools.agent_tools import ToolContext, build_source_tools, build_verifier_tools
from terrasentry_core.tools.sources import PolygonSources
from terrasentry_core.tools.trace import TraceCollector

FIXED_TIME = agent_helpers.FIXED_TIME


def _context(source_clients: Any) -> ToolContext:
    return ToolContext(
        gfw=source_clients.gfw,
        firms=source_clients.firms,
        datasets=agent_helpers.datasets(),
        trace=TraceCollector(clock=lambda: FIXED_TIME),
        retrieved_at=FIXED_TIME,
    )


def _bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = shape(geometry).bounds
    return (round(minx, 4), round(miny, 4), round(maxx, 4), round(maxy, 4))


async def test_source_tools_return_canonical_payloads(source_router, source_clients) -> None:
    context = _context(source_clients)
    tools: dict[str, Any] = {tool.tool_name: tool for tool in build_source_tools(context)}
    record = context.datasets.get_record("REC-001")

    loss = await tools["get_tree_cover_loss"](polygon_id=record.polygon.id)
    assert loss["total_loss_ha"] == agent_helpers.gfw_loss_for(record.polygon.geometry)
    start_year = loss["by_year"][0]["year"]
    assert loss["date_window"] == f"{start_year}-{start_year + 4}"

    hotspots = await tools["get_fire_hotspots"](polygon_id=record.polygon.id)
    assert hotspots["detection_count"] == agent_helpers.firms_count_for(_bbox(record.polygon.geometry))

    legality = await tools["get_legality_record"](supplier_id=record.supplier_id)
    assert legality["synthetic"] is True
    assert legality["disclosure"]

    consignment = await tools["get_consignment"](record_id=record.record_id)
    assert consignment["hs_heading"] == record.consignment.hs_heading

    assert context.trace.names_of_kind("tool") == [
        "get_tree_cover_loss",
        "get_fire_hotspots",
        "get_legality_record",
        "get_consignment",
    ]


async def test_polygon_sources_are_fetched_once_per_run(source_router, source_clients) -> None:
    context = _context(source_clients)
    record = context.datasets.get_record("REC-001")
    tools: dict[str, Any] = {tool.tool_name: tool for tool in build_source_tools(context)}

    await tools["get_tree_cover_loss"](polygon_id=record.polygon.id)
    await tools["get_tree_cover_loss"](polygon_id=record.polygon.id)

    assert source_router.routes[0].call_count == 1
    assert len(context.collected_sources) == 1


async def test_polygon_sources_forwards_the_pinned_as_of(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    async def fake_fetch(polygon: Any, **kwargs: Any) -> PolygonSources:
        captured.update(kwargs)
        return PolygonSources(polygon_id=polygon.id)

    monkeypatch.setattr(agent_tools, "fetch_polygon_sources", fake_fetch)
    context = ToolContext(
        gfw=cast(Any, None),
        firms=cast(Any, None),
        datasets=agent_helpers.datasets(),
        trace=TraceCollector(clock=lambda: FIXED_TIME),
        as_of=date(2026, 9, 11),
    )
    record = context.datasets.get_record("REC-001")

    sources = await context.polygon_sources(record.polygon.id)

    assert sources.polygon_id == record.polygon.id
    assert captured["as_of"] == date(2026, 9, 11)


async def test_verifier_tools_are_read_only(source_router, source_clients) -> None:
    context = _context(source_clients)
    tools = {tool.tool_name: tool for tool in build_verifier_tools(context)}
    assert set(tools) == {
        "get_source_claims",
        "get_assessment",
        "list_evidence_claims",
        "get_evidence_entry",
    }
    assert not any(name in tools for name in ("assess_record", "dds_writer", "commit"))


async def test_verifier_tools_inspect_the_candidate(source_router, source_clients) -> None:
    context = _context(source_clients)
    record = context.datasets.get_record("REC-001")
    sources = await context.polygon_sources(record.polygon.id)
    polygon = record.polygon
    context.candidate = assess_record(
        PolygonReport(
            polygon_id=polygon.id,
            label=polygon.label,
            region=polygon.region,
            archetype=polygon.archetype,
            area_ha=polygon.area_ha,
            loss=sources.loss,
            hotspots=sources.hotspots,
            errors=list(sources.errors),
        ),
        record,
        context.datasets.operator,
        retrieved_at=FIXED_TIME,
    )
    tools: dict[str, Any] = {tool.tool_name: tool for tool in build_verifier_tools(context)}

    claims = await tools["get_source_claims"](polygon_id=polygon.id)
    assert claims["loss"]["total_loss_ha"] == agent_helpers.gfw_loss_for(polygon.geometry)
    assert claims["errors"] == []

    assessment = await tools["get_assessment"](supplier_id=record.supplier_id)
    assert assessment["fingerprint"] == context.candidate.fingerprint
    assert assessment["verdict"] == context.candidate.assessment.verdict.value

    ledger = await tools["list_evidence_claims"]()
    assert ledger and all(item["evidence_id"].startswith("EV-") for item in ledger)

    entry = await tools["get_evidence_entry"](evidence_id=ledger[0]["evidence_id"])
    assert entry["evidence_id"] == ledger[0]["evidence_id"]

    missing = await tools["get_evidence_entry"](evidence_id="EV-missing")
    assert missing["error"] == "evidence id is not in the ledger"
    wrong_supplier = await tools["get_assessment"](supplier_id="SUP-OTHER")
    assert wrong_supplier["error"] == "no candidate assessment is available"
