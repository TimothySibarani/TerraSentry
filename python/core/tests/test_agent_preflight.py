"""SAP AI Core preflight: exercises the real Strands path and maps failures to fixes."""

from __future__ import annotations

from typing import Any

from terrasentry_core.agents import preflight
from terrasentry_core.agents.scripted import ScriptedModel, ScriptedTurn
from terrasentry_core.agents.settings import AgentSettings


def _settings(**overrides: Any) -> AgentSettings:
    values: dict[str, Any] = {
        "aicore_service_key": "",
        "aicore_client_id": "",
        "aicore_client_secret": "",
        "aicore_auth_url": "",
        "aicore_base_url": "",
        "aicore_model_orchestrator": "claude-id",
        "aicore_model_extraction": "gpt-id",
        "aicore_model_media": "",
    }
    values.update(overrides)
    return AgentSettings(**values)


def _failing_model(exc: Exception) -> ScriptedModel:
    def responder(_context: object) -> ScriptedTurn:
        raise exc

    return ScriptedModel(responder=responder)


def _structured_model() -> ScriptedModel:
    return ScriptedModel(
        turns=[ScriptedTurn(structured_output=preflight._StructuredProbe(status="ok", note="fine"))]
    )


async def test_check_role_succeeds_with_the_scripted_model() -> None:
    model = ScriptedModel(default_text="ok")

    check = await preflight.check_role("extraction", settings=_settings(), model=model)

    assert check.ok
    assert check.model_id == "gpt-id"
    assert "ok" in check.detail
    assert check.latency_ms is not None
    assert model.get_config()["max_tokens"] == preflight.PING_MAX_TOKENS


async def test_check_without_credentials_is_a_failed_check() -> None:
    check = await preflight.check_role("orchestrator", settings=_settings())

    assert not check.ok
    assert check.model_id == "claude-id"
    assert "AICORE_SERVICE_KEY" in check.detail


def test_litellm_failures_map_to_sap_fixes() -> None:
    from litellm.exceptions import AuthenticationError, NotFoundError, RateLimitError

    auth = AuthenticationError("bad secret", llm_provider="sap", model="m")
    missing = NotFoundError("no deployment", model="m", llm_provider="sap")
    limited = RateLimitError("slow down", llm_provider="sap", model="m")

    assert "keybroker" in preflight.friendly_error(auth)
    assert "AICORE_MODEL_" in preflight.friendly_error(missing)
    assert "rate limit" in preflight.friendly_error(limited)


async def test_structured_probe_passes_when_the_model_uses_the_output_tool() -> None:
    check = await preflight.check_structured_output(settings=_settings(), model=_structured_model())

    assert check.ok
    assert check.role == "structured"
    assert "tool route" in check.detail


async def test_structured_probe_fails_with_the_gpt_fallback_when_the_tool_is_ignored() -> None:
    plain_text_only = ScriptedModel(default_text="all good")

    check = await preflight.check_structured_output(settings=_settings(), model=plain_text_only)

    assert not check.ok
    assert "never used the structured-output tool" in check.detail
    assert "AICORE_MODEL_ORCHESTRATOR=gpt-5.4" in check.detail


async def test_run_checks_probes_structured_output_only_after_the_orchestrator_answers(
    monkeypatch: Any,
) -> None:
    probed: list[str] = []

    async def fake_role(role: str, *, settings: AgentSettings) -> preflight.RoleCheck:
        return preflight.RoleCheck(role=role, model_id=role, ok=role != "orchestrator", detail="x")

    async def fake_probe(*, settings: AgentSettings) -> preflight.RoleCheck:
        probed.append("structured")
        return preflight.RoleCheck(role="structured", model_id="m", ok=True, detail="x")

    monkeypatch.setattr(preflight, "check_role", fake_role)
    monkeypatch.setattr(preflight, "check_structured_output", fake_probe)

    checks = await preflight.run_checks(("orchestrator", "extraction"), settings=_settings())

    assert [c.role for c in checks] == ["orchestrator", "extraction"]
    assert probed == []


def test_main_reports_a_failure_without_credentials(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(preflight, "get_agent_settings", _settings)

    exit_code = preflight.main(["--role", "both"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "credentials    : MISSING" in captured.out
    assert "FAILED" in captured.out
    assert "docs/sap-hackathon-resources.md" in captured.err


def test_main_succeeds_offline(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(preflight, "get_agent_settings", lambda: _settings(aicore_service_key="{}"))
    monkeypatch.setattr(
        preflight, "build_aicore_model", lambda role, settings=None: ScriptedModel(default_text="ok")
    )

    async def structured_ok(**_: Any) -> preflight.RoleCheck:
        return preflight.RoleCheck(role="structured", model_id="m", ok=True, detail="fine")

    monkeypatch.setattr(preflight, "check_structured_output", structured_ok)

    exit_code = preflight.main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ok in" in captured.out
    assert "structured" in captured.out


async def test_check_media_is_skipped_without_a_media_model() -> None:
    assert await preflight.check_media(settings=_settings(aicore_service_key="{}")) is None


def _fake_media_client(monkeypatch: Any, *, working: set[str]) -> list[str]:
    from terrasentry_integrations.sources.media import AdverseMediaReport, MediaCitation, MediaFinding

    asked: list[str] = []

    class FakeClient:
        def __init__(self, *, model: str, **_: Any) -> None:
            self.model = model

        async def search(self, subject: str, country: str | None, **_: Any) -> AdverseMediaReport:
            asked.append(self.model)
            if self.model not in working:
                return AdverseMediaReport(subject=subject, status="unavailable", error="unknown model")
            finding = MediaFinding(claim="c", citations=[MediaCitation(url="https://a.example")])
            return AdverseMediaReport(
                subject=subject, status="success", findings=[finding], response_citations=2
            )

    monkeypatch.setattr(preflight, "AdverseMediaClient", FakeClient)
    return asked


async def test_check_media_reports_findings_and_citation_passthrough(monkeypatch: Any) -> None:
    asked = _fake_media_client(monkeypatch, working={"sonar"})
    settings = _settings(aicore_service_key="{}", aicore_model_media="sonar")

    check = await preflight.check_media(settings=settings)

    assert check is not None and check.ok
    assert "1 cited finding(s)" in check.detail and "provider citations passed through" in check.detail
    assert asked == ["sonar"]


async def test_check_media_names_the_working_sonar_when_the_configured_one_fails(
    monkeypatch: Any,
) -> None:
    asked = _fake_media_client(monkeypatch, working={"sonar-pro"})
    settings = _settings(aicore_service_key="{}", aicore_model_media="sonar")

    check = await preflight.check_media(settings=settings)

    assert check is not None and not check.ok
    assert "AICORE_MODEL_MEDIA=sonar-pro" in check.detail
    assert asked == ["sonar", "sonar-pro"]


async def test_check_media_does_not_guess_for_other_model_names(monkeypatch: Any) -> None:
    asked = _fake_media_client(monkeypatch, working=set())
    settings = _settings(aicore_service_key="{}", aicore_model_media="custom-search")

    check = await preflight.check_media(settings=settings)

    assert check is not None and not check.ok
    assert asked == ["custom-search"]
