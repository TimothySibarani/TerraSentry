"""Command-line screening -- no AWS required.

    python -m scripts.run_screening --supplier SUP-001
    python -m scripts.run_screening --supplier SUP-002 --json
    python -m scripts.run_screening --list

Thin wrapper. All logic lives in ``rimba.pipeline`` so the CLI and the web panel
(``scripts/serve.py``) run exactly the same code path. If the two ever disagree, that is
a bug.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rimba import pipeline  # noqa: E402

ICON = {"done": "ok  ", "flag": "FLAG", "blocked": "STOP", "info": "  ->"}


def print_step(step: pipeline.Step) -> None:
    print(f"  [{ICON.get(step.status, '    ')}] {step.title}")
    if step.detail:
        print(f"         {step.detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a RIMBA screening over the demo dataset.")
    parser.add_argument("--supplier", help="Supplier id (e.g. SUP-001) or legal name.")
    parser.add_argument("--json", action="store_true", help="Emit the full dossier as JSON.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the step-by-step trace.")
    parser.add_argument("--list", action="store_true", help="List available demo suppliers.")
    args = parser.parse_args()

    if args.list:
        for s in pipeline.list_suppliers():
            print(f"{s['supplier_id']:<10} {s['legal_name']:<32} {s['commodity']}")
        return

    if not args.supplier:
        parser.error("--supplier is required (or use --list)")

    try:
        result = pipeline.run(
            args.supplier,
            on_step=None if (args.json or args.quiet) else print_step,
        )
    except KeyError as exc:
        raise SystemExit(str(exc))

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if result.get("blocked"):
        print("\nBLOCKED -- geometry unusable.")
        for p in result["problems"]:
            print(f"  - {p}")
        return

    print(f"\n=== {result['supplier']} ({result['supplier_id']}) ===\n")
    print(result["assessment_explained"])
    print(f"\nEvidence items recorded: {result['evidence_count']}")
    print(f"Adjacent-parcel branch taken: {result['adjacent_parcel_branch_taken']}")

    dds = result["dds"]
    print(f"\nDDS issuable: {dds['issued']}")
    if dds["gaps"]:
        print("\nGaps the supplier must close:")
        for gap in dds["gaps"]:
            print(f"  [{gap['code']}] {gap['requirement']}")
            print(f"      why: {gap['why']}")
    print()


if __name__ == "__main__":
    main()
