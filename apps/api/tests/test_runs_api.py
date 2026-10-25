"""Run endpoints: lifecycle, SSE, DDS release, HITL decisions, error paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import api_helpers
from fastapi.testclient import TestClient
from terrasentry_api.main import create_app
from terrasentry_integrations.sources.media import StubMediaClient


def _create(client: TestClient, payload: dict[str, Any]) -> str:
    response = client.post("/runs", json=payload)
    assert response.status_code == 202, response.text
    return str(response.json()["run_id"])


def test_compliant_run_persists_and_releases_the_dds(client: TestClient, source_router: object) -> None:
    run_id = _create(client, {"record_id": "REC-001"})
    detail = api_helpers.wait_for_state(client, run_id, {"complete"})

    assert detail["verdict"] == "compliant"
    assert detail["score"] == 0
    assert detail["dds"]["released"] is True
    assert detail["assessment"] is not None
    assert detail["assessment"]["fingerprint"]
    assert detail["pending_assessment"] is None
    assert detail["verification"]["accepted"] is True
    assert detail["review"] is None
    assert len(detail["steps"]) >= 5
    assert detail["elapsed_seconds"] >= 0
    assert detail["created_at"].endswith("Z")
    assert detail["started_at"].endswith("Z")
    assert detail["finished_at"].endswith("Z")
    assert detail["dds"]["created_at"].endswith("Z")
    assert all(step["at"].endswith("Z") for step in detail["steps"])

    evidence = client.get(f"/runs/{run_id}/evidence")
    assert evidence.status_code == 200
    assert len(evidence.json()) > 0

    dds = client.get(f"/dds/{run_id}")
    assert dds.status_code == 200
    assert dds.json()["assessment"]["verdict"] == "compliant"
    xml = client.get(f"/dds/{run_id}/xml")
    assert xml.status_code == 200
    assert xml.headers["content-type"].startswith("application/xml")
    assert "SubmitDdsRequest" in xml.text


def test_high_risk_scenario_is_held_for_a_person(client: TestClient, source_router: object) -> None:
    run_id = _create(client, {"scenario": "high_risk_live"})
    detail = api_helpers.wait_for_state(client, run_id, {"awaiting_review"})

    assert detail["verdict"] == "high_risk"
    assert detail["assessment"] is None
    assert detail["pending_assessment"]["assessment"]["verdict"] == "high_risk"
    assert detail["dds"]["released"] is False
    assert detail["sap_action"] is None


def test_ambiguous_run_pauses_until_a_decision(client: TestClient, source_router: object) -> None:
    run_id = _create(client, {"record_id": "REC-003"})
    detail = api_helpers.wait_for_state(client, run_id, {"awaiting_review"})

    assert detail["assessment"] is None
    assert detail["pending_assessment"]["assessment"]["verdict"] == "ambiguous"
    assert detail["dds"]["released"] is False
    withheld = client.get(f"/dds/{run_id}")
    assert withheld.status_code == 409
    assert "withheld" in withheld.json()["detail"]

    decision = client.post(
        f"/runs/{run_id}/decision",
        json={"decision": "approve", "reviewer": "alice", "note": "checked the permit gap"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["state"] == "complete"
    released = client.get(f"/dds/{run_id}")
    assert released.status_code == 200
    assert released.json()["assessment"]["verdict"] == "ambiguous"

    second = client.post(f"/runs/{run_id}/decision", json={"decision": "override"})
    assert second.status_code == 409


def test_stream_replays_steps_and_finishes(client: TestClient, source_router: object) -> None:
    run_id = _create(client, {"record_id": "REC-001"})
    detail = api_helpers.wait_for_state(client, run_id, {"complete"})

    events = api_helpers.read_sse(client, f"/runs/{run_id}/stream")
    assert events[0]["event"] == "snapshot"
    assert events[0]["data"]["run_id"] == run_id
    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["state"] == "complete"
    steps = [event for event in events if event["event"] == "step"]
    assert len(steps) == len(detail["steps"])
    assert all(step["data"]["at"].endswith("+00:00") or step["data"]["at"].endswith("Z") for step in steps)
    assert "dds_writer" in [step["data"]["name"] for step in steps]


def test_stream_sets_hardening_headers(client: TestClient, source_router: object) -> None:
    run_id = _create(client, {"record_id": "REC-001"})
    api_helpers.wait_for_state(client, run_id, {"complete"})

    with client.stream("GET", f"/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"


def test_list_runs_reports_state_and_steps(client: TestClient, source_router: object) -> None:
    first = _create(client, {"record_id": "REC-001"})
    api_helpers.wait_for_state(client, first, {"complete"})

    response = client.get("/runs", params={"kind": "scenario"})
    assert response.status_code == 200
    runs = response.json()
    assert any(run["run_id"] == first and run["step_count"] > 0 for run in runs)


def test_list_endpoints_use_a_constant_number_of_queries(client: TestClient, source_router: object) -> None:
    from sqlalchemy import event

    for _ in range(3):
        api_helpers.wait_for_state(client, _create(client, {"record_id": "REC-001"}), {"complete"})
    batch = client.post("/batch-runs", json={"size": 4}).json()["run_id"]
    api_helpers.wait_for_state(client, batch, {"complete"})

    statements: list[str] = []
    engine = client.app.state.services.engine.sync_engine  # type: ignore[attr-defined]

    def record(*args: object) -> None:
        statements.append(str(args[2]))

    event.listen(engine, "before_cursor_execute", record)
    try:
        for path in ("/runs", "/batch-runs", f"/batch-runs/{batch}/records"):
            statements.clear()
            assert client.get(path).status_code == 200
            assert len(statements) <= 6, (path, len(statements))
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_validation_and_not_found_paths(client: TestClient) -> None:
    assert client.post("/runs", json={}).status_code == 422
    both = {"record_id": "REC-001", "scenario": "compliant_live"}
    assert client.post("/runs", json=both).status_code == 422
    missing = client.post("/runs", json={"record_id": "REC-999"})
    assert missing.status_code == 404
    assert client.get("/runs/nope").status_code == 404
    assert client.get("/runs/nope/evidence").status_code == 404
    assert client.get("/runs/nope/stream").status_code == 404
    assert client.post("/runs/nope/decision", json={"decision": "approve"}).status_code == 404


def test_high_risk_scenario_shows_retasks_with_reasons(client: TestClient, signal_router: object) -> None:
    run_id = _create(client, {"scenario": "high_risk_live", "model": "scripted"})
    detail = api_helpers.wait_for_state(client, run_id, {"awaiting_review"})

    retasks = [step for step in detail["steps"] if step["kind"] == "retask"]
    assert sorted(step["name"] for step in retasks) == ["geospatial_analyst", "legality_analyst"]
    assert all(step["detail"] and step["payload"]["ordinal"] == 2 for step in retasks)
    tools = {step["name"] for step in detail["steps"] if step["kind"] == "tool"}
    assert {"get_context_layers", "check_concession_overlap"} <= tools
    assert detail["verification"]["accepted"] is True
    assert all("protected_overlap" in step["detail"] for step in retasks)


def test_clean_scenario_has_no_retask(client: TestClient, source_router: object) -> None:
    run_id = _create(client, {"scenario": "compliant_live", "model": "scripted"})
    detail = api_helpers.wait_for_state(client, run_id, {"complete"})

    assert not [step for step in detail["steps"] if step["kind"] == "retask"]


def test_coverage_catch_fault_scenario_is_rejected_by_the_verifier(
    client: TestClient, signal_router: object
) -> None:
    run_id = _create(client, {"scenario": "coverage_catch", "model": "scripted"})
    detail = api_helpers.wait_for_state(client, run_id, {"failed"})

    assert detail["verification"]["accepted"] is False
    coverage = [item for item in detail["verification"]["challenges"] if item["kind"] == "coverage"]
    assert {item["severity"] for item in coverage} == {"error"} and len(coverage) == 2
    assert detail["error"].startswith("Verifier rejected the run: coverage:")
    assert "dds_writer" not in [step["name"] for step in detail["steps"]]
    assert detail["dds"] is None and detail["assessment"] is None


def test_coverage_catch_is_only_available_on_scripted(client: TestClient) -> None:
    response = client.post("/runs", json={"scenario": "coverage_catch", "model": "sap"})
    assert response.status_code == 422
    assert "fault injection" in response.json()["detail"]


def test_adverse_media_step_is_persisted_and_does_not_change_the_verdict(
    tmp_path: Path, signal_router: object
) -> None:
    def run(media: StubMediaClient | None) -> dict[str, Any]:
        factory = api_helpers.test_services_factory(tmp_path / ("media" if media else "plain"), media=media)
        with TestClient(create_app(services_factory=factory)) as test_client:
            run_id = _create(test_client, {"scenario": "high_risk_live", "model": "scripted"})
            return api_helpers.wait_for_state(test_client, run_id, {"awaiting_review"})

    (tmp_path / "media").mkdir()
    (tmp_path / "plain").mkdir()
    plain, with_media = run(None), run(StubMediaClient())

    steps = [
        step
        for step in with_media["steps"]
        if step["name"] == "search_adverse_media" and step["payload"]["event"] == "tool_end"
    ]
    assert len(steps) == 1 and steps[0]["payload"]["report"]["synthetic"] is True
    assert not [step for step in plain["steps"] if step["name"] == "search_adverse_media"]
    assert with_media["pending_assessment"] == plain["pending_assessment"]
