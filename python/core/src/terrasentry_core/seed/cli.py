"""CLI entry point: regenerate the committed seed datasets under ``data/seed``."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from terrasentry_core.seed.generator import (
    DEFAULT_RNG_SEED,
    demo_dataset,
    generate_batch,
    legality_dataset,
    operator_dataset,
)


def _write(path: Path, model: BaseModel) -> None:
    path.write_text(
        json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m terrasentry_core.seed",
        description="Generate deterministic synthetic seed data for TerraSentry.",
    )
    parser.add_argument("--out-dir", default="data/seed", help="output directory")
    parser.add_argument("--seed", type=int, default=DEFAULT_RNG_SEED, help="RNG seed")
    args = parser.parse_args(argv)

    batch = generate_batch(rng_seed=args.seed)
    demo = demo_dataset(batch)
    legality = legality_dataset(batch)
    operator = operator_dataset(batch)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write(out_dir / "demo_polygons.json", demo)
    _write(out_dir / "legality.json", legality)
    _write(out_dir / "operator.json", operator)
    _write(out_dir / "batch_50.json", batch)

    live = [polygon.scenario for polygon in demo.polygons if polygon.scenario]
    print(
        f"wrote {len(batch.records)} batch records {batch.distribution} "
        f"and {len(demo.polygons)} demo polygons to {out_dir}"
    )
    print(f"live scenarios: {', '.join(live) if live else 'none'}")
    return 0
