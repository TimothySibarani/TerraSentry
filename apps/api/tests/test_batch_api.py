"""Batch endpoints: deterministic execution, metrics, streaming, bounded concurrency."""

from __future__ import annotations

import asyncio
from typing import Any

import api_helpers
import terrasentry_api.runner as runner_module
from fastapi.testclient import TestClient
from terrasentry_api.runner import nearest_rank_percentile
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
    assert summary["states"]["complete"] == 3
    assert summary["states"]["awaiting_review"] == 1
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
    assert snapshot["progress"]["completed"] == 3
    assert snapshot["progress"]["awaiting_review"] == 1
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
