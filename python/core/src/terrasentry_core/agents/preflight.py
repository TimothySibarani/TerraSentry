"""Live Bedrock preflight: verify model access for both agent roles.

Run this once before the first live agent run (docs/milestones.md section 3):

    uv run python -m terrasentry_core.agents.preflight

It builds each role's model exactly the way the orchestrator does, then makes
one tiny Converse turn per role with ``max_tokens`` capped so the check does
not reserve meaningful quota. AWS errors are mapped to the fix from
docs/setup/aws.md. Exit code 0 when every checked role answers, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass

from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    PartialCredentialsError,
    ProfileNotFound,
)
from strands import Agent
from strands.models.model import Model

from terrasentry_core.agents.models import CONNECT_TIMEOUT_SECONDS, build_model, cache_config
from terrasentry_core.agents.settings import AgentSettings, ModelRole, get_agent_settings

_PING_PROMPT = "Reply with the single word ok."
PING_MAX_TOKENS = 16
_ROLES: tuple[ModelRole, ...] = ("orchestrator", "extraction")


@dataclass(frozen=True)
class RoleCheck:
    """One role's preflight outcome, safe to print (no credentials)."""

    role: ModelRole
    model_id: str
    ok: bool
    detail: str
    latency_ms: int | None = None


def friendly_error(exc: BaseException) -> str:
    """Map an AWS/SDK failure onto the fix documented in docs/setup/aws.md."""
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        code = str(error.get("Code", "ClientError"))
        message = str(error.get("Message", exc))
        if code == "AccessDeniedException":
            return (
                "AccessDeniedException: model access is not granted or the IAM policy lacks "
                "bedrock:InvokeModel / bedrock:InvokeModelWithResponseStream"
            )
        if code == "ValidationException" and "on-demand throughput" in message:
            return (
                "ValidationException: this model requires an inference profile id; pick one with "
                f"`aws bedrock list-inference-profiles` ({message})"
            )
        if code == "ThrottlingException":
            return "ThrottlingException: quota exhausted; retry or request a service-quota increase"
        return f"{code}: {message}"
    if isinstance(exc, (NoCredentialsError, PartialCredentialsError)):
        return "no AWS credentials found; run `aws configure`, set AWS_PROFILE, or use SSO login"
    if isinstance(exc, ProfileNotFound):
        return f"AWS profile not found: {exc}; check AWS_PROFILE"
    if isinstance(exc, BotoCoreError):
        return f"AWS client error: {exc}"
    return f"{type(exc).__name__}: {exc}"


async def check_role(
    role: ModelRole,
    *,
    settings: AgentSettings,
    model: Model | None = None,
) -> RoleCheck:
    """Ping one role through the same Strands path a real run uses."""
    model_id = settings.model_for(role).strip() or "(unset)"
    try:
        resolved = model or build_model(role, settings=settings)
    except Exception as exc:  # CLI boundary: construction failures map to the same fixes
        return RoleCheck(role=role, model_id=model_id, ok=False, detail=friendly_error(exc))
    resolved.update_config(max_tokens=PING_MAX_TOKENS)
    agent = Agent(
        model=resolved,
        system_prompt="You are a connectivity check. Reply with the single word ok.",
        callback_handler=None,
    )
    started = time.perf_counter()
    try:
        result = await agent.invoke_async(_PING_PROMPT)
    except Exception as exc:  # CLI boundary: map any SDK/transport failure to a fix
        latency = int((time.perf_counter() - started) * 1000)
        return RoleCheck(
            role=role,
            model_id=model_id,
            ok=False,
            detail=friendly_error(exc),
            latency_ms=latency,
        )
    latency = int((time.perf_counter() - started) * 1000)
    reply = str(result).strip() or "(empty response)"
    return RoleCheck(role=role, model_id=model_id, ok=True, detail=reply, latency_ms=latency)


async def run_checks(roles: Sequence[ModelRole], *, settings: AgentSettings) -> list[RoleCheck]:
    return [await check_role(role, settings=settings) for role in roles]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m terrasentry_core.agents.preflight",
        description="Verify Bedrock model access for the agent roles.",
    )
    parser.add_argument(
        "--role",
        choices=["orchestrator", "extraction", "both"],
        default="both",
        help="which model role to check (default: both)",
    )
    args = parser.parse_args(argv)

    settings = get_agent_settings()
    roles: tuple[ModelRole, ...] = _ROLES if args.role == "both" else (args.role,)

    print("TerraSentry Bedrock preflight")
    print(f"region         : {settings.aws_region}")
    print(f"profile        : {settings.aws_profile or '(default credential chain)'}")
    print(f"prompt cache   : {settings.bedrock_prompt_cache}")
    print(
        f"retries        : {settings.agent_retry_max_attempts} adaptive, "
        f"read timeout {settings.agent_read_timeout_seconds}s, "
        f"connect timeout {CONNECT_TIMEOUT_SECONDS}s"
    )
    if cache_config(settings) is not None:
        print("cache note     : prefixes below the model minimum are ignored by Bedrock")

    checks = asyncio.run(run_checks(roles, settings=settings))
    for check in checks:
        status = "ok" if check.ok else "FAILED"
        latency = f" in {check.latency_ms} ms" if check.latency_ms is not None else ""
        print(f"{check.role:<14} : {status}{latency} - {check.model_id}")
        print(f"                 {check.detail}")

    if all(check.ok for check in checks):
        return 0
    sys.stdout.flush()
    print("\nlive Bedrock path is not ready; see docs/setup/aws.md section 4", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
