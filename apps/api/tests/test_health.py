from pathlib import Path

import api_helpers
from fastapi.testclient import TestClient
from terrasentry_api.main import create_app
from terrasentry_integrations.sources.media import StubMediaClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "offline": False,
        "fixtures_loaded": 0,
        "sap_mode": "stub",
        "sap_real": False,
        # The test factory builds services without AI Core credentials.
        "aicore_configured": False,
        "adverse_media_mode": "off",
        "default_model": "scripted",
        "gfw_configured": True,
        "firms_configured": True,
        "auth_enabled": False,
    }


def test_health_reports_aicore_configured_when_credentials_and_models_are_set(tmp_path: Path) -> None:
    factory = api_helpers.test_services_factory(tmp_path, aicore_configured=True)
    with TestClient(create_app(services_factory=factory)) as client:
        body = client.get("/health").json()
    assert body["aicore_configured"] is True
    assert "bedrock_configured" not in body


def test_health_reports_the_adverse_media_mode(tmp_path: Path) -> None:
    factory = api_helpers.test_services_factory(tmp_path, media=StubMediaClient())
    with TestClient(create_app(services_factory=factory)) as client:
        assert client.get("/health").json()["adverse_media_mode"] == "stub"
