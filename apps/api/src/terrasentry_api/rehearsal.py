"""Headless batch rehearsal for M6 throughput numbers.

``prefetch`` makes the live GFW/FIRMS calls for the seed polygons, exports the
responses to a fixture directory, and reports per-source latency. ``run`` primes
those fixtures into an offline cache, executes the batch through the production
:class:`RunManager`, and writes a JSON report (wall clock, percentiles,
throughput, breakdown, cache stats) that backs ``docs/kpi.md`` and the cockpit.

Usage:
    uv run python -m terrasentry_api.rehearsal prefetch --as-of 2026-09-11
    uv run python -m terrasentry_api.rehearsal run --offline --report data/runs/batch.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from terrasentry_core.domain.enums import RunState
from terrasentry_core.errors import CoreError
from terrasentry_core.seed.schemas import BatchRecord
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_core.tools.sources import fetch_polygon_sources
from terrasentry_core.tools.trace import utc_now
from terrasentry_integrations.cache import build_cache
from terrasentry_integrations.fixtures import export_fixtures
from terrasentry_integrations.settings import (
    IntegrationSettings,
    get_integration_settings,
)
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient

from terrasentry_api.config import Settings
from terrasentry_api.config import settings as default_settings
from terrasentry_api.schemas import BatchSummary, RunSummary
from terrasentry_api.services import AppServices, build_services
from terrasentry_api.store import RunStore

_TERMINAL = {RunState.COMPLETE, RunState.FAILED, RunState.AWAITING_REVIEW}
_DEFAULT_SEED_DIR = Path("data/seed")


@dataclass
class PrefetchReport:
    """What one live prefetch produced."""

    record_count: int
    fixtures_written: int
    seconds: float
    per_record_seconds: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fixture_dir: str = ""

    @property
    def failed(self) -> int:
        return len(self.errors)

    def as_dict(self) -> dict[str, Any]:
        durations = self.per_record_seconds
        return {
            "record_count": self.record_count,
            "fixtures_written": self.fixtures_written,
            "seconds": round(self.seconds, 3),
            "average_seconds_per_record": round(sum(durations) / len(durations), 3) if durations else 0.0,
            "failed": self.failed,
            "errors": self.errors,
            "fixture_dir": self.fixture_dir,
        }


def load_datasets(seed_dir: Path) -> SeedDatasets:
    return SeedDatasets.load(
        batch_path=seed_dir / "batch_50.json",
        operator_path=seed_dir / "operator.json",
    )


async def prefetch_fixtures(
    *,
    datasets: SeedDatasets,
    integration: IntegrationSettings,
    fixtures_dir: Path,
    size: int = 50,
    as_of: date | None = None,
    concurrency: int = 4,
    window_days: int = 30,
    loss_years: int = 5,
) -> PrefetchReport:
    """Live-fetch the batch polygons, then export every cache entry as a fixture."""
    cache = build_cache(integration)
    gfw = GfwClient(integration, cache=cache)
    firms = FirmsClient(integration, cache=cache)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    records = datasets.records[:size]
    durations: list[float] = []
    errors: list[str] = []
    lock = asyncio.Lock()

    async def one(record: BatchRecord) -> None:
        async with semaphore:
            started = time.perf_counter()
            sources = await fetch_polygon_sources(
                record.polygon,
                gfw=gfw,
                firms=firms,
                window_days=window_days,
                loss_years=loss_years,
                as_of=as_of,
                refresh=True,
            )
            elapsed = time.perf_counter() - started
        async with lock:
            durations.append(elapsed)
            errors.extend(f"{record.record_id}: {error}" for error in sources.errors)

    started = time.perf_counter()
    try:
        await asyncio.gather(*(one(record) for record in records))
        fixtures = await export_fixtures(cache, fixtures_dir)
    finally:
        await gfw.close()
        await firms.close()
        await cache.close()
    return PrefetchReport(
        record_count=len(records),
        fixtures_written=fixtures,
        seconds=time.perf_counter() - started,
        per_record_seconds=durations,
        errors=errors,
        fixture_dir=str(fixtures_dir),
    )


async def build_batch_report(
    *,
    services: AppServices,
    batch_run_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Assemble the machine-readable M6 report for one finished batch."""
    async with services.session_factory() as session:
        store = RunStore(session)
        run = await store.get_run(batch_run_id)
        if run is None:
            raise RuntimeError(f"batch {batch_run_id} not found")
        states = await store.batch_state_counts(batch_run_id)
        breakdown = await store.batch_verdict_breakdown(batch_run_id)
        average = await store.batch_average_seconds(batch_run_id)
        rows = await store.list_batch_records(batch_run_id)
    summary = BatchSummary.from_run(run, states=states, breakdown=breakdown, average_seconds=average)
    records = [
        RunSummary.from_row(run_row, verdict=verdict).model_dump(mode="json") for run_row, verdict in rows
    ]
    return {
        "generated_at": utc_now().isoformat(),
        "batch_run_id": batch_run_id,
        "as_of": services.settings.rehearsal_as_of or None,
        "offline": services.offline,
        "fixtures_loaded": services.fixtures_loaded,
        "settings": {
            "batch_concurrency": services.settings.batch_concurrency,
            "firms_window_days": services.settings.firms_window_days,
            "loss_window_years": services.settings.loss_window_years,
            "run_timeout_seconds": timeout_seconds,
        },
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "summary": summary.model_dump(mode="json"),
        "records": records,
    }


async def run_recorded_batch(
    *,
    services: AppServices,
    size: int = 50,
    report_path: Path | None = None,
    timeout_seconds: float = 1800.0,
    poll_seconds: float = 0.25,
) -> dict[str, Any]:
    """Run a batch through the production services and return the M6 report."""
    batch_run_id = await services.run_manager.start_batch(size=size)
    deadline = time.monotonic() + timeout_seconds
    while True:
        async with services.session_factory() as session:
            run = await RunStore(session).get_run(batch_run_id)
        if run is None:
            raise RuntimeError(f"batch {batch_run_id} disappeared after start")
        if run.state in _TERMINAL:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"batch {batch_run_id} did not finish within {timeout_seconds}s")
        await asyncio.sleep(poll_seconds)

    report = await build_batch_report(
        services=services,
        batch_run_id=batch_run_id,
        timeout_seconds=timeout_seconds,
    )
    if report_path is not None:
        await asyncio.to_thread(report_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(report_path.write_text, json.dumps(report, indent=2), encoding="utf-8")
    return report


def print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    metrics = summary.get("metrics", {})
    print(f"batch        {report['batch_run_id']}  state={summary['state']}")
    print(
        f"records      {summary.get('record_count')}  offline={report['offline']}  "
        f"fixtures={report['fixtures_loaded']}"
    )
    print(f"wall clock   {summary.get('wall_clock_seconds')} s")
    print(
        "avg/med/p95  "
        f"{summary.get('average_seconds_per_record')} / "
        f"{summary.get('median_seconds_per_record')} / "
        f"{summary.get('p95_seconds_per_record')} s"
    )
    print(f"throughput   {summary.get('throughput_records_per_second')} records/s")
    print(f"breakdown    {summary.get('verdict_breakdown')}  expected {summary.get('expected_breakdown')}")
    print(f"confusion    {metrics.get('confusion')}")
    print(f"cache        {metrics.get('cache_stats')}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prefetch = sub.add_parser("prefetch", help="live-fetch sources and export fixtures")
    prefetch.add_argument("--size", type=int, default=50)
    prefetch.add_argument("--seed-dir", default=str(_DEFAULT_SEED_DIR))
    prefetch.add_argument("--fixtures-dir", default="data/fixtures")
    prefetch.add_argument("--as-of", default="", help="ISO date pin, e.g. 2026-09-11")
    prefetch.add_argument("--concurrency", type=int, default=4)
    prefetch.add_argument("--dry-run", action="store_true", help="print the plan only")

    run = sub.add_parser("run", help="run the batch offline from primed fixtures")
    run.add_argument("--size", type=int, default=50)
    run.add_argument("--seed-dir", default=str(_DEFAULT_SEED_DIR))
    run.add_argument("--fixtures-dir", default="data/fixtures")
    run.add_argument("--as-of", default="", help="ISO date pin, e.g. 2026-09-11")
    run.add_argument("--offline", action="store_true", help="fail fast on cache misses")
    run.add_argument("--report", default="data/runs/batch-report.json")
    run.add_argument("--timeout", type=float, default=1800.0)
    return parser


def _prefetch_command(args: argparse.Namespace, datasets: SeedDatasets) -> int:
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    integration = get_integration_settings()
    if args.dry_run:
        records = datasets.records[: args.size]
        chunk_days = max(1, min(integration.firms_day_range_max, 5))
        firms_requests = math.ceil(default_settings.firms_window_days / chunk_days)
        print(f"as_of        {as_of.isoformat() if as_of else 'today'}")
        print(
            f"plan         {len(records)} records, "
            f"{len(records)} GFW + {len(records) * firms_requests} FIRMS requests"
        )
        for record in records:
            polygon = record.polygon
            print(
                f"  {record.record_id}  {polygon.id}  {polygon.region}  "
                f"({polygon.archetype}, {polygon.area_ha:.1f} ha)"
            )
        return 0

    report = asyncio.run(
        prefetch_fixtures(
            datasets=datasets,
            integration=integration,
            fixtures_dir=Path(args.fixtures_dir),
            size=args.size,
            as_of=as_of,
            concurrency=args.concurrency,
            window_days=default_settings.firms_window_days,
            loss_years=default_settings.loss_window_years,
        )
    )
    print(json.dumps(report.as_dict(), indent=2))
    if report.failed:
        print(f"prefetch incomplete: {report.failed} record(s) had source errors", file=sys.stderr)
        return 1
    return 0


def _run_command(args: argparse.Namespace) -> int:
    base = get_integration_settings()
    api_settings: Settings = Settings().model_copy(
        update={
            "rehearsal_as_of": args.as_of or default_settings.rehearsal_as_of,
            "seed_data_dir": args.seed_dir,
        }
    )
    integration = base.model_copy(
        update={
            "cache_offline": bool(args.offline) or base.cache_offline,
            "cache_fixtures_dir": args.fixtures_dir,
        }
    )

    async def execute() -> dict[str, Any]:
        async with build_services(api_settings, integration) as services:
            return await run_recorded_batch(
                services=services,
                size=args.size,
                report_path=Path(args.report),
                timeout_seconds=args.timeout,
            )

    report = asyncio.run(execute())
    print_report(report)
    print(f"report       {args.report}")
    return 0 if report["summary"]["state"] == RunState.COMPLETE.value else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prefetch":
            return _prefetch_command(args, load_datasets(Path(args.seed_dir)))
        return _run_command(args)
    except (TimeoutError, RuntimeError, ValueError, OSError, CoreError) as exc:
        print(f"rehearsal failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PrefetchReport",
    "build_batch_report",
    "load_datasets",
    "main",
    "prefetch_fixtures",
    "print_report",
    "run_recorded_batch",
]
