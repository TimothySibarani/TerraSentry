from __future__ import annotations

from typing import Any

import httpx
from mcp_helpers import API, ok, run_payload

PLOT = {
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[101.0, 0.0], [101.01, 0.0], [101.01, 0.01], [101.0, 0.01], [101.0, 0.0]]],
    },
    "country": "ID",
    "label": "Block A",
    "supplier_name": "PT Contoh",
    "commodity": "wood",
    "description": "Wood pulp",
    "net_weight_kg": 25000,
    "harvest_year": 2026,
}


def _text(result: Any) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


async def test_exposes_every_workflow_as_a_tool(connect) -> None:
    async with connect() as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert names == {
        "screen_plot",
        "import_records",
        "start_batch",
        "get_run",
        "get_batch",
        "list_runs",
        "list_suppliers",
        "get_evidence",
        "get_dds",
        "cancel_run",
        "record_review_decision",
        "confirm_erp_action",
    }


async def test_confirmation_is_not_a_parameter_the_caller_can_fill(connect) -> None:
    async with connect() as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    for name in ("record_review_decision", "confirm_erp_action"):
        assert "confirmation" not in (tools[name].input_schema or {}).get("properties", {})


async def test_screen_plot_defaults_to_no_erp_change_and_returns_the_verdict(api, connect) -> None:
    api.post("/records").mock(
        return_value=ok(
            {"record_id": "REC-U-1", "supplier_id": "SUP-U-1", "polygon_id": "PLY-U-1", "area_ha": 1.2}, 201
        )
    )
    batch = api.post("/batch-runs").mock(
        return_value=ok({"run_id": "batch-aaa", "state": "queued", "record_count": 1}, 202)
    )
    api.get("/runs/batch-aaa:REC-U-1").mock(return_value=ok(run_payload("batch-aaa:REC-U-1")))

    async with connect() as client:
        result = await client.call_tool("screen_plot", PLOT)

    view = result.structured_content
    assert view["verdict"] == "compliant" and view["state"] == "complete"
    assert view["erp"] == {"mode": "off", "pending": None, "applied": None}
    assert view["cockpit_url"] == "https://cockpit.test/runs/batch-aaa%3AREC-U-1"
    sent = batch.calls.last.request.content
    assert b'"erp_mode":"off"' in sent.replace(b" ", b"") and b'"mode":"screening"' in sent.replace(b" ", b"")


async def test_screen_plot_that_outlasts_the_wait_returns_the_run_to_poll(api, connect, clock) -> None:
    api.post("/records").mock(
        return_value=ok(
            {"record_id": "REC-U-1", "supplier_id": "SUP-U-1", "polygon_id": "P", "area_ha": 1}, 201
        )
    )
    api.post("/runs").mock(return_value=ok({"run_id": "run-9", "state": "queued"}, 202))
    api.get("/runs/run-9").mock(
        return_value=ok(run_payload("run-9", state="running", verdict=None, dds=None))
    )

    async with connect() as client:
        result = await client.call_tool("screen_plot", {**PLOT, "mode": "agent", "wait_seconds": 3})

    assert result.structured_content["state"] == "running"
    assert "Still running" in result.structured_content["next_step"]
    assert clock.now >= 3


async def test_held_results_say_a_person_has_to_decide(api, connect) -> None:
    held = run_payload(
        "run-2",
        state="awaiting_review",
        verdict="high_risk",
        score=72,
        assessment=None,
        dds={"released": False},
        pending_assessment={
            "assessment": {
                "rubric_version": "1.2.0",
                "findings": [
                    {
                        "code": "protected_area",
                        "level": "flag",
                        "points": 60,
                        "detail": "Overlaps a reserve.",
                    },
                    {"code": "fire_cluster", "level": "clear", "points": 0, "detail": "No fires."},
                ],
                "data_gaps": [],
            }
        },
    )
    api.get("/runs/run-2").mock(return_value=ok(held))

    async with connect() as client:
        view = (await client.call_tool("get_run", {"run_id": "run-2"})).structured_content

    assert view["needs_decision"] is True and view["dds_released"] is False
    assert [item["code"] for item in view["findings"]] == ["protected_area"]
    assert "record_review_decision" in view["next_step"]


async def test_api_errors_reach_the_agent_as_readable_tool_errors(api, connect) -> None:
    api.post("/records").mock(
        return_value=ok(
            {"detail": [{"loc": ["body", "plot", "geometry"], "msg": "polygon is self-intersecting"}]}, 422
        )
    )

    async with connect() as client:
        result = await client.call_tool("screen_plot", PLOT)

    assert result.is_error
    assert "plot.geometry: polygon is self-intersecting" in _text(result)


async def test_unreachable_api_says_how_to_start_it(api, connect) -> None:
    api.get("/runs/run-1").mock(side_effect=httpx.ConnectError("refused"))
    async with connect() as client:
        result = await client.call_tool("get_run", {"run_id": "run-1"})
    assert result.is_error and "unreachable" in _text(result)


async def test_list_runs_filters_by_state_and_drops_batch_parents(api, connect) -> None:
    route = api.get("/runs").mock(
        return_value=ok([run_payload("a", kind="record"), run_payload("batch-1", kind="batch")])
    )
    async with connect() as client:
        rows = (await client.call_tool("list_runs", {"state": "awaiting_review"})).structured_content[
            "result"
        ]
    assert [row["run_id"] for row in rows] == ["a"]
    assert route.calls.last.request.url.params["state"] == "awaiting_review"


async def test_evidence_is_trimmed_and_filterable(api, connect) -> None:
    api.get("/runs/run-1/evidence").mock(
        return_value=ok(
            [
                {
                    "evidence_id": "EV-1",
                    "claim": "loss.total_loss_ha",
                    "source": "global_forest_watch",
                    "provenance": "real_source",
                    "value": 3.2,
                },
                {
                    "evidence_id": "EV-2",
                    "claim": "parcel.area_ha",
                    "source": "intake",
                    "provenance": "derived",
                    "value": 12,
                },
            ]
        )
    )
    async with connect() as client:
        rows = (
            await client.call_tool("get_evidence", {"run_id": "run-1", "claim_prefix": "loss."})
        ).structured_content["result"]
    assert [row["evidence_id"] for row in rows] == ["EV-1"]


async def test_import_records_reports_created_and_rejected_rows(api, connect) -> None:
    api.post("/records/import").mock(
        return_value=ok(
            {
                "total_rows": 2,
                "created": [
                    {"record_id": "REC-U-1", "supplier_id": "SUP-U-1", "legal_name": "PT A", "label": "A"}
                ],
                "errors": [{"row": 2, "field": "plot.geometry", "message": "unreadable WKT"}],
            }
        )
    )
    async with connect() as client:
        view = (
            await client.call_tool("import_records", {"csv_text": "country,label\nID,A\n"})
        ).structured_content
    assert view["created"][0]["record_id"] == "REC-U-1"
    assert view["errors"][0]["row"] == 2
    assert "start_batch" in view["next_step"]


async def test_released_dds_comes_back_as_structured_json_or_xml(api, connect) -> None:
    api.get("/dds/run-1").mock(return_value=ok({"schemaVersion": "eudr-is-v3"}))
    api.get("/dds/run-1/xml").mock(
        return_value=httpx.Response(200, text="<Envelope/>", headers={"content-type": "application/xml"})
    )
    async with connect() as client:
        as_json = (await client.call_tool("get_dds", {"run_id": "run-1"})).structured_content
        as_xml = (await client.call_tool("get_dds", {"run_id": "run-1", "format": "xml"})).structured_content
    assert as_json == {"format": "json", "document": {"schemaVersion": "eudr-is-v3"}}
    assert as_xml == {"format": "xml", "document": "<Envelope/>"}


async def test_withheld_dds_explains_itself(api, connect) -> None:
    api.get("/dds/run-2").mock(return_value=ok({"detail": "DDS withheld pending review"}, 409))
    async with connect() as client:
        result = await client.call_tool("get_dds", {"run_id": "run-2"})
    assert result.is_error and "withheld" in _text(result)


_ = API
