"""Run endpoints: lifecycle, SSE, DDS release, HITL decisions, error paths."""

from __future__ import annotations

from typing import Any

import api_helpers
from fastapi.testclient import TestClient


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


def test_high_risk_scenario_completes(client: TestClient, source_router: object) -> None:
    run_id = _create(client, {"scenario": "high_risk_live"})
    detail = api_helpers.wait_for_state(client, run_id, {"complete"})

    assert detail["verdict"] == "high_risk"
    assert detail["dds"]["released"] is True


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
