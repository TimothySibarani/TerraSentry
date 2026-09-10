"""Live preflight probe for the M1 data sources.

Run this as soon as the API keys land to validate credentials, measure latency, observe
rate-limit behaviour, and decide whether the GFW async batch endpoint should drive the
50-record run (PRD section 5 action item).

Usage:
    uv run python -m terrasentry_integrations.preflight --polygons data/seed/demo_polygons.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from terrasentry_integrations.cache import build_cache
from terrasentry_integrations.errors import IntegrationError, SourceError
from terrasentry_integrations.settings import IntegrationSettings, get_integration_settings
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient


class PreflightPolygon(BaseModel):
    id: str
    geometry: dict[str, Any]
    label: str = ""


class TimingSample(BaseModel):
    polygon_id: str
    seconds: float
    ok: bool
    detail: str | None = None


class PreflightReport(BaseModel):
    started_at: datetime
    finished_at: datetime
    missing_credentials: list[str] = Field(default_factory=list)
    gfw_samples: list[TimingSample] = Field(default_factory=list)
    firms_samples: list[TimingSample] = Field(default_factory=list)
    gfw_batch_seconds: float | None = None
    gfw_batch_status: str | None = None
    gfw_batch_rows: int | None = None
    gfw_concurrency_ladder: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def load_polygons(path: Path) -> list[PreflightPolygon]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("polygons", payload.get("features", [])) if isinstance(payload, dict) else payload
    return [PreflightPolygon.model_validate(item) for item in raw]


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _summarize(samples: Sequence[TimingSample]) -> str:
    seconds = [sample.seconds for sample in samples if sample.ok]
    ok_count = sum(1 for sample in samples if sample.ok)
    if not seconds:
        return f"{ok_count}/{len(samples)} ok"
    return (
        f"{ok_count}/{len(samples)} ok, "
        f"p50={statistics.median(seconds):.2f}s, p95={percentile(seconds, 0.95):.2f}s"
    )


async def _probe_source(
    label: str, polygons: Sequence[PreflightPolygon], probe: Any, *, refresh: bool = True
) -> list[TimingSample]:
    samples: list[TimingSample] = []
    for polygon in polygons:
        started = time.monotonic()
        try:
            await probe(polygon)
        except SourceError as exc:
            samples.append(
                TimingSample(
                    polygon_id=polygon.id,
                    seconds=time.monotonic() - started,
                    ok=False,
                    detail=str(exc),
                )
            )
        else:
            samples.append(TimingSample(polygon_id=polygon.id, seconds=time.monotonic() - started, ok=True))
    print(f"{label}: {_summarize(samples)}")
    return samples


async def _run_ladder(
    gfw: GfwClient,
    polygons: Sequence[PreflightPolygon],
    levels: Sequence[int],
    *,
    start_year: int,
    end_year: int,
) -> dict[str, float]:
    results: dict[str, float] = {}
    for level in levels:
        semaphore = asyncio.Semaphore(level)
        failures = 0

        async def _one(polygon: PreflightPolygon, semaphore: asyncio.Semaphore = semaphore) -> None:
            nonlocal failures
            async with semaphore:
                try:
                    await gfw.tree_cover_loss(
                        polygon.geometry,
                        start_year=start_year,
                        end_year=end_year,
                        refresh=True,
                    )
                except SourceError:
                    failures += 1

        started = time.monotonic()
        await asyncio.gather(*(_one(polygon) for polygon in polygons))
        results[str(level)] = round(time.monotonic() - started, 3)
        print(f"gfw ladder concurrency={level}: {results[str(level)]:.2f}s, failures={failures}")
    return results


async def _run(args: argparse.Namespace) -> int:
    settings: IntegrationSettings = get_integration_settings()
    started = datetime.now(tz=UTC)
    report = PreflightReport(started_at=started, finished_at=started)

    missing = settings.missing_credentials
    report.missing_credentials = missing
    if missing:
        print(
            "missing credentials: " + ", ".join(missing) + " — follow docs/setup/data-sources.md and retry.",
            file=sys.stderr,
        )
        return 2

    polygons = load_polygons(Path(args.polygons))[: args.limit]
    cache = build_cache(settings)
    gfw = GfwClient(settings, cache=cache)
    firms = FirmsClient(settings, cache=cache)
    end_year = datetime.now(tz=UTC).year - 1
    start_year = end_year - 5 + 1

    try:
        report.gfw_samples = await _probe_source(
            "gfw",
            polygons,
            lambda polygon: gfw.tree_cover_loss(
                polygon.geometry, start_year=start_year, end_year=end_year, refresh=True
            ),
        )
        report.firms_samples = await _probe_source(
            "firms",
            polygons,
            lambda polygon: firms.hotspots_in_polygon(polygon.geometry, days=7, refresh=True),
        )
        if args.batch and polygons:
            batch_started = time.monotonic()
            try:
                batch = await gfw.tree_cover_loss_batch(
                    [(polygon.id, polygon.geometry) for polygon in polygons],
                    start_year=start_year,
                    end_year=end_year,
                    refresh=True,
                )
            except SourceError as exc:
                report.notes.append(f"gfw batch endpoint failed: {exc}")
                print(f"gfw batch: failed ({exc})")
            else:
                report.gfw_batch_seconds = round(time.monotonic() - batch_started, 3)
                report.gfw_batch_status = batch.status
                report.gfw_batch_rows = len(batch.rows)
                print(
                    f"gfw batch: status={batch.status} rows={len(batch.rows)} "
                    f"in {report.gfw_batch_seconds:.2f}s"
                )
        if args.ladder and polygons:
            levels = [int(level) for level in args.ladder.split(",") if level.strip()]
            report.gfw_concurrency_ladder = await _run_ladder(
                gfw, polygons, levels, start_year=start_year, end_year=end_year
            )
    finally:
        await gfw.close()
        await firms.close()
        await cache.close()

    report.finished_at = datetime.now(tz=UTC)
    out_dir = Path(args.out)
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    out_path = out_dir / f"preflight-{report.started_at:%Y%m%dT%H%M%S}.json"
    await asyncio.to_thread(
        out_path.write_text,
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        "utf-8",
    )
    print(f"report -> {out_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m terrasentry_integrations.preflight",
        description="Probe GFW/FIRMS credentials, latency, rate limits, and the GFW batch API.",
    )
    parser.add_argument("--polygons", default="data/seed/demo_polygons.json")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--out", default="data/preflight")
    parser.add_argument(
        "--batch",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="evaluate the GFW async batch endpoint",
    )
    parser.add_argument(
        "--ladder",
        default="",
        help="comma-separated GFW concurrency levels to probe, e.g. 1,2,4 (off by default)",
    )
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except IntegrationError as exc:
        print(f"preflight failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
