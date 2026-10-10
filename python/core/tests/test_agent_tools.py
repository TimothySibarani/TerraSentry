"""Tool contract: ids in, canonical source payloads out, trace appended."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import date
from typing import Any, cast

import agent_helpers
import pytest
import terrasentry_core.tools.agent_tools as agent_tools
from conftest import clear_layers, make_hotspots, make_loss
from shapely.geometry import shape
from terrasentry_core.assessment.pipeline import assess_record
from terrasentry_core.reference.pipeline import PolygonReport
from terrasentry_core.tools.agent_tools import ToolContext, build_source_tools, build_verifier_tools
from terrasentry_core.tools.sources import PolygonSources
from terrasentry_core.tools.trace import TraceCollector
from terrasentry_integrations.errors import SourceUnavailable
from terrasentry_integrations.sources.gfw_layers import LayerFeature

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


async def test_concurrent_calls_share_one_snapshot_and_refresh_cannot_replace_it(
    source_clients: Any, monkeypatch: Any
) -> None:
    calls: list[bool] = []

    async def fake_fetch(polygon: Any, **kwargs: Any) -> PolygonSources:
        calls.append(kwargs["refresh"])
        await asyncio.sleep(0)
        return PolygonSources(polygon_id=polygon.id, errors=["partial failure"])

    monkeypatch.setattr(agent_tools, "fetch_polygon_sources", fake_fetch)
    context = _context(source_clients)
    polygon_id = context.datasets.get_record("REC-001").polygon.id
    first, second = await asyncio.gather(
        context.polygon_sources(polygon_id, refresh=True), context.polygon_sources(polygon_id)
    )
    assert first is second and calls == [True]
    assert await context.polygon_sources(polygon_id, refresh=True) is first
    assert first.errors == ["partial failure"] and calls == [True]
    other = _context(source_clients)
    assert await other.polygon_sources(polygon_id) is not first
    assert calls == [True, False]


@pytest.mark.parametrize("cancel", [False, True])
async def test_acquisition_failure_or_cancellation_releases_lock_for_retry(
    source_clients: Any, monkeypatch: Any, cancel: bool
) -> None:
    calls = 0
    entered = asyncio.Event()

    async def fake_fetch(polygon: Any, **kwargs: Any) -> PolygonSources:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            if cancel:
                await asyncio.Event().wait()
            raise SourceUnavailable("gfw", "injected failure")
        return PolygonSources(polygon_id=polygon.id)

    monkeypatch.setattr(agent_tools, "fetch_polygon_sources", fake_fetch)
    context = _context(source_clients)
    polygon_id = context.datasets.get_record("REC-001").polygon.id
    task = asyncio.create_task(context.polygon_sources(polygon_id))
    await entered.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else SourceUnavailable):
        await task
    assert context.collected_sources == []
    recovered = await asyncio.wait_for(context.polygon_sources(polygon_id), timeout=1)
    assert calls == 2 and await context.polygon_sources(polygon_id) is recovered


@pytest.mark.parametrize("loss_available", [False, True])
async def test_independent_context_facts_survive_partial_failures_and_geometry_stays_in_ledger(
    source_clients: Any, loss_available: bool
) -> None:
    context = _context(source_clients)
    record = context.datasets.get_record("REC-001")
    layers = clear_layers()
    large_geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [101 + 0.01 * math.cos(i * math.tau / 10000), 0.01 * math.sin(i * math.tau / 10000)]
                for i in range(10001)
            ]
        ],
    }
    layers.layers[0].overlap_ha = 1
    layers.layers[0].features = [
        LayerFeature(
            feature_id="wdpa-1",
            overlap_ha=1,
            properties={"name": "Review reserve", "desig": "National park"},
            geometry=large_geometry,
        )
    ]
    if loss_available:
        layers.layers[1].status, layers.layers[1].error = "unavailable", "injected moratorium failure"
    sources = PolygonSources(
        polygon_id=record.polygon.id,
        loss=make_loss() if loss_available else None,
        hotspots=make_hotspots(),
        layers=layers,
        errors=["moratorium unavailable" if loss_available else "loss unavailable"],
    )
    context._sources[record.polygon.id] = sources
    context.candidate = assess_record(
        PolygonReport(
            polygon_id=record.polygon.id,
            label=record.polygon.label,
            region=record.polygon.region,
            archetype=record.polygon.archetype,
            area_ha=record.polygon.area_ha,
            loss=sources.loss,
            hotspots=sources.hotspots,
            layers=layers,
            errors=sources.errors,
        ),
        record,
        context.datasets.operator,
        retrieved_at=FIXED_TIME,
    )
    assert context.candidate.assessment.verdict == "high_risk"
    tools: dict[str, Any] = {tool.tool_name: tool for tool in build_source_tools(context)}
    payload = await tools["get_tree_cover_loss"](polygon_id=record.polygon.id)
    summary = payload["context_summary"]
    assert summary[0]["overlap_ha"] == 1 and summary[0]["feature_count"] == 1
    assert "features" not in summary[0] and "protected_overlap" in payload["screening_signals"]
    assert ("error" in payload) == (not loss_available)
    assert payload["errors"] == sources.errors
    if loss_available:
        assert summary[1]["error"] == "injected moratorium failure"
    deep = await tools["get_context_layers"](polygon_id=record.polygon.id)
    feature = deep["layers"][0]["features"][0]
    assert feature["properties"]["name"] == "Review reserve" and "geometry" not in feature
    assert ("error" in deep) == loss_available
    verifier: dict[str, Any] = {tool.tool_name: tool for tool in build_verifier_tools(context)}
    claims = await verifier["get_source_claims"](polygon_id=record.polygon.id)
    assert "context_summary" not in claims["loss"] and claims["context_layers"] == {"layers": deep["layers"]}
    entry = next(entry for entry in context.candidate.evidence if entry.claim == "context.protected_areas")
    compact_entry = await verifier["get_evidence_entry"](evidence_id=entry.evidence_id)
    assert "geometry" not in compact_entry["value"]["features"][0]
    assert entry.value["features"][0]["geometry"] == large_geometry
    assert len(json.dumps(entry.model_dump(mode="json"))) > 350_000
    assert len(json.dumps(claims)) < 8_000 and len(json.dumps(compact_entry)) < 2_000


def test_oversized_feature_facts_are_explicitly_omitted_without_hiding_risk() -> None:
    layer = clear_layers().layers[0]
    layer.overlap_ha = 12
    layer.features = [
        LayerFeature(
            feature_id=str(i),
            overlap_ha=1,
            properties={"name": "Long reserve name " * 100},
            geometry={"type": "Polygon"},
        )
        for i in range(100)
    ]
    payload = agent_tools._layer_payload(layer)
    assert payload["status"] == "success" and payload["overlap_ha"] == 12
    assert payload["features"] == [] and payload["feature_count"] == 100
    assert "evidence artifact" in payload["feature_details_error"]
    assert len(json.dumps(payload).encode()) < 8 * 1024
    assert len(layer.features) == 100 and layer.features[0].properties["name"]
