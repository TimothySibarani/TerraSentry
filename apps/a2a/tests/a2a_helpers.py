"""Shared constants and builders for the A2A tests (uniquely named; other packages have conftests)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from terrasentry_a2a.settings import A2ASettings

API = "http://api.test"
BATCH = "batch-aaaaaa111111"

SUPPLIERS = [
    {
        "supplier_id": "SUP-001",
        "legal_name": "PT Sumber Sejahtera Sriwijaya",
        "trading_name": "Sumber Sejahtera",
    },
    {"supplier_id": "SUP-002", "legal_name": "PT Agro Sejahtera Borneo", "trading_name": "Agro Borneo"},
    {"supplier_id": "SUP-003", "legal_name": "PT Kencana Hijau", "trading_name": "Kencana Hijau"},
    {"supplier_id": "SUP-004", "legal_name": "PT Kencana Hijau Lestari", "trading_name": "Kencana Hijau"},
]


@dataclass
class VirtualClock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def settings(**overrides: Any) -> A2ASettings:
    values: dict[str, Any] = {
        "terrasentry_api_url": API,
        "cockpit_base_url": "https://cockpit.test",
        "a2a_reply_budget_seconds": 5.0,
        "a2a_poll_interval_seconds": 1.0,
        "a2a_public_url": "https://a2a.test",
    }
    values.update(overrides)
    return A2ASettings(**values)


def run_payload(run_id: str, *, state: str = "complete", **extra: object) -> dict[str, object]:
    return {"run_id": run_id, "kind": "screening", "state": state, "model": "deterministic", **extra}
