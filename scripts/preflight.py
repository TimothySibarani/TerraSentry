"""Check what your AWS account can actually do before you spend a token.

    python -m scripts.preflight
    python -m scripts.preflight --region ap-southeast-1 --smoke-test

Answers, in order, the four questions that block a first Bedrock run:

  1. Are credentials configured at all, and which account/identity are they?
  2. Does this region have Bedrock?
  3. Which models has this account been *granted access to*? Models are not enabled by
     default -- access is requested per model, per region, in the Bedrock console.
  4. Does a real Converse call succeed? (only with --smoke-test; this one costs money)

Cost reality check: **Bedrock has no free tier.** You pay from the first API call. New
accounts (created after 15 July 2025) get $200 in promotional credits that expire after
six months. The smoke test sends about 20 tokens, so it costs a fraction of a cent -- but
set a budget alarm before running anything unattended.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from terrasentry.config import settings  # noqa: E402

OK, BAD, WARN = "  ok  ", " FAIL ", " warn "

# Regions with Bedrock that matter for an Indonesian team. Jakarta went live in
# September 2025; Singapore has the broadest model selection in the region.
SUGGESTED_REGIONS = ("ap-southeast-1", "ap-southeast-3", "us-east-1", "us-west-2")


def line(status: str, text: str, detail: str = "") -> None:
    print(f"[{status}] {text}")
    if detail:
        for row in detail.splitlines():
            print(f"         {row}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Bedrock readiness.")
    parser.add_argument("--region", default=settings.aws_region)
    parser.add_argument("--smoke-test", action="store_true",
                        help="Send one tiny Converse request. Costs a fraction of a cent.")
    parser.add_argument("--model", default=settings.model_orchestrator,
                        help="Model id for the smoke test.")
    args = parser.parse_args()

    print(f"\nTerraSentry preflight -- region {args.region}\n")

    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
    except ImportError:
        line(BAD, "boto3 not installed", "pip install -r requirements.txt")
        raise SystemExit(1)

    # -- 1. credentials ---------------------------------------------------
    try:
        ident = boto3.client("sts", region_name=args.region).get_caller_identity()
        line(OK, "Credentials found", f"account {ident['Account']}\n{ident['Arn']}")
    except NoCredentialsError:
        line(BAD, "No AWS credentials",
             "Run 'aws configure', or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.")
        raise SystemExit(1)
    except Exception as exc:
        line(BAD, "Could not verify identity", str(exc))
        raise SystemExit(1)

    # -- 2 & 3. bedrock + model access -----------------------------------
    try:
        bedrock = boto3.client("bedrock", region_name=args.region)
        models = bedrock.list_foundation_models().get("modelSummaries", [])
        line(OK, f"Bedrock reachable in {args.region}", f"{len(models)} models listed")
    except EndpointConnectionError:
        line(BAD, f"Bedrock not available in {args.region}",
             "Try one of: " + ", ".join(SUGGESTED_REGIONS))
        raise SystemExit(1)
    except ClientError as exc:
        line(BAD, "Bedrock call rejected", str(exc))
        raise SystemExit(1)

    try:
        granted = {
            e["modelId"]
            for e in bedrock.list_foundation_models(byInferenceType="ON_DEMAND").get("modelSummaries", [])
        }
    except Exception:
        granted = set()

    interesting = sorted(
        m["modelId"] for m in models
        if any(k in m["modelId"].lower() for k in ("claude", "nova"))
    )
    if interesting:
        line(OK, "Claude / Nova models visible in this region")
        for mid in interesting[:14]:
            mark = "on-demand" if mid in granted else "check access"
            print(f"           {mid}  [{mark}]")
        if len(interesting) > 14:
            print(f"           ... and {len(interesting) - 14} more")
    else:
        line(WARN, "No Claude or Nova models listed here",
             "Try ap-southeast-1, or check the region's model catalogue.")

    print()
    line(WARN, "Listing a model is not the same as having access to it",
         "Access is requested per model, per region, in the Bedrock console under\n"
         "'Model access'. A model you have not been granted returns AccessDeniedException\n"
         "on the first Converse call, not at list time.")

    # -- 4. smoke test ----------------------------------------------------
    if not args.smoke_test:
        print()
        line(WARN, "Skipped the live call", "Add --smoke-test to actually invoke a model.")
        _cost_notice()
        return

    if not args.model:
        print()
        line(BAD, "No model id for the smoke test", "Pass --model or set MODEL_ORCHESTRATOR.")
        raise SystemExit(1)

    print()
    try:
        runtime = boto3.client("bedrock-runtime", region_name=args.region)
        resp = runtime.converse(
            modelId=args.model,
            messages=[{"role": "user", "content": [{"text": "Reply with the single word: ready"}]}],
            inferenceConfig={"maxTokens": 12, "temperature": 0},
        )
        text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
        usage = resp.get("usage", {})
        line(OK, f"Converse succeeded on {args.model}",
             f"reply: {text.strip()!r}\n"
             f"tokens in/out: {usage.get('inputTokens')}/{usage.get('outputTokens')}")
        print()
        line(OK, "You are ready to run the agent",
             f"python -m scripts.run_agent --supplier SUP-001 --model {args.model}")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "AccessDeniedException":
            line(BAD, f"No access to {args.model}",
                 "Request it in the Bedrock console: Model access -> Manage model access.")
        elif code == "ValidationException":
            line(BAD, "Model id rejected",
                 "Some models require an inference-profile id (e.g. prefixed 'apac.').\n"
                 f"Original error: {exc}")
        else:
            line(BAD, f"Converse failed ({code})", str(exc))
        raise SystemExit(1)

    _cost_notice()


def _cost_notice() -> None:
    print()
    print("  Bedrock has no free tier -- you pay from the first call. New accounts get")
    print("  $200 in credits that expire after six months. Set a budget alarm in Billing")
    print("  before letting any loop run unattended.\n")


if __name__ == "__main__":
    main()
