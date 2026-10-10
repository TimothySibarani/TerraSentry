from __future__ import annotations

import httpx
import respx
from a2a_helpers import BATCH, run_payload, settings
from fastapi.testclient import TestClient
from terrasentry_a2a.client import TerraSentryClient
from terrasentry_a2a.server import create_app


def _rpc(text: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": "m-1",
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }


def test_agent_card_lists_the_three_skills(api: respx.MockRouter) -> None:
    app = create_app(settings(), TerraSentryClient("http://api.test"))
    with TestClient(app) as client:
        card = client.get("/.well-known/agent-card.json").json()
        assert client.get("/health").json() == {"status": "ok"}
    assert card["url"] == "https://a2a.test"
    assert [skill["id"] for skill in card["skills"]] == ["screen", "investigate", "status"]
    assert card["capabilities"]["streaming"] is False


def test_message_send_returns_the_reply_as_a_completed_task_artifact(api: respx.MockRouter) -> None:
    child = f"{BATCH}:REC-001"
    api.post("/batch-runs").mock(
        return_value=httpx.Response(202, json={"run_id": BATCH, "state": "complete", "record_count": 1})
    )
    api.get(f"/runs/{child}").mock(
        return_value=httpx.Response(200, json=run_payload(child, verdict="compliant", score=5))
    )
    app = create_app(settings(), TerraSentryClient("http://api.test"))

    with TestClient(app) as client:
        body = client.post("/", json=_rpc("screen REC-001")).json()

    task = body["result"]
    assert task["status"]["state"] == "completed"
    text = task["artifacts"][0]["parts"][0]["text"]
    assert "Verdict: **Compliant**, score 5." in text


def test_empty_message_gets_guidance_instead_of_an_error(api: respx.MockRouter) -> None:
    app = create_app(settings(), TerraSentryClient("http://api.test"))
    with TestClient(app) as client:
        body = client.post("/", json=_rpc("   ")).json()
    assert "Tell me which supplier" in body["result"]["artifacts"][0]["parts"][0]["text"]
