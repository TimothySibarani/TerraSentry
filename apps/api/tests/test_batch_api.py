"""Batch endpoints: deterministic execution, metrics, streaming, bounded concurrency."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import api_helpers
import pytest
import terrasentry_api.runner as runner_module
from fastapi.testclient import TestClient
from terrasentry_api.main import create_app
from terrasentry_api.runner import nearest_rank_percentile
from terrasentry_core.agents.orchestrator import RunOrchestrator
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_core.tools.sources import PolygonSources


def _start_batch(client: TestClient, size: int) -> str:
    response = client.post("/batch-runs", json={"size": size})
    assert response.status_code == 202, response.text
    return str(response.json()["run_id"])


def test_batch_completes_with_the_design_breakdown(client: TestClient, source_router: object) -> None:
    batch_run_id = _start_batch(client, 4)
    summary = api_helpers.wait_for_state(client, batch_run_id, {"complete"}, path="/batch-runs")

    assert summary["record_count"] == 4
    assert summary["verdict_breakdown"] == {"compliant": 2, "high_risk": 1, "ambiguous": 1}
    # Only compliant records release on their own; high-risk and ambiguous both wait for a person.
    assert summary["states"]["complete"] == 2
    assert summary["states"]["awaiting_review"] == 2
    assert summary["states"]["failed"] == 0
    assert summary["wall_clock_seconds"] >= 0
    assert summary["average_seconds_per_record"] >= 0
    assert summary["expected_breakdown"] == {"compliant": 2, "high_risk": 1, "ambiguous": 1}
    assert summary["median_seconds_per_record"] is not None
    assert summary["p95_seconds_per_record"] is not None
    assert summary["total_record_seconds"] >= 0
    assert summary["throughput_records_per_second"] is not None
    assert summary["batch_concurrency"] == 2
    assert summary["confusion"] == {
        "compliant": {"compliant": 2, "high_risk": 0, "ambiguous": 0},
        "high_risk": {"compliant": 0, "high_risk": 1, "ambiguous": 0},
        "ambiguous": {"compliant": 0, "high_risk": 0, "ambiguous": 1},
    }
    assert summary["cache_stats"] is not None
    assert summary["cache_stats"]["writes"] >= 1

    records = client.get(f"/batch-runs/{batch_run_id}/records")
    assert records.status_code == 200
    rows = records.json()
    assert len(rows) == 4
    assert all(row["step_count"] > 0 for row in rows)
    assert {row["state"] for row in rows} == {"complete", "awaiting_review"}
    assert all(row["elapsed_seconds"] is not None for row in rows)
    assert all(row["elapsed_seconds"] >= 0 for row in rows)
    assert all(row["input_brief"]["region"] and row["input_brief"]["area_ha"] > 0 for row in rows)


def test_batch_validation(client: TestClient) -> None:
    assert client.post("/batch-runs", json={"size": 0}).status_code == 422
    assert client.post("/batch-runs", json={"size": 51}).status_code == 422
    assert client.get("/batch-runs/nope").status_code == 404
    assert client.get("/batch-runs/nope/records").status_code == 404
    assert client.get("/batch-runs/nope/stream").status_code == 404


def test_batch_stream_emits_progress(client: TestClient, monkeypatch: Any) -> None:
    async def slow_fetch(polygon: Any, **kwargs: Any) -> PolygonSources:
        await asyncio.sleep(0.05)
        return PolygonSources(polygon_id=polygon.id, errors=["slow mock"])

    monkeypatch.setattr(runner_module, "fetch_polygon_sources", slow_fetch)
    batch_run_id = _start_batch(client, 4)
    events = api_helpers.read_sse(client, f"/batch-runs/{batch_run_id}/stream")

    assert events[0]["event"] == "snapshot"
    assert events[-1]["event"] == "done"
    progress = [event for event in events if event["event"] == "progress"]
    assert progress, "expected progress events while the batch is in flight"
    assert progress[-1]["data"]["total"] == 4
    assert sum(progress[-1]["data"]["verdict_breakdown"].values()) == 4
    assert progress[-1]["data"]["elapsed_seconds"] >= 0


def test_batch_snapshot_replays_progress(client: TestClient, source_router: object) -> None:
    """A late subscriber sees cumulative counts without waiting for a new frame."""
    batch_run_id = _start_batch(client, 4)
    api_helpers.wait_for_state(client, batch_run_id, {"complete"}, path="/batch-runs")

    events = api_helpers.read_sse(client, f"/batch-runs/{batch_run_id}/stream")
    snapshot = events[0]["data"]
    assert snapshot["kind"] == "batch"
    assert snapshot["progress"]["total"] == 4
    assert snapshot["progress"]["completed"] == 2
    assert snapshot["progress"]["awaiting_review"] == 2
    assert snapshot["progress"]["failed"] == 0
    assert snapshot["progress"]["verdict_breakdown"] == {
        "compliant": 2,
        "high_risk": 1,
        "ambiguous": 1,
    }
    assert snapshot["progress"]["elapsed_seconds"] >= 0


def test_nearest_rank_percentile() -> None:
    assert nearest_rank_percentile([], 0.95) == 0.0
    assert nearest_rank_percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert nearest_rank_percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert nearest_rank_percentile([5.0], 0.95) == 5.0


def test_batch_concurrency_is_bounded(client: TestClient, monkeypatch: Any) -> None:
    in_flight = 0
    peak = 0

    async def tracked_fetch(polygon: Any, **kwargs: Any) -> PolygonSources:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return PolygonSources(polygon_id=polygon.id, errors=["mock"])

    monkeypatch.setattr(runner_module, "fetch_polygon_sources", tracked_fetch)
    batch_run_id = _start_batch(client, 4)
    api_helpers.wait_for_state(client, batch_run_id, {"complete"}, path="/batch-runs")

    assert peak == 2, "the semaphore should allow exactly batch_concurrency records at once"


# -- agent mode ------------------------------------------------------------------------------


def _start_agent_batch(client: TestClient, **payload: Any) -> str:
    response = client.post("/batch-runs", json={"mode": "agent", **payload})
    assert response.status_code == 202, response.text
    return str(response.json()["run_id"])


def _wait_batch(client: TestClient, batch_run_id: str) -> dict[str, Any]:
    return api_helpers.wait_for_state(client, batch_run_id, {"complete", "failed"}, path="/batch-runs")


def test_agent_batch_runs_the_graph_per_record_and_labels_mode_and_model(
    client: TestClient, source_router: object
) -> None:
    batch_run_id = _start_agent_batch(client, size=4, model="scripted")
    summary = _wait_batch(client, batch_run_id)

    assert summary["state"] == "complete"
    assert (summary["mode"], summary["model"]) == ("agent", "scripted")
    assert summary["record_count"] == 4 and summary["unlabelled_count"] == 0
    assert summary["batch_concurrency"] == 2
    assert summary["metrics"]["mode"] == "agent" and summary["metrics"]["model"] == "scripted"
    assert sum(summary["verdict_breakdown"].values()) == 4

    rows = client.get(f"/batch-runs/{batch_run_id}/records").json()
    parent = client.get(f"/runs/{batch_run_id}").json()
    assert len(rows) == 4
    for row in rows:
        detail = client.get(f"/runs/{row['run_id']}").json()
        assert detail["model"] == "scripted"
        kinds = {step["kind"] for step in detail["steps"]}
        assert {"agent", "verifier", "tool"} <= kinds, row["run_id"]
        assert detail["assessment_date"] == parent["assessment_date"]
        assert detail["operator_profile"] == parent["operator_profile"]


def test_agent_batch_defaults_to_the_configured_model(client: TestClient, source_router: object) -> None:
    summary = _wait_batch(client, _start_agent_batch(client, size=1))
    assert (summary["mode"], summary["model"]) == ("agent", "scripted")


def test_screening_batch_is_labelled_screening_without_a_model(
    client: TestClient, source_router: object
) -> None:
    summary = _wait_batch(client, _start_batch(client, 2))
    assert (summary["mode"], summary["model"], summary["unlabelled_count"]) == ("screening", None, 0)
    assert summary["metrics"]["mode"] == "screening" and summary["metrics"]["model"] is None
    listed = client.get("/batch-runs").json()
    assert [(item["mode"], item["model"]) for item in listed] == [("screening", None)]


def test_batch_mode_validation(client: TestClient) -> None:
    assert client.post("/batch-runs", json={"mode": "screening", "model": "scripted"}).status_code == 422
    assert client.post("/batch-runs", json={"mode": "bogus"}).status_code == 422
    too_many = [f"REC-{index:03d}" for index in range(51)]
    assert client.post("/batch-runs", json={"mode": "agent", "record_ids": too_many}).status_code == 422


def test_mixed_labelled_and_unlabelled_records_keep_the_confusion_matrix_honest(
    client: TestClient, source_router: object
) -> None:
    from test_records_api import body

    submitted = [client.post("/records", json=body()).json()["record_id"] for _ in range(2)]
    batch_run_id = _start_agent_batch(client, record_ids=["REC-001", "REC-002", *submitted], model="scripted")
    summary = _wait_batch(client, batch_run_id)

    assert summary["record_count"] == 4 and summary["unlabelled_count"] == 2
    assert summary["expected_breakdown"] == {"compliant": 1, "high_risk": 1}
    assert sum(sum(row.values()) for row in summary["confusion"].values()) == 2
    assert sum(summary["verdict_breakdown"].values()) == 4


def _track_orchestrators(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    original = RunOrchestrator.run
    state = {"in_flight": 0, "peak": 0}

    async def tracked(self: RunOrchestrator, *args: Any, **kwargs: Any) -> Any:
        state["in_flight"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        try:
            await asyncio.sleep(0.05)
            return await original(self, *args, **kwargs)
        finally:
            state["in_flight"] -= 1

    monkeypatch.setattr(RunOrchestrator, "run", tracked)
    return state


def test_agent_concurrency_is_bounded_independently_of_screening(
    tmp_path: Path, datasets: SeedDatasets, source_router: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _track_orchestrators(monkeypatch)
    factory = api_helpers.test_services_factory(
        tmp_path, datasets, batch_concurrency=1, batch_agent_concurrency=3
    )
    with TestClient(create_app(factory)) as client:
        summary = _wait_batch(client, _start_agent_batch(client, size=4, model="scripted"))
        assert state["peak"] == 3 and summary["batch_concurrency"] == 3

        screening = _wait_batch(client, _start_batch(client, 4))
        assert screening["batch_concurrency"] == 1
        assert state["in_flight"] == 0


def test_a_timed_out_child_fails_alone_and_the_batch_still_completes(
    client: TestClient, source_router: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = RunOrchestrator.run

    async def flaky(self: RunOrchestrator, record_id: str, **kwargs: Any) -> Any:
        if record_id == "REC-002":
            raise TimeoutError
        return await original(self, record_id, **kwargs)

    monkeypatch.setattr(RunOrchestrator, "run", flaky)
    batch_run_id = _start_agent_batch(client, size=3, model="scripted")
    summary = _wait_batch(client, batch_run_id)

    assert summary["state"] == "complete"
    assert summary["states"]["failed"] == 1
    failed = next(
        row for row in client.get(f"/batch-runs/{batch_run_id}/records").json() if row["state"] == "failed"
    )
    assert failed["record_id"] == "REC-002"
    detail = client.get(f"/runs/{failed['run_id']}").json()
    assert "timed out" in detail["error"]


def test_a_child_without_its_accepted_snapshot_fails_alone(
    client: TestClient, source_router: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from terrasentry_core.errors import CoreError

    original = runner_module.RunManager._accepted_context

    async def missing_for_second(self: Any, run_id: str) -> Any:
        if run_id.endswith(":REC-002"):
            raise CoreError("accepted run has no immutable assessment context")
        return await original(self, run_id)

    monkeypatch.setattr(runner_module.RunManager, "_accepted_context", missing_for_second)
    for mode_payload in ({"mode": "agent", "model": "scripted"}, {}):
        response = client.post("/batch-runs", json={"size": 3, **mode_payload})
        summary = _wait_batch(client, response.json()["run_id"])
        assert summary["state"] == "complete", mode_payload
        assert summary["states"]["failed"] == 1, mode_payload


def test_agent_batch_children_keep_the_operator_snapshot_taken_at_queue_time(
    client: TestClient, source_router: object
) -> None:
    from test_operator_settings import profile

    assert client.put("/settings/operator", json=profile()).status_code == 200
    batch_run_id = _start_agent_batch(client, size=3, model="scripted")
    assert client.put("/settings/operator", json=profile(legal_name="Later Importer")).status_code == 200
    _wait_batch(client, batch_run_id)

    rows = client.get(f"/batch-runs/{batch_run_id}/records").json()
    assert len(rows) == 3
    assert {row["operator_profile"]["legal_name"] for row in rows} == {"Declared Importer"}
    assert len({row["assessment_date"] for row in rows}) == 1
