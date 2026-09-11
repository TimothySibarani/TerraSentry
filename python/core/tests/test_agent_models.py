"""Model routing comes from the environment, not hardcoded model ids."""

from __future__ import annotations

from typing import Any, cast

import boto3
import pytest
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import ProfileNotFound
from pydantic import ValidationError
from strands.models.model import CacheConfig
from terrasentry_core.agents.models import build_model
from terrasentry_core.agents.settings import AgentSettings
from terrasentry_core.errors import MissingModelError, ModelConfigurationError


def _settings(**overrides: Any) -> AgentSettings:
    values: dict[str, Any] = {
        "bedrock_model_orchestrator": "orchestrator-model",
        "bedrock_model_extraction": "extraction-model",
    }
    values.update(overrides)
    return AgentSettings(**values)


def _fake_bedrock(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    class FakeBedrockModel:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("strands.models.BedrockModel", FakeBedrockModel)
    return captured


def test_model_for_role_reads_the_configured_ids() -> None:
    settings = _settings()
    assert settings.model_for("orchestrator") == "orchestrator-model"
    assert settings.model_for("extraction") == "extraction-model"
    assert settings.missing_models == []


def test_build_model_requires_a_configured_model() -> None:
    settings = _settings(bedrock_model_orchestrator="", bedrock_model_extraction="")
    assert settings.missing_models == ["BEDROCK_MODEL_ORCHESTRATOR", "BEDROCK_MODEL_EXTRACTION"]
    with pytest.raises(MissingModelError, match="BEDROCK_MODEL_ORCHESTRATOR"):
        build_model("orchestrator", settings=settings)
    with pytest.raises(MissingModelError, match="BEDROCK_MODEL_EXTRACTION"):
        build_model("extraction", settings=settings)


def _fake_boto_config(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_config(**kwargs: Any) -> BotocoreConfig:
        captured.update(kwargs)
        return cast(BotocoreConfig, object())

    monkeypatch.setattr("terrasentry_core.agents.models.BotocoreConfig", fake_config)
    return captured


def test_build_model_applies_adaptive_retries_and_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_bedrock(monkeypatch)
    client = _fake_boto_config(monkeypatch)
    settings = _settings(agent_retry_max_attempts=7, agent_read_timeout_seconds=90)

    build_model("orchestrator", settings=settings)

    assert captured["model_id"] == "orchestrator-model"
    assert captured["region_name"] == "us-east-1"
    assert captured["temperature"] == 0.0
    assert captured["max_tokens"] == 2048
    assert captured["cache_config"] is None
    assert client["retries"] == {"max_attempts": 7, "mode": "adaptive"}
    assert client["read_timeout"] == 90
    assert client["connect_timeout"] == 10


@pytest.mark.parametrize(
    ("mode", "strategy"),
    [("off", None), ("auto", "auto"), ("anthropic", "anthropic")],
)
def test_prompt_cache_is_opt_in(
    monkeypatch: pytest.MonkeyPatch, mode: str, strategy: str | None
) -> None:
    captured = _fake_bedrock(monkeypatch)

    build_model("orchestrator", settings=_settings(bedrock_prompt_cache=mode))

    cached = captured["cache_config"]
    if strategy is None:
        assert cached is None
    else:
        assert isinstance(cached, CacheConfig)
        assert cached.strategy == strategy


def test_profile_settings_use_a_boto_session(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_bedrock(monkeypatch)
    sessions: list[dict[str, str]] = []

    def fake_session(**kwargs: str) -> object:
        sessions.append(kwargs)
        return object()

    monkeypatch.setattr(boto3, "Session", fake_session)

    build_model("orchestrator", settings=_settings(aws_profile="terrasentry", aws_region="eu-west-1"))

    assert sessions == [{"profile_name": "terrasentry", "region_name": "eu-west-1"}]
    assert "boto_session" in captured
    assert "region_name" not in captured


def test_unknown_profile_is_a_typed_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_session(**_: str) -> object:
        raise ProfileNotFound(profile="missing")

    monkeypatch.setattr(boto3, "Session", fake_session)

    with pytest.raises(ModelConfigurationError, match="missing"):
        build_model("orchestrator", settings=_settings(aws_profile="missing"))


def test_env_profile_failure_is_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeBedrockModel:
        def __init__(self, **_: Any) -> None:
            raise ProfileNotFound(profile="env-profile")

    monkeypatch.setattr("strands.models.BedrockModel", FakeBedrockModel)

    with pytest.raises(ModelConfigurationError, match="AWS_DEFAULT_PROFILE"):
        build_model("orchestrator", settings=_settings())


@pytest.mark.parametrize(
    "overrides",
    [
        {"agent_max_tokens": 0},
        {"agent_temperature": 1.5},
        {"agent_retry_max_attempts": 0},
        {"agent_read_timeout_seconds": 0},
        {"bedrock_prompt_cache": "sometimes"},
    ],
)
def test_settings_validate_bounds(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _settings(**overrides)
