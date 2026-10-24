"""The two consequential tools only act when a person confirms through the client."""

from __future__ import annotations

from typing import Any

import pytest
from mcp.shared.exceptions import MCPError
from mcp_helpers import ok, run_payload


def _text(result: Any) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


def _held(run_id: str = "run-2", verdict: str = "high_risk", erp_mode: str = "auto") -> dict[str, Any]:
    return run_payload(
        run_id,
        state="awaiting_review",
        verdict=verdict,
        erp_mode=erp_mode,
        assessment=None,
        dds={"released": False},
    )


async def test_decision_asks_the_user_and_names_the_sap_effect(api, connect) -> None:
    api.get("/runs/run-2").mock(return_value=ok(_held()))
    decide = api.post("/runs/run-2/decision").mock(return_value=ok(run_payload("run-2")))

    async with connect(answer="yes") as client:
        result = await client.call_tool(
            "record_review_decision",
            {"run_id": "run-2", "decision": "override", "note": "confirmed on the register"},
        )

    assert result.structured_content["recorded"] is True
    assert decide.called
    prompt = client.prompts[0]
    assert "Block supplier SUP-U-1" in prompt and "high_risk" in prompt
    assert "vendor is set to blocked immediately" in prompt


async def test_declining_records_nothing(api, connect) -> None:
    api.get("/runs/run-2").mock(return_value=ok(_held()))
    decide = api.post("/runs/run-2/decision").mock(return_value=ok(run_payload("run-2")))

    async with connect(answer="no") as client:
        result = await client.call_tool("record_review_decision", {"run_id": "run-2", "decision": "override"})

    assert result.structured_content == {
        "recorded": False,
        "reason": "The user did not confirm the decision.",
    }
    assert not decide.called


async def test_a_client_that_cannot_ask_is_refused_and_nothing_happens(api, connect) -> None:
    api.get("/runs/run-2").mock(return_value=ok(_held()))
    decide = api.post("/runs/run-2/decision").mock(return_value=ok(run_payload("run-2")))

    async with connect(answer=None) as client:
        with pytest.raises(MCPError, match="elicitation capability"):
            await client.call_tool("record_review_decision", {"run_id": "run-2", "decision": "override"})

    assert not decide.called


async def test_the_same_refusal_protects_the_sap_change(api, connect) -> None:
    api.get("/runs/run-3").mock(
        return_value=ok(run_payload("run-3", erp_mode="confirm", erp_pending="blocked"))
    )
    apply = api.post("/runs/run-3/erp-action").mock(return_value=ok({"status": "blocked"}))

    async with connect(answer=None) as client:
        with pytest.raises(MCPError, match="elicitation capability"):
            await client.call_tool("confirm_erp_action", {"run_id": "run-3"})

    assert not apply.called


async def test_approving_a_high_risk_supplier_needs_a_note_before_the_user_is_even_asked(
    api, connect
) -> None:
    api.get("/runs/run-2").mock(return_value=ok(_held()))
    decide = api.post("/runs/run-2/decision").mock(return_value=ok(run_payload("run-2")))

    async with connect(answer="yes") as client:
        result = await client.call_tool("record_review_decision", {"run_id": "run-2", "decision": "approve"})

    assert result.is_error and "note" in _text(result)
    assert client.prompts == [] and not decide.called


async def test_only_held_runs_can_be_decided(api, connect) -> None:
    api.get("/runs/run-1").mock(return_value=ok(run_payload("run-1")))
    async with connect(answer="yes") as client:
        result = await client.call_tool("record_review_decision", {"run_id": "run-1", "decision": "override"})
    assert result.is_error and "only runs awaiting review" in _text(result)


async def test_confirm_mode_waits_for_the_users_go_ahead_before_touching_sap(api, connect) -> None:
    api.get("/runs/run-3").mock(
        return_value=ok(run_payload("run-3", erp_mode="confirm", erp_pending="blocked", verdict="high_risk"))
    )
    apply = api.post("/runs/run-3/erp-action").mock(return_value=ok({"status": "blocked"}))

    async with connect(answer="yes") as client:
        result = await client.call_tool("confirm_erp_action", {"run_id": "run-3"})

    assert result.structured_content["applied"] is True and apply.called
    assert "block vendor SUP-U-1" in client.prompts[0]


async def test_declining_leaves_sap_unchanged(api, connect) -> None:
    api.get("/runs/run-3").mock(
        return_value=ok(run_payload("run-3", erp_mode="confirm", erp_pending="approved"))
    )
    apply = api.post("/runs/run-3/erp-action").mock(return_value=ok({"status": "approved"}))

    async with connect(answer="no") as client:
        result = await client.call_tool("confirm_erp_action", {"run_id": "run-3"})

    assert result.structured_content["applied"] is False and not apply.called


async def test_nothing_pending_is_a_clear_error(api, connect) -> None:
    api.get("/runs/run-1").mock(return_value=ok(run_payload("run-1")))
    async with connect(answer="yes") as client:
        result = await client.call_tool("confirm_erp_action", {"run_id": "run-1"})
    assert result.is_error and "no SAP change waiting" in _text(result)
