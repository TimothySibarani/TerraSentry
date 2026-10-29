"""Investigation rules: screening signals, required deep dives, and the deep-dive tools."""

from __future__ import annotations

from datetime import date
from typing import Any

import agent_helpers
import pytest
from conftest import clear_layers, make_hotspots, make_loss
from terrasentry_core.agents.investigation import (
    CHECK_CONCESSION_OVERLAP,
    GET_CONTEXT_LAYERS,
    format_signals_line,
    parse_signals,
    required_deep_dives,
    screening_signals,
)
from terrasentry_core.assessment.pipeline import RecordAssessment, assess_record
from terrasentry_core.reference.pipeline import PolygonReport
from terrasentry_core.seed import generate_batch
from terrasentry_core.tools.agent_tools import ToolContext, build_source_tools
from terrasentry_core.tools.sources import PolygonSources
from terrasentry_core.tools.trace import TraceCollector
from terrasentry_integrations.sources.firms import FireDetection
from terrasentry_integrations.sources.gfw_layers import ContextLayersResult, LayerFeature
from test_assessment import design_report

FIXED_TIME = agent_helpers.FIXED_TIME


def _sources(report: PolygonReport) -> PolygonSources:
    return PolygonSources(
        polygon_id=report.polygon_id,
        loss=report.loss,
        hotspots=report.hotspots,
        layers=report.layers,
        errors=report.errors,
    )


def _assess(record: Any, sources: PolygonSources) -> RecordAssessment:
    report = PolygonReport(
        polygon_id=sources.polygon_id,
        label=record.polygon.label,
        region=record.polygon.region,
        archetype=record.polygon.archetype,
        area_ha=record.polygon.area_ha,
        loss=sources.loss,
        hotspots=sources.hotspots,
        layers=sources.layers,
        errors=sources.errors,
    )
    return assess_record(report, record, agent_helpers.datasets().operator, retrieved_at=FIXED_TIME)


def _overlap(layers: ContextLayersResult, layer_name: str, ha: float, properties: dict[str, Any]) -> None:
    layer = next(item for item in layers.layers if item.name == layer_name)
    layer.overlap_ha = ha
    layer.features = [
        LayerFeature(feature_id=f"{layer_name}-1", overlap_ha=ha, properties=properties, geometry={})
    ]


def _context(source_clients: Any) -> ToolContext:
    return ToolContext(
        gfw=source_clients.gfw,
        firms=source_clients.firms,
        datasets=agent_helpers.datasets(),
        trace=TraceCollector(clock=lambda: FIXED_TIME),
        retrieved_at=FIXED_TIME,
    )


def _tools(context: ToolContext) -> dict[str, Any]:
    return {tool.tool_name: tool for tool in build_source_tools(context)}


def test_clean_sources_need_no_signals_or_deep_dives() -> None:
    record = generate_batch().records[0]
    sources = PolygonSources(
        polygon_id=record.polygon.id, loss=make_loss(), hotspots=make_hotspots(), layers=clear_layers()
    )
    assert screening_signals(sources) == []
    assert required_deep_dives(_assess(record, sources).assessment.findings) == frozenset()


def test_loss_failure_does_not_hide_context_signals() -> None:
    record = generate_batch().records[0]
    layers = clear_layers()
    _overlap(layers, "protected_areas", 1.0, {"name": "Reserve"})
    sources = PolygonSources(
        polygon_id=record.polygon.id, loss=None, hotspots=make_hotspots(), layers=layers, errors=["loss down"]
    )
    assert screening_signals(sources) == ["protected_overlap"]
    assert required_deep_dives(_assess(record, sources).assessment.findings) == {
        GET_CONTEXT_LAYERS,
        CHECK_CONCESSION_OVERLAP,
    }


def test_unavailable_layers_are_signalled() -> None:
    layers = clear_layers()
    layers.layers[1].status = "unavailable"
    sources = PolygonSources(polygon_id="PLY-X", loss=make_loss(), hotspots=make_hotspots(), layers=layers)
    assert screening_signals(sources) == [f"context_unavailable:{layers.layers[1].name}"]


@pytest.mark.parametrize(
    ("layer", "ha", "properties", "signal", "required"),
    [
        ("protected_areas", 1.0, {"name": "Reserve"}, "protected_overlap", True),
        ("moratorium", 0.05, {"pippib_en": "Zone"}, "moratorium_overlap", True),
        ("moratorium", 5.0, {"pippib_en": "Zone"}, "moratorium_overlap", True),
        ("peatlands", 2.0, {}, "peat_overlap", True),
        ("oil_palm_concessions", 3.0, {"company": "Other Estate Ltd"}, "concession_overlap", True),
        # An unknown holder alone is a data gap, not a finding; the signal still fires.
        ("oil_palm_concessions", 3.0, {"company": None}, "concession_overlap", False),
    ],
)
def test_every_required_deep_dive_is_signalled_per_context_layer(
    layer: str, ha: float, properties: dict[str, Any], signal: str, required: bool
) -> None:
    record = next(item for item in generate_batch().records if item.consignment.commodity == "oil_palm")
    layers = clear_layers()
    _overlap(layers, layer, ha, properties)
    sources = PolygonSources(
        polygon_id=record.polygon.id, loss=make_loss(), hotspots=make_hotspots(), layers=layers
    )
    findings = _assess(record, sources).assessment.findings
    assert bool(required_deep_dives(findings)) == required
    assert signal in screening_signals(sources)


def test_required_implies_signalled_over_the_design_batch() -> None:
    batch = generate_batch()
    required_count = 0
    for record in batch.records:
        report = design_report(record)
        sources = _sources(report)
        required = required_deep_dives(_assess(record, sources).assessment.findings)
        if required:
            required_count += 1
            assert screening_signals(sources), record.record_id
    # Loss/fire archetypes exist in the design batch, so the implication is not vacuous.
    assert required_count >= 12


def test_signals_line_round_trips_through_surrounding_text() -> None:
    line = format_signals_line(["hotspots", "peat_overlap"])
    assert parse_signals(f"Done.\n**{line}**\nbye") == ["hotspots", "peat_overlap"]
    assert parse_signals(format_signals_line([])) == []
    assert parse_signals("no signals line here") == []


async def test_hotspot_payload_reports_the_detection_date_range(source_clients: Any) -> None:
    context = _context(source_clients)
    record = context.datasets.records[0]
    hotspots = make_hotspots(count=3, total_frp=30.0)
    hotspots.detections = [
        FireDetection(latitude=0.0, longitude=101.0, acq_date=day, frp=10.0)
        for day in (date(2026, 8, 20), date(2026, 8, 5), date(2026, 8, 28))
    ]
    context._sources[record.polygon.id] = PolygonSources(
        polygon_id=record.polygon.id, loss=make_loss(), hotspots=hotspots, layers=clear_layers()
    )
    tools = _tools(context)
    payload = await tools["get_fire_hotspots"](polygon_id=record.polygon.id)
    assert (payload["first_detection"], payload["last_detection"]) == ("2026-08-05", "2026-08-28")
    assert "hotspots" in payload["screening_signals"] and payload["window_end"]

    context._sources[record.polygon.id].hotspots = make_hotspots()
    quiet = await tools["get_fire_hotspots"](polygon_id=record.polygon.id)
    assert quiet["first_detection"] is None and quiet["last_detection"] is None


async def test_concession_overlap_compares_holder_and_commodity(source_clients: Any) -> None:
    context = _context(source_clients)
    record = next(item for item in context.datasets.records if item.consignment.commodity == "oil_palm")
    declared = record.legality.declared_holder or record.legality.legal_name
    layers = clear_layers()
    layer = next(item for item in layers.layers if item.name == "oil_palm_concessions")
    layer.overlap_ha = 4.0
    layer.features = [
        LayerFeature(
            feature_id="match", overlap_ha=2.0, properties={"company": declared.upper() + "."}, geometry={}
        ),
        LayerFeature(feature_id="other", overlap_ha=2.0, properties={"company": "Other Estate"}, geometry={}),
        LayerFeature(feature_id="blank", overlap_ha=0.0, properties={}, geometry={}),
    ]
    context._sources[record.polygon.id] = PolygonSources(
        polygon_id=record.polygon.id, loss=make_loss(), hotspots=make_hotspots(), layers=layers
    )
    tools = _tools(context)
    payload = await tools["check_concession_overlap"](
        polygon_id=record.polygon.id, supplier_id=record.legality.supplier_id
    )
    assert "error" not in payload and payload["overlap_found"]
    [concession] = payload["concessions"]
    matches = {item["feature_id"]: item["holder_matches"] for item in concession["features"]}
    assert matches == {"match": True, "other": False, "blank": None}
    assert concession["commodity_matches"] is True
    assert concession["mismatched_holders"] == 1 and concession["unknown_holders"] == 1
    # Conflicts sort ahead of matches so truncation can never hide one.
    assert concession["features"][-1]["holder_matches"] is True
    step = context.trace.of_kind("tool")[-1]
    assert {key: step.payload[key] for key in ("polygon_id", "supplier_id", "status")} == {
        "polygon_id": record.polygon.id,
        "supplier_id": record.legality.supplier_id,
        "status": "ok",
    }


async def test_concession_overlap_rejects_a_supplier_that_does_not_own_the_polygon(
    source_clients: Any,
) -> None:
    context = _context(source_clients)
    first, second = context.datasets.records[:2]
    tools = _tools(context)
    payload = await tools["check_concession_overlap"](
        polygon_id=first.polygon.id, supplier_id=second.legality.supplier_id
    )
    assert "does not belong" in payload["error"]
    assert context.trace.of_kind("tool")[-1].payload["result"] == payload
    step = context.trace.of_kind("tool")[-1]
    assert {key: step.payload[key] for key in ("polygon_id", "supplier_id", "status")} == {
        "polygon_id": first.polygon.id,
        "supplier_id": second.legality.supplier_id,
        "status": "error",
    }


async def test_unknown_ids_raise_and_record_no_step(source_clients: Any) -> None:
    context = _context(source_clients)
    tools = _tools(context)
    with pytest.raises(Exception, match="PLY-NOPE"):
        await tools["check_concession_overlap"](polygon_id="PLY-NOPE", supplier_id="SUP-001")
    with pytest.raises(Exception, match="PLY-NOPE"):
        await tools["get_context_layers"](polygon_id="PLY-NOPE")
    assert context.trace.of_kind("tool") == []


async def test_context_deep_dive_is_bounded_and_loss_payload_stays_compact(source_clients: Any) -> None:
    context = _context(source_clients)
    record = context.datasets.records[0]
    layers = clear_layers()
    layers.layers[0].overlap_ha = 12
    layers.layers[0].features = [
        LayerFeature(
            feature_id=str(i), overlap_ha=1, properties={"name": "Long reserve name " * 100}, geometry={}
        )
        for i in range(100)
    ]
    context._sources[record.polygon.id] = PolygonSources(
        polygon_id=record.polygon.id, loss=make_loss(), hotspots=make_hotspots(), layers=layers
    )
    tools = _tools(context)
    deep = await tools["get_context_layers"](polygon_id=record.polygon.id)
    protected = deep["layers"][0]
    assert protected["features"] == [] and protected["feature_count"] == 100
    assert "evidence artifact" in protected["feature_details_error"]
    loss = await tools["get_tree_cover_loss"](polygon_id=record.polygon.id)
    assert len(str(loss)) < 2_000
    assert loss["context_summary"][0]["feature_count"] == 100
