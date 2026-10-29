"""Live model preflight: verify SAP AI Core access for both agent roles.

Run this once before the first live agent run (docs/sap-hackathon-resources.md):

    uv run python -m terrasentry_core.agents.preflight

It builds each role's model exactly the way the orchestrator does, then makes one tiny turn per
role with ``max_tokens`` capped so the check does not reserve meaningful quota. Three more checks
cover what a one-word ping cannot:

* **structured** asks the orchestrator model for a structured reply through Strands' output tool,
  which is how the verifier returns its report. LiteLLM's SAP provider drops ``tool_choice``, so a
  model that ignores the tool would fail every run at the verifier; this finds out up front.
* **media** (optional) pings the adverse-media model, and tries the other Sonar name when the
  configured one is rejected.

SAP AI Core errors map to the fix in docs/sap-hackathon-resources.md. Exit code 0 when every gating
check passes, 1 otherwise; the media check is informational.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from strands import Agent
from strands.models.model import Model
from strands.types.exceptions import StructuredOutputException
from terrasentry_integrations.cache import MemoryCache
from terrasentry_integrations.sources.media import AdverseMediaClient

from terrasentry_core.agents.models import build_aicore_model, cap_max_tokens
from terrasentry_core.agents.settings import AgentSettings, ModelRole, get_agent_settings

_PING_PROMPT = "Reply with the single word ok."
#: Reasoning models spend tokens thinking before they answer, so the ping needs headroom even for
#: a one-word reply.
PING_MAX_TOKENS = 256
_ROLES: tuple[ModelRole, ...] = ("orchestrator", "extraction")
#: The committee lists the deployment as `sonar`; its sample code calls `sonar-pro`.
_SONAR_ALTERNATE = {"sonar": "sonar-pro", "sonar-pro": "sonar"}


class _StructuredProbe(BaseModel):
    """Smallest report that still has to go through the structured-output tool."""

    status: Literal["ok"] = Field(description="Always the literal string ok.")
    note: str = Field(description="One short sentence confirming the check ran.")


@dataclass(frozen=True)
class RoleCheck:
    """One check's outcome, safe to print (no credentials)."""

    role: str
    model_id: str
    ok: bool
    detail: str
    latency_ms: int | None = None


def friendly_error(exc: BaseException) -> str:
    """Map a LiteLLM / SAP AI Core failure onto the fix in docs/sap-hackathon-resources.md."""
    import litellm.exceptions as lx

    detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    if isinstance(exc, lx.AuthenticationError):
        return (
            "SAP AI Core rejected the credentials; refetch the team key from the keybroker "
            f"and update AICORE_SERVICE_KEY ({detail})"
        )
    if isinstance(exc, lx.NotFoundError):
        return (
            "SAP AI Core has no deployment for this model id in the resource group; check "
            f"AICORE_MODEL_* against the deployment table ({detail})"
        )
    if isinstance(exc, lx.RateLimitError):
        return f"SAP AI Core rate limit reached; retry shortly ({detail})"
    if isinstance(exc, (lx.APIConnectionError, lx.Timeout)):
        return f"cannot reach SAP AI Core; check AICORE_SERVICE_KEY serviceurls and the network ({detail})"
    return f"{type(exc).__name__}: {exc}"


def _model_id(role: ModelRole, settings: AgentSettings) -> str:
    return settings.aicore_model_for(role).strip() or "(unset)"


async def check_role(role: ModelRole, *, settings: AgentSettings, model: Model | None = None) -> RoleCheck:
    """Ping one role through the same Strands path a real run uses."""
    model_id = _model_id(role, settings)
    try:
        resolved = model or build_aicore_model(role, settings=settings)
    except Exception as exc:  # CLI boundary: construction failures map to the same fixes
        return RoleCheck(role=role, model_id=model_id, ok=False, detail=friendly_error(exc))
    cap_max_tokens(resolved, PING_MAX_TOKENS)
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
            role=role, model_id=model_id, ok=False, detail=friendly_error(exc), latency_ms=latency
        )
    latency = int((time.perf_counter() - started) * 1000)
    reply = str(result).strip() or "(empty response)"
    return RoleCheck(role=role, model_id=model_id, ok=True, detail=reply, latency_ms=latency)


async def check_structured_output(*, settings: AgentSettings, model: Model | None = None) -> RoleCheck:
    """Ask the orchestrator model for a structured reply, the way the verifier does."""
    model_id = _model_id("orchestrator", settings)
    try:
        resolved = model or build_aicore_model("orchestrator", settings=settings)
    except Exception as exc:
        return RoleCheck(role="structured", model_id=model_id, ok=False, detail=friendly_error(exc))
    cap_max_tokens(resolved, PING_MAX_TOKENS * 2)
    agent = Agent(
        model=resolved,
        system_prompt="You are a connectivity check. Answer only through the structured output tool.",
        structured_output_model=_StructuredProbe,
        callback_handler=None,
    )
    started = time.perf_counter()
    try:
        result = await agent.invoke_async("Run the structured-output check.")
    except StructuredOutputException as exc:
        latency = int((time.perf_counter() - started) * 1000)
        return RoleCheck(
            role="structured",
            model_id=model_id,
            ok=False,
            detail=(
                f"the model never used the structured-output tool ({exc}); the verifier would "
                "fail every run. LiteLLM's SAP provider drops tool_choice, so set "
                "AICORE_MODEL_ORCHESTRATOR=gpt-5.4 and run this again"
            ),
            latency_ms=latency,
        )
    except Exception as exc:
        latency = int((time.perf_counter() - started) * 1000)
        return RoleCheck(
            role="structured",
            model_id=model_id,
            ok=False,
            detail=friendly_error(exc),
            latency_ms=latency,
        )
    latency = int((time.perf_counter() - started) * 1000)
    if isinstance(result.structured_output, _StructuredProbe):
        return RoleCheck(
            role="structured",
            model_id=model_id,
            ok=True,
            detail="structured output arrived through the tool route",
            latency_ms=latency,
        )
    return RoleCheck(
        role="structured",
        model_id=model_id,
        ok=False,
        detail="the model answered in plain text instead of the structured-output tool",
        latency_ms=latency,
    )


async def _search_media(model_id: str, settings: AgentSettings) -> RoleCheck:
    client = AdverseMediaClient(
        credentials=settings.aicore_credentials, model=model_id, cache=MemoryCache(), timeout=60.0
    )
    started = time.perf_counter()
    report = await client.search("Sime Darby Plantation", "MY")
    latency = int((time.perf_counter() - started) * 1000)
    if report.status != "success":
        return RoleCheck(
            role="media",
            model_id=model_id,
            ok=False,
            detail=friendly_error(RuntimeError(report.error or "unavailable")),
            latency_ms=latency,
        )
    passthrough = (
        "provider citations passed through" if report.response_citations else "no provider citations"
    )
    return RoleCheck(
        role="media",
        model_id=model_id,
        ok=True,
        detail=f"{len(report.findings)} cited finding(s); {passthrough}",
        latency_ms=latency,
    )


async def check_media(*, settings: AgentSettings) -> RoleCheck | None:
    """Ping the optional adverse-media model; informational, it never gates the agent roles.

    The committee lists the deployment as ``sonar`` but its sample code calls ``sonar-pro``, so a
    rejected name is retried under the other one and the working name is reported.
    """
    model_id = settings.aicore_model_media.strip()
    if not model_id or not settings.aicore_credentials:
        return None
    first = await _search_media(model_id, settings)
    alternate = _SONAR_ALTERNATE.get(model_id)
    if first.ok or alternate is None:
        return first
    second = await _search_media(alternate, settings)
    if second.ok:
        return RoleCheck(
            role="media",
            model_id=model_id,
            ok=False,
            detail=(
                f"'{model_id}' failed ({first.detail}); '{alternate}' works: "
                f"set AICORE_MODEL_MEDIA={alternate}"
            ),
            latency_ms=second.latency_ms,
        )
    return first


async def run_checks(roles: Sequence[ModelRole], *, settings: AgentSettings) -> list[RoleCheck]:
    checks = [await check_role(role, settings=settings) for role in roles]
    # The verifier runs on the orchestrator model; only probe it once its plain ping works.
    orchestrator = next((c for c in checks if c.role == "orchestrator"), None)
    if orchestrator is not None and orchestrator.ok:
        checks.append(await check_structured_output(settings=settings))
    return checks


def _print_check(check: RoleCheck, suffix: str = "") -> None:
    status = "ok" if check.ok else "FAILED"
    latency = f" in {check.latency_ms} ms" if check.latency_ms is not None else ""
    print(f"{check.role:<14} : {status}{latency} - {check.model_id}{suffix}")
    print(f"                 {check.detail}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m terrasentry_core.agents.preflight",
        description="Verify live SAP AI Core access for the agent roles.",
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

    print("TerraSentry SAP AI Core preflight")
    print(f"resource group : {settings.aicore_resource_group}")
    print(f"credentials    : {'set' if settings.aicore_credentials else 'MISSING'}")
    print(
        f"retries        : {settings.agent_retry_max_attempts}, "
        f"timeout {settings.agent_read_timeout_seconds}s"
    )

    checks = asyncio.run(run_checks(roles, settings=settings))
    for check in checks:
        _print_check(check)

    media = asyncio.run(check_media(settings=settings))
    if media is not None:
        _print_check(media, " (optional)")

    if all(check.ok for check in checks):
        return 0
    sys.stdout.flush()
    print("\nlive SAP AI Core path is not ready; see docs/sap-hackathon-resources.md", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
