from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "offline": False,
        "fixtures_loaded": 0,
        "sap_mode": "stub",
        "sap_real": False,
    }
