"""CLI: score an M1 reference run and emit DDS JSON/XML plus a breakdown."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from terrasentry_core.assessment.pipeline import (
    AssessmentBatch,
    assess_reference_run,
    load_batch,
    load_operator,
    load_reference_run,
    write_assessment_batch,
)
from terrasentry_core.domain.enums import FindingLevel
from terrasentry_core.errors import CoreError
from terrasentry_core.scoring import RUBRIC_VERSION


def _print_report(batch: AssessmentBatch) -> None:
    header = (
        f"{'record':<9} {'supplier':<9} {'expected':<11} {'verdict':<11} {'score':>5} {'state':<16} flags"
    )
    print(header)
    print("-" * len(header))
    for item in batch.records:
        codes = [
            finding.code.value for finding in item.assessment.findings if finding.level is FindingLevel.FLAG
        ]
        flags = ",".join(codes) if codes else "-"
        print(
            f"{item.record_id:<9} {item.supplier_id:<9} {item.expected_archetype:<11} "
            f"{item.assessment.verdict:<11} {item.assessment.score:>5} "
            f"{item.run_state:<16} {flags}"
        )
    print()
    print(f"rubric          : {batch.rubric_version}")
    print(f"records         : {batch.record_count}")
    print(f"verdicts        : {batch.verdict_breakdown}")
    print(f"expected design : {batch.expected_breakdown}")
    print("confusion (rows=expected, cols=verdict):")
    for archetype, row in batch.confusion.items():
        print(f"  {archetype:<11} {row}")
    print(f"flagged signals : {batch.signal_coverage}")


def _run(args: argparse.Namespace) -> int:
    run = load_reference_run(Path(args.run))
    batch = load_batch(Path(args.batch))
    operator = load_operator(Path(args.operator))
    result = assess_reference_run(run, batch, operator)
    written = write_assessment_batch(result, Path(args.out))
    print(f"assessed {result.record_count} record(s) from {run.run_id} (rubric {RUBRIC_VERSION})")
    print(f"wrote {len(written)} files under {args.out}")
    if not args.quiet:
        _print_report(result)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m terrasentry_core.assessment",
        description="Deterministically score a reference run and build EUDR DDS artifacts.",
    )
    parser.add_argument("--run", required=True, help="M1 reference run JSON under data/runs")
    parser.add_argument("--batch", default="data/seed/batch_50.json", help="seed batch dataset")
    parser.add_argument("--operator", default="data/seed/operator.json", help="synthetic EU operator")
    parser.add_argument("--out", default="data/dds", help="output directory for DDS artifacts")
    parser.add_argument("--quiet", action="store_true", help="only print file counts")
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except CoreError as exc:
        print(f"assessment failed: {exc}", file=sys.stderr)
        return 1
