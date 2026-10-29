"""Run controls: ERP modes, held high-risk decisions, cancel, restart sweep, state filter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import api_helpers
import terrasentry_api.runner as runner_module
from fastapi.testclient import TestClient
from terrasentry_api.main import create_app
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_core.tools.sources import PolygonSources


def _create(client: TestClient, payload: dict[str, Any]) -> str:
    response = client.post("/runs", json=payload)
    assert response.status_code == 202, response.text
    return str(response.json()["run_id"])


def _decide(client: TestClient, run_id: str, decision: str, note: str = "reviewed") -> Any:
    return client.post(
        f"/runs/{run_id}/decision", json={"decision": decision, "reviewer": "dana", "note": note}
    )


def test_off_mode_never_touches_the_erp(client: TestClient, source_router: object) -> None:
    run_id = _create(client, {"record_id": "REC-001", "erp_mode": "off"})
    detail = api_helpers.wait_for_state(client, run_id, {"complete"})

    assert detail["erp_mode"] == "off"
    assert detail["dds"]["released"] is True
    assert detail["sap_action"] is None
    assert detail["erp_pending"] is None
    assert not [step for step in detail["steps"] if step["kind"] == "sap"]


def test_confirm_mode_waits_for_an_explicit_confirmation(client: TestClient, source_router: object) -> None:
    run_id = _create(client, {"record_id": "REC-001", "erp_mode": "confirm"})
    detail = api_helpers.wait_for_state(client, run_id, {"complete"})

    assert detail["sap_action"] is None
    assert detail["erp_pending"] == "approved"

    confirmed = client.post(f"/runs/{run_id}/erp-action")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "approved"

    after = client.get(f"/runs/{run_id}").json()
    assert after["sap_action"]["status"] == "approved"
    assert after["erp_pending"] is None
    assert len([step for step in after["steps"] if step["kind"] == "sap"]) == 1
    assert client.get(f"/dds/{run_id}").json()["erpAction"]["status"] == "approved"

    again = client.post(f"/runs/{run_id}/erp-action")
    assert again.status_code == 409


def test_held_high_risk_run_needs_a_decision_before_its_erp_action(
    client: TestClient, source_router: object
) -> None:
    run_id = _create(client, {"scenario": "high_risk_live", "erp_mode": "confirm"})
    held = api_helpers.wait_for_state(client, run_id, {"awaiting_review"})
    assert held["erp_pending"] is None
    assert client.post(f"/runs/{run_id}/erp-action").status_code == 409

    assert _decide(client, run_id, "override", "supplier blocked after review").status_code == 200
    decided = client.get(f"/runs/{run_id}").json()
    assert decided["sap_action"] is None
    assert decided["erp_pending"] == "blocked"
    assert client.get("/suppliers/SUP-002").json()["sap"]["status"] == "approved"

    assert client.post(f"/runs/{run_id}/erp-action").status_code == 200
    assert client.get("/suppliers/SUP-002").json()["sap"]["status"] == "blocked"


def test_approving_a_high_risk_supplier_needs_a_note(client: TestClient, source_router: object) -> None:
    run_id = _create(client, {"scenario": "high_risk_live"})
    api_helpers.wait_for_state(client, run_id, {"awaiting_review"})

    rejected = _decide(client, run_id, "approve", note="  ")
    assert rejected.status_code == 422
    assert "contradicts the rubric" in rejected.json()["detail"]
    assert client.get(f"/runs/{run_id}").json()["state"] == "awaiting_review"

    accepted = _decide(client, run_id, "approve", note="permit renewal evidence attached")
    assert accepted.status_code == 200, accepted.text
    detail = client.get(f"/runs/{run_id}").json()
    assert detail["verdict"] == "high_risk"
    assert detail["review"]["decision"] == "approve"
    assert detail["sap_action"]["status"] == "approved"


def test_runs_can_be_filtered_by_state(client: TestClient, source_router: object) -> None:
    held_id = _create(client, {"scenario": "high_risk_live"})
    done_id = _create(client, {"record_id": "REC-001"})
    api_helpers.wait_for_state(client, held_id, {"awaiting_review"})
    api_helpers.wait_for_state(client, done_id, {"complete"})

    held = client.get("/runs", params={"state": "awaiting_review"}).json()
    assert [row["run_id"] for row in held] == [held_id]
    assert client.get("/runs", params={"state": "nonsense"}).status_code == 422


def test_cancelling_a_running_batch_fails_it_and_its_records(
    client: TestClient, monkeypatch: Any, source_router: object
) -> None:
    async def slow_fetch(polygon: Any, **kwargs: Any) -> PolygonSources:
        await asyncio.sleep(30)
        return PolygonSources(polygon_id=polygon.id)

    monkeypatch.setattr(runner_module, "fetch_polygon_sources", slow_fetch)
    response = client.post("/batch-runs", json={"size": 4})
    batch_id = str(response.json()["run_id"])
    api_helpers.wait_for_state(client, batch_id, {"running"}, path="/batch-runs")

    cancelled = client.post(f"/runs/{batch_id}/cancel")
    assert cancelled.status_code == 202, cancelled.text
    assert cancelled.json()["state"] == "failed"
    assert cancelled.json()["error"] == "cancelled by a reviewer"

    rows = client.get(f"/batch-runs/{batch_id}/records").json()
    assert rows and {row["state"] for row in rows} == {"failed"}
    assert client.post(f"/runs/{batch_id}/cancel").status_code == 409
    assert client.post("/runs/run-missing/cancel").status_code == 404


def test_a_restart_fails_runs_the_dead_process_left_open(
    tmp_path: Path, datasets: SeedDatasets, monkeypatch: Any, source_router: object
) -> None:
    async def slow_fetch(polygon: Any, **kwargs: Any) -> PolygonSources:
        await asyncio.sleep(30)
        return PolygonSources(polygon_id=polygon.id)

    monkeypatch.setattr(runner_module, "fetch_polygon_sources", slow_fetch)
    first = create_app(services_factory=api_helpers.test_services_factory(tmp_path, datasets))
    with TestClient(first) as client:
        batch_id = str(client.post("/batch-runs", json={"size": 2}).json()["run_id"])
        api_helpers.wait_for_state(client, batch_id, {"running"}, path="/batch-runs")

    restarted = create_app(services_factory=api_helpers.test_services_factory(tmp_path, datasets))
    with TestClient(restarted) as client:
        detail = client.get(f"/runs/{batch_id}").json()
        assert detail["state"] == "failed"
        assert "interrupted by an API restart" in detail["error"]
        children = client.get(f"/batch-runs/{batch_id}/records").json()
        assert children and {row["state"] for row in children} == {"failed"}
