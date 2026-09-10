"""CLI for the M1 reference pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from terrasentry_integrations.cache import build_cache
from terrasentry_integrations.errors import IntegrationError
from terrasentry_integrations.settings import get_integration_settings
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient

from terrasentry_core.reference.pipeline import ReferenceRun, run_reference_pipeline
from terrasentry_core.seed.schemas import SeedDataset


def load_seed(path: Path) -> SeedDataset:
    return SeedDataset.model_validate_json(path.read_text(encoding="utf-8"))


def _print_table(run: ReferenceRun) -> None:
    header = f"{'polygon':<9} {'region':<28} {'loss_ha':>9} {'hotspots':>9} {'frp':>8}  errors"
    print(header)
    print("-" * len(header))
    for report in run.reports:
        loss = f"{report.loss.total_loss_ha:.1f}" if report.loss else "-"
        hotspots = str(report.hotspots.detection_count) if report.hotspots else "-"
        frp = f"{report.hotspots.total_frp:.1f}" if report.hotspots else "-"
        errors = "; ".join(report.errors) if report.errors else ""
        print(f"{report.polygon_id:<9} {report.region:<28} {loss:>9} {hotspots:>9} {frp:>8}  {errors}")


async def _run(args: argparse.Namespace) -> int:
    settings = get_integration_settings()
    seed = await asyncio.to_thread(load_seed, Path(args.seed))
    cache = build_cache(settings, offline=args.offline)
    gfw = GfwClient(settings, cache=cache)
    firms = FirmsClient(settings, cache=cache)
    try:
        run = await run_reference_pipeline(
            seed.polygons,
            gfw=gfw,
            firms=firms,
            cache=cache,
            window_days=args.window,
            years=args.years,
            offline=args.offline,
        )
    finally:
        await gfw.close()
        await firms.close()
        await cache.close()

    out_path = Path(args.out) / f"{run.run_id}.json"
    payload = json.dumps(run.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    await asyncio.to_thread(out_path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(out_path.write_text, payload, encoding="utf-8")
    mode = "offline" if run.offline else "live"
    print(f"run {run.run_id} ({mode}) -> {out_path}")
    _print_table(run)
    print(f"cache stats: {run.cache_stats}")
    if any(report.errors for report in run.reports):
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m terrasentry_core.reference",
        description="Run the deterministic GFW + FIRMS reference pipeline over seed polygons.",
    )
    parser.add_argument("--seed", default="data/seed/demo_polygons.json", help="seed polygon file")
    parser.add_argument("--window", type=int, default=30, help="FIRMS lookback window in days")
    parser.add_argument("--years", type=int, default=5, help="GFW loss window in years")
    parser.add_argument("--out", default="data/runs", help="run artifact directory")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="serve exclusively from the cache; fail on a cache miss",
    )
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except IntegrationError as exc:
        print(f"reference pipeline failed: {exc}", file=sys.stderr)
        return 1
