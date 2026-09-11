"""Full 50-record batch: design breakdown, persistence, and offline replay.

This is the M6 exit-criteria suite. The first test injects the source signal each
seeded archetype is designed to exercise and asserts the production runner maps
it back onto the intended 30/12/8 breakdown with per-record status/elapsed
persistence. The second warms a real-client cache through mocked HTTP, exports
fixtures, and re-runs the batch offline, asserting zero external calls and
identical verdicts -- the strongest "reproducible from cached data" evidence
available without §3 credentials.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import api_helpers
import pytest
import terrasentry_api.rehearsal as rehearsal
import terrasentry_api.runner as runner_module
from fastapi.testclient import TestClient
from terrasentry_api.main import create_app
from terrasentry_core.seed.schemas import BatchRecord
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_core.tools.sources import PolygonSources
from terrasentry_integrations.cache import MemoryCache
from terrasentry_integrations.fixtures import export_fixtures, prime_fixtures
from terrasentry_integrations.settings import IntegrationSettings
from terrasentry_integrations.sources.firms import FireDetection, FirmsHotspotResult
from terrasentry_integrations.sources.gfw import TreeCoverLossResult, TreeCoverLossYear

RUN_STARTED_AT = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def design_sources(record: BatchRecord) -> PolygonSources:
    """Inject the source signal each seeded archetype is designed to exercise."""
    today = datetime.now(tz=UTC).date()
    loss_ha = 0.0
    hotspot_count = 0
    hotspot_date = today
    if record.expected_archetype == "high_risk":
        if record.expected_signal == "deforestation":
            loss_ha = 8.0
        elif record.expected_signal == "fire":
            hotspot_count = 8
    elif record.expected_archetype == "ambiguous":
        if record.expected_ambiguity == "borderline_area":
            loss_ha = 2.0
        elif record.expected_ambiguity == "old_fire_scar":
            hotspot_count = 3
            hotspot_date = today - timedelta(days=25)  # older than the 7-day recency rule
    polygon = record.polygon
    detections = [
        FireDetection(
            latitude=polygon.centroid_lat,
            longitude=polygon.centroid_lon,
            acq_date=hotspot_date,
            frp=10.0,
        )
        for _ in range(hotspot_count)
    ]
    return PolygonSources(
        polygon_id=polygon.id,
        loss=TreeCoverLossResult(
            dataset="umd_tree_cover_loss",
            version="v1.13",
            geometry_hash="b" * 64,
            date_window="2021-2025",
            start_year=2021,
            end_year=2025,
            total_loss_ha=loss_ha,
            by_year=[TreeCoverLossYear(year=2022, loss_ha=loss_ha)] if loss_ha else [],
            fetched_at=RUN_STARTED_AT,
        ),
        hotspots=FirmsHotspotResult(
            source="VIIRS_SNPP_NRT",
            geometry_hash="b" * 64,
            date_window=f"{(today - timedelta(days=29)).isoformat()}..{today.isoformat()}",
            window_start=today - timedelta(days=29),
            window_end=today,
            detection_count=hotspot_count,
            total_frp=10.0 * hotspot_count,
            detections=detections,
            fetched_at=RUN_STARTED_AT,
        ),
    )


@pytest.fixture
def full_datasets() -> SeedDatasets:
    return api_helpers.load_seed_datasets()


@pytest.fixture
def full_client(tmp_path: Path, full_datasets: SeedDatasets) -> Any:
    app = create_app(
        services_factory=api_helpers.test_services_factory(tmp_path, full_datasets, batch_concurrency=8)
    )
    with TestClient(app) as client:
        yield client


def test_full_batch_matches_the_design_breakdown(
    full_client: TestClient,
    full_datasets: SeedDatasets,
    monkeypatch: Any,
) -> None:
    by_polygon = {record.polygon.id: record for record in full_datasets.records}

    async def designed_fetch(polygon: Any, **kwargs: Any) -> PolygonSources:
        return design_sources(by_polygon[polygon.id])

    monkeypatch.setattr(runner_module, "fetch_polygon_sources", designed_fetch)

    response = full_client.post("/batch-runs", json={"size": 50})
    assert response.status_code == 202, response.text
    batch_run_id = response.json()["run_id"]
    summary = api_helpers.wait_for_state(
        full_client, batch_run_id, {"complete"}, path="/batch-runs", timeout=120
    )

    assert summary["record_count"] == 50
    assert summary["verdict_breakdown"] == {"compliant": 30, "high_risk": 12, "ambiguous": 8}
    assert summary["expected_breakdown"] == {"compliant": 30, "high_risk": 12, "ambiguous": 8}
    assert summary["states"]["complete"] == 42
    assert summary["states"]["awaiting_review"] == 8
    assert summary["states"]["failed"] == 0
    assert summary["confusion"] == {
        "compliant": {"compliant": 30, "high_risk": 0, "ambiguous": 0},
        "high_risk": {"compliant": 0, "high_risk": 12, "ambiguous": 0},
        "ambiguous": {"compliant": 0, "high_risk": 0, "ambiguous": 8},
    }
    assert summary["wall_clock_seconds"] >= 0
    assert summary["average_seconds_per_record"] >= 0
    assert summary["median_seconds_per_record"] is not None
    assert summary["p95_seconds_per_record"] >= summary["median_seconds_per_record"]
    assert summary["throughput_records_per_second"] is not None
    assert summary["batch_concurrency"] == 8
    # M7: every released verdict reaches the ERP; ambiguous records wait for HITL.
    assert summary["sap_actions"] == {"approved": 30, "blocked": 12, "failed": 0}

    rows = full_client.get(f"/batch-runs/{batch_run_id}/records").json()
    assert len(rows) == 50
    assert {row["record_id"] for row in rows} == {f"REC-{index:03d}" for index in range(1, 51)}
    assert all(row["state"] in {"complete", "awaiting_review"} for row in rows)
    assert all(row["verdict"] is not None for row in rows)
    assert all(row["elapsed_seconds"] is not None for row in rows)
    assert all(row["elapsed_seconds"] >= 0 for row in rows)


async def test_offline_batch_replays_from_fixtures(
    tmp_path: Path,
    full_datasets: SeedDatasets,
    source_router: Any,
) -> None:
    fixture_dir = tmp_path / "fixtures"
    live_cache = MemoryCache()
    live_factory = api_helpers.test_services_factory(
        tmp_path, full_datasets, cache=live_cache, batch_concurrency=4
    )
    async with live_factory() as services:
        first = await rehearsal.run_recorded_batch(services=services, size=4, poll_seconds=0.01)
        exported = await export_fixtures(services.cache, fixture_dir)
    assert first["summary"]["state"] == "complete"
    assert exported >= 4
    calls_after_live = len(source_router.calls)
    assert calls_after_live >= 4

    offline_cache = MemoryCache(offline=True)
    primed = await prime_fixtures(offline_cache, fixture_dir)
    assert primed == exported
    offline_factory = api_helpers.test_services_factory(
        tmp_path, full_datasets, cache=offline_cache, batch_concurrency=4, offline=True
    )
    async with offline_factory() as services:
        assert services.offline is True
        second = await rehearsal.run_recorded_batch(services=services, size=4, poll_seconds=0.01)

    assert len(source_router.calls) == calls_after_live, "offline replay made an external call"
    assert second["summary"]["state"] == "complete"
    assert second["summary"]["verdict_breakdown"] == first["summary"]["verdict_breakdown"]
    stats = second["summary"]["metrics"]["cache_stats"]
    assert stats["offline_misses"] == 0
    assert stats["misses"] == 0
    assert stats["hits"] == primed

    first_records = {
        row["record_id"]: (row["state"], row["verdict"], row["score"]) for row in first["records"]
    }
    second_records = {
        row["record_id"]: (row["state"], row["verdict"], row["score"]) for row in second["records"]
    }
    assert first_records == second_records


async def test_prefetch_exports_fixtures_with_pinned_window(
    tmp_path: Path,
    full_datasets: SeedDatasets,
    source_router: Any,
) -> None:
    integration = IntegrationSettings(
        gfw_api_key="test-key",
        gfw_rate_limit_per_min=100_000,
        firms_map_key="TESTKEY",
        firms_rate_limit_per_10min=100_000,
        cache_backend="memory",
    )
    report = await rehearsal.prefetch_fixtures(
        datasets=full_datasets,
        integration=integration,
        fixtures_dir=tmp_path / "fixtures",
        size=4,
        as_of=date(2026, 9, 11),
        concurrency=2,
    )
    assert report.failed == 0, report.errors
    assert report.fixtures_written >= 4
    assert len(report.per_record_seconds) == 4
    assert all(path.stat().st_size > 0 for path in (tmp_path / "fixtures").glob("*.json"))


def test_prefetch_dry_run_prints_the_plan(capsys: Any) -> None:
    assert rehearsal.main(["prefetch", "--dry-run", "--size", "3"]) == 0
    output = capsys.readouterr().out
    assert "3 records" in output
    assert "REC-001" in output
    assert "FIRMS requests" in output
