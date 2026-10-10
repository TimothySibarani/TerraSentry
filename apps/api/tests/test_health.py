from pathlib import Path

import api_helpers
from fastapi.testclient import TestClient
from terrasentry_api.main import create_app


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "offline": False,
        "fixtures_loaded": 0,
        "sap_mode": "stub",
        "sap_real": False,
        # The test factory builds services without Bedrock ids.
        "bedrock_configured": False,
        "default_model": "scripted",
        "gfw_configured": True,
        "firms_configured": True,
        "auth_enabled": False,
    }


def test_health_reports_bedrock_configured_when_both_models_are_set(tmp_path: Path) -> None:
    factory = api_helpers.test_services_factory(tmp_path, bedrock_configured=True)
    with TestClient(create_app(services_factory=factory)) as client:
        body = client.get("/health").json()
    assert body["bedrock_configured"] is True
