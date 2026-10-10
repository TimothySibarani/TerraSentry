from __future__ import annotations

import httpx
import respx
from a2a_helpers import BATCH, VirtualClock, run_payload, settings
from terrasentry_a2a.client import TerraSentryClient
from terrasentry_a2a.skills import Skills

CHILD = f"{BATCH}:REC-001"
SCREENED = run_payload(
    CHILD,
    record_id="REC-001",
    verdict="high_risk",
    score=72,
    assessment={
        "assessment": {
            "findings": [
                {
                    "code": "protected_area",
                    "level": "flag",
                    "points": 60,
                    "detail": "Overlaps Tanjung Puting.",
                },
                {"code": "fire", "level": "clear", "points": 0, "detail": "No fires."},
            ]
        }
    },
)


def _mock_screening(api: respx.MockRouter, *, batch_state: str = "complete") -> None:
    api.post("/batch-runs").mock(
        return_value=httpx.Response(202, json={"run_id": BATCH, "state": "queued", "record_count": 1})
    )
    api.get(f"/batch-runs/{BATCH}").mock(
        return_value=httpx.Response(200, json={"run_id": BATCH, "state": batch_state, "record_count": 1})
    )
    api.get(f"/runs/{CHILD}").mock(return_value=httpx.Response(200, json=SCREENED))


async def test_screen_by_name_returns_verdict_findings_and_an_encoded_link(
    api: respx.MockRouter, skills: Skills
) -> None:
    _mock_screening(api)

    reply = await skills.handle("screen PT Sumber Sejahtera Sriwijaya")

    assert "Verdict: **High risk**, score 72." in reply
    assert "- Overlaps Tanjung Puting." in reply and "No fires" not in reply
    assert "(https://cockpit.test/runs/batch-aaaaaa111111%3AREC-001)" in reply
    sent = api.calls[1].request
    assert sent.url.path == "/batch-runs"
    assert b'"record_ids":["REC-001"]' in sent.content.replace(b" ", b"")
    assert b'"mode":"screening"' in sent.content.replace(b" ", b"")


async def test_screen_that_outlasts_the_reply_budget_answers_with_a_link(
    api: respx.MockRouter, skills: Skills, clock: VirtualClock
) -> None:
    _mock_screening(api, batch_state="running")

    reply = await skills.handle("screen REC-001")

    assert "Still screening" in reply
    assert "runs/batch-aaaaaa111111%3AREC-001" in reply
    assert clock.now >= 5.0


async def test_ambiguous_name_asks_which_supplier_and_starts_nothing(
    api: respx.MockRouter, skills: Skills
) -> None:
    reply = await skills.handle("screen Kencana Hijau")

    assert "Which supplier did you mean?" in reply
    assert "`SUP-003`" in reply and "`SUP-004`" in reply
    assert not any(call.request.method == "POST" for call in api.calls)


async def test_unknown_supplier_is_explained(skills: Skills) -> None:
    reply = await skills.handle("screen Totally Different Corp")
    assert "couldn't find a supplier" in reply


async def test_investigate_starts_a_run_and_replies_at_once(api: respx.MockRouter, skills: Skills) -> None:
    api.post("/runs").mock(
        return_value=httpx.Response(202, json=run_payload("run-1a2b3c4d5e6f", state="queued", model="sap"))
    )

    reply = await skills.handle("investigate SUP-001")

    assert "Started an AI-agent investigation" in reply
    assert "status run-1a2b3c4d5e6f" in reply
    assert b'"record_id":"REC-001"' in api.calls.last.request.content.replace(b" ", b"")


async def test_agent_runs_are_rate_limited(api: respx.MockRouter, clock: VirtualClock) -> None:
    api.post("/runs").mock(
        return_value=httpx.Response(202, json=run_payload("run-1a2b3c4d5e6f", state="queued"))
    )
    limited = Skills(
        TerraSentryClient("http://api.test"),
        settings(a2a_max_agent_runs_per_hour=1),
        sleep=clock.sleep,
        clock=clock,
    )

    assert "Started" in await limited.handle("investigate SUP-001")
    assert "limited per hour" in await limited.handle("investigate SUP-002")


async def test_status_of_a_run_and_a_batch(api: respx.MockRouter, skills: Skills) -> None:
    api.get("/runs/run-1a2b3c4d5e6f").mock(
        return_value=httpx.Response(
            200, json=run_payload("run-1a2b3c4d5e6f", state="awaiting_review", verdict="ambiguous")
        )
    )
    api.get(f"/batch-runs/{BATCH}").mock(
        return_value=httpx.Response(
            200,
            json={
                "run_id": BATCH,
                "state": "running",
                "record_count": 10,
                "states": {"complete": 4, "awaiting_review": 1},
                "verdict_breakdown": {"compliant": 3, "high_risk": 2, "ambiguous": 0},
            },
        )
    )

    run_reply = await skills.handle("status run-1a2b3c4d5e6f")
    batch_reply = await skills.handle(f"status {BATCH}")

    assert "awaiting a reviewer's decision" in run_reply and "Ambiguous, needs review" in run_reply
    assert "5 of 10 records done" in batch_reply
    assert "So far: 3 compliant, 2 high risk." in batch_reply
    assert "https://cockpit.test/batch/batch-aaaaaa111111" in batch_reply


async def test_api_failures_become_friendly_replies(api: respx.MockRouter, skills: Skills) -> None:
    api.post("/batch-runs").mock(side_effect=httpx.ConnectError("boom"))
    assert "unreachable" in await skills.handle("screen REC-001")

    api.post("/batch-runs").mock(return_value=httpx.Response(404, json={"detail": "x"}))
    assert "no record of that" in await skills.handle("screen REC-999")

    api.post("/batch-runs").mock(return_value=httpx.Response(403, json={"detail": "x"}))
    assert "rejected the proxy's credentials" in await skills.handle("screen REC-001")


async def test_unrecognised_text_returns_help(skills: Skills) -> None:
    assert "Screen a supplier" in await skills.handle("help")
