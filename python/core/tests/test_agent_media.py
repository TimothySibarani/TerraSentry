"""Adverse media is context only: it shows in the trace and never moves the rubric outcome."""

from __future__ import annotations

from typing import Any

import agent_helpers
import pytest
from terrasentry_core.agents.media import build_media_client
from terrasentry_core.agents.orchestrator import RunOrchestrator
from terrasentry_core.agents.settings import AgentSettings
from terrasentry_core.errors import MissingModelError, ModelConfigurationError
from terrasentry_integrations.cache import MemoryCache
from terrasentry_integrations.settings import IntegrationSettings
from terrasentry_integrations.sources.media import AdverseMediaClient, StubMediaClient


async def _run(source_clients, *, media):
    data = agent_helpers.datasets()
    record = data.record_for_scenario("high_risk_live")
    orchestrator = RunOrchestrator(
        gfw=source_clients.gfw,
        firms=source_clients.firms,
        datasets=data,
        models=agent_helpers.scripted_models(record),
        media=media,
    )
    return await orchestrator.run(record.record_id)


async def test_media_never_changes_the_assessment(source_router, source_clients) -> None:
    without = await _run(source_clients, media=None)
    with_media = await _run(source_clients, media=StubMediaClient())

    candidate = with_media.assessment or with_media.pending_assessment
    baseline = without.assessment or without.pending_assessment
    assert candidate is not None and baseline is not None
    assert candidate.fingerprint == baseline.fingerprint
    assert candidate.assessment == baseline.assessment
    assert candidate.dds == baseline.dds
    volatile = {"retrieved_at", "cached"}
    assert [entry.model_dump(exclude=volatile) for entry in candidate.evidence] == [
        entry.model_dump(exclude=volatile) for entry in baseline.evidence
    ]
    assert with_media.verification is not None and with_media.verification.accepted


async def test_media_step_is_traced_only_when_enabled(source_router, source_clients) -> None:
    without = await _run(source_clients, media=None)
    with_media = await _run(source_clients, media=StubMediaClient())

    assert not [step for step in without.trace if step.name == "search_adverse_media"]
    steps = [step for step in with_media.trace if step.name == "search_adverse_media"]
    assert len(steps) == 1
    report = steps[0].payload["report"]
    assert steps[0].payload["status"] == "ok"
    assert report["synthetic"] is True
    assert report["findings"][0]["citations"][0]["url"].startswith("https://")


def _agent(**overrides: Any) -> AgentSettings:
    """Explicit empties beat any local .env, so the test never reads real credentials."""
    values: dict[str, Any] = {
        "aicore_service_key": "",
        "aicore_client_id": "",
        "aicore_client_secret": "",
        "aicore_auth_url": "",
        "aicore_base_url": "",
        "aicore_model_media": "",
    }
    values.update(overrides)
    return AgentSettings(**values)


def test_factory_maps_modes() -> None:
    cache = MemoryCache()
    agent = _agent()
    assert build_media_client(cache, integration=IntegrationSettings(adverse_media_mode="off")) is None
    stub = build_media_client(cache, integration=IntegrationSettings(adverse_media_mode="stub"))
    assert isinstance(stub, StubMediaClient)

    live = IntegrationSettings(adverse_media_mode="live")
    with pytest.raises(MissingModelError):
        build_media_client(cache, integration=live, settings=agent)
    with pytest.raises(ModelConfigurationError):
        build_media_client(cache, integration=live, settings=_agent(aicore_model_media="sonar"))
    configured = _agent(
        aicore_model_media="sonar",
        aicore_client_id="id",
        aicore_client_secret="secret",
        aicore_auth_url="https://auth.example/oauth/token",
        aicore_base_url="https://ai.example",
    )
    assert isinstance(build_media_client(cache, integration=live, settings=configured), AdverseMediaClient)
