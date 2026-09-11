"""CLI: run the M3 agent graph for one seed record.

``--model scripted`` (the default) runs the whole graph with no network and no
Bedrock calls, using the deterministic verifier checks as the gate.
``--model bedrock`` uses the orchestrator/extraction models configured in
``BEDROCK_MODEL_ORCHESTRATOR`` / ``BEDROCK_MODEL_EXTRACTION`` instead; that
path needs the Day-1 Bedrock model access from docs/milestones.md section 3.

Exit codes: 0 complete, 2 awaiting human review, 1 failed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from terrasentry_integrations.cache import build_cache
from terrasentry_integrations.errors import IntegrationError
from terrasentry_integrations.settings import get_integration_settings
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient

from terrasentry_core.agents.artifacts import write_agent_run
from terrasentry_core.agents.models import ModelBundle
from terrasentry_core.agents.orchestrator import RunOrchestrator
from terrasentry_core.agents.schemas import AgentRunResult, ReviewDecision
from terrasentry_core.agents.scripted import AutopilotResponder, ScriptedModel
from terrasentry_core.agents.verification import VerificationReport
from terrasentry_core.domain.enums import Decision, RunState
from terrasentry_core.errors import CoreError
from terrasentry_core.seed.schemas import BatchRecord
from terrasentry_core.tools.datasets import DEFAULT_BATCH_PATH, DEFAULT_OPERATOR_PATH, SeedDatasets


def _scripted_models(record: BatchRecord) -> ModelBundle:
    responder = AutopilotResponder.for_record(
        record,
        structured_outputs={
            VerificationReport: VerificationReport(
                accepted=True,
                checked_claims=["llm.scripted"],
                notes=["scripted verifier: deterministic checks are the gate"],
            )
        },
    )
    return ModelBundle(
        orchestrator=ScriptedModel(responder=responder),
        extraction=ScriptedModel(responder=responder),
    )


def _models_for(model_name: str, record: BatchRecord) -> ModelBundle:
    if model_name == "bedrock":
        return ModelBundle.from_settings()
    return _scripted_models(record)


def _print_result(result: AgentRunResult, written: list[Path]) -> None:
    print(f"run            : {result.run_id}")
    print(f"record         : {result.record_id} ({result.polygon_id}, supplier {result.supplier_id})")
    print(f"state          : {result.state}")
    if result.assessment is not None:
        assessment = result.assessment.assessment
        print(f"verdict        : {assessment.verdict} (score {assessment.score})")
        print(f"rubric         : {assessment.rubric_version}")
        print(f"fingerprint    : {result.assessment.fingerprint}")
    if result.pending_assessment is not None:
        print(
            f"pending review : {result.pending_assessment.assessment.verdict} "
            f"(score {result.pending_assessment.assessment.score}); DDS withheld"
        )
    if result.verification is not None:
        report = result.verification
        print(
            f"verification   : {'accepted' if report.accepted else 'rejected'} "
            f"({len(report.challenges)} challenge(s), {len(report.checked_claims)} check(s), "
            f"llm_reviewed={report.llm_reviewed})"
        )
        for challenge in report.challenges:
            print(f"  - [{challenge.severity}] {challenge.kind}: {challenge.detail}")
    if result.review is not None:
        print(f"review         : {result.review.decision} by {result.review.reviewer}")
    print(f"trace steps    : {len(result.trace)}")
    for path in written:
        print(f"wrote          : {path}")


async def _run(args: argparse.Namespace) -> int:
    settings = get_integration_settings()
    datasets = await asyncio.to_thread(
        SeedDatasets.load,
        batch_path=Path(args.batch),
        operator_path=Path(args.operator),
    )
    record = (
        datasets.get_record(args.record)
        if args.record
        else datasets.record_for_scenario(args.scenario)
    )
    cache = build_cache(settings, offline=args.offline)
    gfw = GfwClient(settings, cache=cache)
    firms = FirmsClient(settings, cache=cache)
    try:
        orchestrator = RunOrchestrator(
            gfw=gfw,
            firms=firms,
            datasets=datasets,
            models=_models_for(args.model, record),
            window_days=args.window,
            years=args.years,
        )
        result = await orchestrator.run(record.record_id, refresh=args.refresh)
        if args.decision is not None and result.state is RunState.AWAITING_REVIEW:
            decision = ReviewDecision(
                decision=Decision(args.decision),
                reviewer=args.reviewer,
                note=args.note,
            )
            result = await orchestrator.resume(result, decision)
        written = write_agent_run(result, Path(args.out))
        _print_result(result, written)
        if result.state is RunState.AWAITING_REVIEW:
            return 2
        return 0 if result.state is RunState.COMPLETE else 1
    finally:
        await gfw.close()
        await firms.close()
        await cache.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m terrasentry_core.agents",
        description="Run the supervisor -> specialists -> verifier -> writer agent graph.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--record", help="seed record id, for example REC-001")
    target.add_argument("--scenario", help="demo scenario name, for example high_risk_live")
    parser.add_argument("--model", choices=["scripted", "bedrock"], default="scripted")
    parser.add_argument("--batch", default=str(DEFAULT_BATCH_PATH), help="seed batch dataset")
    parser.add_argument("--operator", default=str(DEFAULT_OPERATOR_PATH), help="synthetic EU operator")
    parser.add_argument("--window", type=int, default=30, help="FIRMS lookback window in days")
    parser.add_argument("--years", type=int, default=5, help="GFW loss window in years")
    parser.add_argument("--out", default="data/runs/agents", help="run artifact directory")
    parser.add_argument("--refresh", action="store_true", help="bypass the response cache")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="serve sources exclusively from the cache; fail on a cache miss",
    )
    parser.add_argument("--decision", choices=["approve", "override"], help="HITL decision to record")
    parser.add_argument("--reviewer", default="human", help="reviewer name for the HITL decision")
    parser.add_argument("--note", default="", help="review note for the HITL decision")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except (CoreError, IntegrationError) as exc:
        print(f"agent run failed: {exc}", file=sys.stderr)
        return 1


__all__ = ["main"]
