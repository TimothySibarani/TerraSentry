"""Run the actual agent against Amazon Bedrock.

    python -m scripts.run_agent --supplier SUP-001 --model <bedrock-model-id>
    python -m scripts.run_agent --supplier SUP-001 --dry-run     # no AWS, no cost

``--dry-run`` swaps in a scripted fake client so the whole loop -- tool dispatch, result
marshalling, ledger writes -- can be exercised without credentials or spend. Use it to
prove the wiring before pointing at a real model, and to debug tool plumbing without
paying per token.

Cost note: Bedrock has no free tier; you pay from the first call. Run ``scripts/preflight.py``
first to confirm access, and set a budget alarm before letting a loop run unattended.
``--max-turns`` is the hard stop that keeps a confused agent from spending in circles.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from terrasentry.agent.orchestrator import Orchestrator  # noqa: E402
from terrasentry.agent.prompts import ORCHESTRATOR_SYSTEM  # noqa: E402
from terrasentry.agent.toolspec import ALL_TOOLS  # noqa: E402
from terrasentry.agent.tools_registry import ScreeningSession  # noqa: E402
from terrasentry.config import settings  # noqa: E402


class ScriptedClient:
    """A fake bedrock-runtime for --dry-run.

    Replays a fixed plan, including the adjacent-parcel branch, so the plumbing can be
    tested offline. It is NOT a model and proves nothing about whether a real model would
    choose these steps -- that is exactly the thing only a real run can tell you.
    """

    PLAN = [
        ("validate_geometry", {"supplier_id": "SUP-001"}),
        ("analyse_forest_change", {"supplier_id": "SUP-001"}),
        ("fetch_hotspots", {"supplier_id": "SUP-001", "years": 5}),
        ("lookup_entity", {"entity_name": "PT Rimba Lestari Jaya"}),
        ("investigate_adjacent_parcel",
         {"parcel_id": "PARCEL-N-114", "supplier_entity_name": "PT Rimba Lestari Jaya"}),
        ("verify_permit", {"permit_number": "IUPHHK-HT/512/2019"}),
        ("compute_risk_score", {"supplier_id": "SUP-001"}),
        ("generate_dds", {"supplier_id": "SUP-001", "commodity": "timber"}),
    ]

    def __init__(self) -> None:
        self.turn = 0

    def converse(self, **kwargs):
        if self.turn >= len(self.PLAN):
            return {
                "stopReason": "end_turn",
                "output": {"message": {"role": "assistant", "content": [
                    {"text": "Dry run complete. Every tool executed and the ledger is populated."}
                ]}},
            }
        name, args = self.PLAN[self.turn]
        self.turn += 1
        return {
            "stopReason": "tool_use",
            "output": {"message": {"role": "assistant", "content": [
                {"text": f"Calling {name}."},
                {"toolUse": {"toolUseId": f"t{self.turn}", "name": name, "input": args}},
            ]}},
        }


def build_client(region: str):
    try:
        import boto3
    except ImportError:
        raise SystemExit("boto3 is not installed. pip install -r requirements.txt")
    return boto3.client("bedrock-runtime", region_name=region)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TerraSentry agent.")
    parser.add_argument("--supplier", default="SUP-001")
    parser.add_argument("--model", default=settings.model_orchestrator,
                        help="Bedrock model id. Defaults to MODEL_ORCHESTRATOR from the environment.")
    parser.add_argument("--region", default=settings.aws_region)
    parser.add_argument("--max-turns", type=int, default=settings.max_agent_turns)
    parser.add_argument("--dry-run", action="store_true", help="Use the scripted fake client.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    session = ScreeningSession(args.supplier)

    if args.dry_run:
        client, model_id = ScriptedClient(), "dry-run"
    else:
        if not args.model:
            raise SystemExit(
                "No model id. Pass --model or set MODEL_ORCHESTRATOR in .env.\n"
                "Run 'python -m scripts.preflight' to list what your account can actually call."
            )
        client, model_id = build_client(args.region), args.model

    agent = Orchestrator(
        client=client,
        model_id=model_id,
        tools=session.build(),
        tool_specs=ALL_TOOLS,
        system_prompt=ORCHESTRATOR_SYSTEM,
        max_turns=args.max_turns,
        ledger=session.ledger,
    )

    result = agent.run(supplier=session.supplier["legal_name"], task=session.task_prompt())

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"\n=== agent run: {result.supplier} ({model_id}) ===\n")
    for turn in result.turns:
        if turn.text:
            print(f"[turn {turn.index}] {turn.text}")
        for call, res in zip(turn.tool_calls, turn.tool_results):
            print(f"    -> {call['name']}({json.dumps(call['input'])[:70]}) [{res['status']}]")
    print(f"\nstop reason: {result.stop_reason}")
    print(f"evidence recorded: {len(result.ledger)}")

    if session.assessment is not None:
        print()
        print(session.assessment.explain())
    else:
        print("\nNo score computed -- the agent never called compute_risk_score.")
    print()


if __name__ == "__main__":
    main()
