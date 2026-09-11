"""Bedrock preflight: exercises the real Strands path and maps failures to fixes."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError, NoCredentialsError
from terrasentry_core.agents import preflight
from terrasentry_core.agents.scripted import ScriptedModel, ScriptedTurn
from terrasentry_core.agents.settings import AgentSettings


def _settings(**overrides: Any) -> AgentSettings:
    values: dict[str, Any] = {
        "bedrock_model_orchestrator": "orchestrator-id",
        "bedrock_model_extraction": "extraction-id",
    }
    values.update(overrides)
    return AgentSettings(**values)


def _failing_model(exc: Exception) -> ScriptedModel:
    def responder(_context: object) -> ScriptedTurn:
        raise exc

    return ScriptedModel(responder=responder)


async def test_check_role_succeeds_with_the_scripted_model() -> None:
    model = ScriptedModel(default_text="ok")

    check = await preflight.check_role("orchestrator", settings=_settings(), model=model)

    assert check.ok
    assert check.model_id == "orchestrator-id"
    assert "ok" in check.detail
    assert check.latency_ms is not None
    assert model.get_config()["max_tokens"] == preflight.PING_MAX_TOKENS


async def test_access_denied_maps_to_the_model_access_fix() -> None:
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        "Converse",
    )

    check = await preflight.check_role(
        "orchestrator", settings=_settings(), model=_failing_model(error)
    )

    assert not check.ok
    assert "bedrock:InvokeModel" in check.detail


async def test_on_demand_validation_suggests_an_inference_profile() -> None:
    error = ClientError(
        {
            "Error": {
                "Code": "ValidationException",
                "Message": "Invocation of model ID with on-demand throughput isn't supported.",
            }
        },
        "Converse",
    )

    check = await preflight.check_role(
        "extraction", settings=_settings(), model=_failing_model(error)
    )

    assert not check.ok
    assert "inference profile" in check.detail


async def test_missing_credentials_map_to_the_cli_hint() -> None:
    check = await preflight.check_role(
        "orchestrator", settings=_settings(), model=_failing_model(NoCredentialsError())
    )

    assert not check.ok
    assert "aws configure" in check.detail


def test_main_reports_failure(monkeypatch: Any, capsys: Any) -> None:
    settings = _settings()
    monkeypatch.setattr(preflight, "get_agent_settings", lambda: settings)
    monkeypatch.setattr(
        preflight,
        "build_model",
        lambda role, settings=None: _failing_model(NoCredentialsError()),
    )

    exit_code = preflight.main(["--role", "both"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "FAILED" in captured.out
    assert "docs/setup/aws.md" in captured.err


def test_main_succeeds_offline(monkeypatch: Any, capsys: Any) -> None:
    settings = _settings()
    monkeypatch.setattr(preflight, "get_agent_settings", lambda: settings)
    monkeypatch.setattr(
        preflight,
        "build_model",
        lambda role, settings=None: ScriptedModel(default_text="ok"),
    )

    exit_code = preflight.main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ok in" in captured.out
