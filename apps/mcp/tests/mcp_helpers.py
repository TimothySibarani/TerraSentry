"""Shared test helpers for the MCP server tests (unique name: the root pytest run has several conftests)."""

from __future__ import annotations

from typing import Any

import httpx

API = "http://api.test"


class VirtualClock:
    """Time that only moves when the server sleeps, so polling never really waits."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def run_payload(run_id: str = "run-1", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "kind": "scenario",
        "state": "complete",
        "record_id": "REC-U-1",
        "supplier_id": "SUP-U-1",
        "model": "scripted",
        "erp_mode": "off",
        "verdict": "compliant",
        "score": 0,
        "summary": "Evidence gathered.",
        "error": None,
        "assessment": {"assessment": {"rubric_version": "1.2.0", "findings": [], "data_gaps": []}},
        "pending_assessment": None,
        "review": None,
        "sap_action": None,
        "erp_pending": None,
        "dds": {"released": True},
    }
    payload.update(overrides)
    return payload


def ok(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)
