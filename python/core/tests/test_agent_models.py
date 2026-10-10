"""Model routing comes from the environment, not hardcoded model ids."""

from __future__ import annotations

import json
from typing import Any, cast

import boto3
import pytest
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import ProfileNotFound
from pydantic import ValidationError
from strands.models.litellm import LiteLLMModel
from strands.models.model import CacheConfig
from terrasentry_core.agents.factory import MODEL_MODES, model_bundle_for
from terrasentry_core.agents.models import ModelBundle, build_aicore_model, build_model, cap_max_tokens
from terrasentry_core.agents.scripted import ScriptedModel
from terrasentry_core.agents.settings import AgentSettings
from terrasentry_core.errors import MissingModelError, ModelConfigurationError
from terrasentry_core.tools.datasets import SeedDatasets


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
def test_prompt_cache_is_opt_in(monkeypatch: pytest.MonkeyPatch, mode: str, strategy: str | None) -> None:
    captured = _fake_bedrock(monkeypatch)

    build_model("orchestrator", settings=_settings(bedrock_prompt_cache=mode))

    cached = captured["cache_config"]
    if strategy is None:
        assert cached is None
    else:
        assert isinstance(cached, CacheConfig)
        assert cached.strategy == strategy


def test_reasoning_effort_is_sent_only_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_bedrock(monkeypatch)

    build_model("orchestrator", settings=_settings(bedrock_reasoning_effort="low"))
    assert captured["additional_request_fields"] == {"reasoning_effort": "low"}

    captured = _fake_bedrock(monkeypatch)
    build_model("orchestrator", settings=_settings(bedrock_reasoning_effort=""))
    assert "additional_request_fields" not in captured


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


def _aicore_settings(**overrides: Any) -> AgentSettings:
    values: dict[str, Any] = {
        "aicore_service_key": "",
        "aicore_client_id": "",
        "aicore_client_secret": "",
        "aicore_auth_url": "",
        "aicore_base_url": "",
        "aicore_model_orchestrator": "anthropic--claude-test",
        "aicore_model_extraction": "gpt-test",
    }
    values.update(overrides)
    return AgentSettings(**values)


def test_aicore_credentials_prefer_the_service_key() -> None:
    settings = _aicore_settings(aicore_service_key='  {"clientid": "from-key"}  ', aicore_client_id="ignored")
    assert settings.aicore_credentials == '{"clientid": "from-key"}'


def test_aicore_credentials_are_assembled_from_individual_fields() -> None:
    settings = _aicore_settings(
        aicore_client_id="id",
        aicore_client_secret="secret",
        aicore_auth_url="https://auth.example",
        aicore_base_url="https://api.example",
        aicore_resource_group="team-group",
    )
    assert json.loads(settings.aicore_credentials) == {
        "clientid": "id",
        "clientsecret": "secret",
        "url": "https://auth.example",
        "serviceurls": {"AI_API_URL": "https://api.example"},
        "resource_group": "team-group",
    }


def test_aicore_credentials_need_every_individual_field() -> None:
    settings = _aicore_settings(aicore_client_id="id", aicore_client_secret="secret")
    assert settings.aicore_credentials == ""
    assert settings.missing_aicore == ["AICORE_SERVICE_KEY"]


def test_missing_aicore_lists_every_gap() -> None:
    settings = _aicore_settings(aicore_model_orchestrator="", aicore_model_extraction="")
    assert settings.missing_aicore == [
        "AICORE_SERVICE_KEY",
        "AICORE_MODEL_ORCHESTRATOR",
        "AICORE_MODEL_EXTRACTION",
    ]
    assert _aicore_settings(aicore_service_key="{}").missing_aicore == []


def test_build_aicore_model_requires_a_configured_model() -> None:
    settings = _aicore_settings(aicore_service_key="{}", aicore_model_orchestrator="")
    with pytest.raises(MissingModelError, match="AICORE_MODEL_ORCHESTRATOR"):
        build_aicore_model("orchestrator", settings=settings)


def test_build_aicore_model_requires_credentials() -> None:
    with pytest.raises(ModelConfigurationError, match="AICORE_SERVICE_KEY"):
        build_aicore_model("orchestrator", settings=_aicore_settings())


def test_build_aicore_model_routes_through_the_sap_provider() -> None:
    settings = _aicore_settings(
        aicore_service_key='{"clientid": "id"}',
        agent_max_tokens=512,
        agent_temperature=0.2,
        agent_retry_max_attempts=3,
        agent_read_timeout_seconds=45,
    )

    model = build_aicore_model("extraction", settings=settings)

    assert isinstance(model, LiteLLMModel)
    config = cast(dict[str, Any], model.get_config())
    assert config["model_id"] == "sap/gpt-test"
    assert config["params"] == {"temperature": 0.2, "max_tokens": 512}
    assert model.client_args == {"api_key": '{"clientid": "id"}', "timeout": 45, "num_retries": 3}


def test_model_bundle_from_aicore_builds_both_roles() -> None:
    bundle = ModelBundle.from_aicore(_aicore_settings(aicore_service_key="{}"))

    assert isinstance(bundle.orchestrator, LiteLLMModel)
    assert cast(dict[str, Any], bundle.orchestrator.get_config())["model_id"] == "sap/anthropic--claude-test"
    assert cast(dict[str, Any], bundle.extraction.get_config())["model_id"] == "sap/gpt-test"


def test_cap_max_tokens_targets_litellm_params_and_plain_config() -> None:
    litellm_model = build_aicore_model("orchestrator", settings=_aicore_settings(aicore_service_key="{}"))
    cap_max_tokens(litellm_model, 64)
    params = cast(dict[str, Any], litellm_model.get_config())["params"]
    assert params == {"temperature": 0.0, "max_tokens": 64}

    scripted = ScriptedModel(default_text="ok")
    cap_max_tokens(scripted, 64)
    assert scripted.get_config()["max_tokens"] == 64


def test_factory_resolves_the_sap_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = ModelBundle(orchestrator=ScriptedModel(), extraction=ScriptedModel())
    monkeypatch.setattr(ModelBundle, "from_aicore", classmethod(lambda _cls, settings=None: sentinel))
    record = SeedDatasets.load().record_for_scenario("high_risk_live")

    assert "sap" in MODEL_MODES
    assert model_bundle_for("sap", record) is sentinel
    assert model_bundle_for("scripted", record) is not sentinel
