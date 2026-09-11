"""M7 closed loop: verdict -> ERP action, HITL gating, stub contract, failures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import api_helpers
from fastapi.testclient import TestClient
from terrasentry_api.main import create_app
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_integrations.errors import IntegrationError
from terrasentry_integrations.sap import VendorStatus


def _create_run(client: TestClient, payload: dict[str, Any]) -> str:
    response = client.post("/runs", json=payload)
    assert response.status_code == 202, response.text
    return str(response.json()["run_id"])


class FailingSapGateway:
    """A gateway whose every write fails, to prove ERP outages do not fail runs."""

    async def get_vendor_status(self, vendor_id: str) -> VendorStatus:
        raise IntegrationError("sandbox unreachable")

    async def update_vendor_status(self, vendor_id: str, status: str) -> VendorStatus:
        raise IntegrationError("sandbox unreachable")

    async def set_purchasing_block(self, vendor_id: str, blocked: bool) -> VendorStatus:
        raise IntegrationError("sandbox unreachable")

    async def close(self) -> None:
        return None


def test_compliant_run_flips_the_vendor_to_approved(client: TestClient, source_router: object) -> None:
    run_id = _create_run(client, {"record_id": "REC-001"})
    detail = api_helpers.wait_for_state(client, run_id, {"complete"})

    action = detail["sap_action"]
    assert action is not None
    assert action["run_id"] == run_id
    assert action["supplier_id"] == "SUP-001"
    assert action["vendor_id"] == "SUP-001"
    assert action["status"] == "approved"
    assert action["purchasing_block"] is False
    assert action["mode"] == "stub"
    assert action["real"] is False
    assert action["error"] is None

    steps = [step for step in detail["steps"] if step["kind"] == "sap"]
    assert len(steps) == 1
    assert steps[0]["name"] == "sap_action"
    assert steps[0]["payload"]["status"] == "approved"
    assert any("schema-accurate" in disclosure for disclosure in detail["disclosures"])

    dds = client.get(f"/dds/{run_id}")
    assert dds.status_code == 200
    assert dds.json()["erpAction"]["status"] == "approved"
    assert dds.json()["erpAction"]["real"] is False

    supplier = client.get("/suppliers/SUP-001")
    assert supplier.status_code == 200
    sap = supplier.json()["sap"]
    assert sap["status"] == "approved"
    assert sap["purchasing_block"] is False
    assert sap["mode"] == "stub"
    assert sap["last_action"]["run_id"] == run_id


def test_high_risk_run_blocks_the_vendor(client: TestClient, source_router: object) -> None:
    run_id = _create_run(client, {"scenario": "high_risk_live"})
    detail = api_helpers.wait_for_state(client, run_id, {"complete"})

    action = detail["sap_action"]
    assert action is not None
    assert action["supplier_id"] == "SUP-002"
    assert action["status"] == "blocked"
    assert action["purchasing_block"] is True

    supplier = client.get("/suppliers/SUP-002")
    assert supplier.json()["sap"]["status"] == "blocked"
    assert supplier.json()["sap"]["purchasing_block"] is True

    dds = client.get(f"/dds/{run_id}")
    assert dds.json()["erpAction"]["status"] == "blocked"
    assert dds.json()["erpAction"]["purchasingBlock"] is True


def test_ambiguous_run_waits_for_the_human_before_touching_sap(
    client: TestClient, source_router: object
) -> None:
    run_id = _create_run(client, {"record_id": "REC-003"})
    detail = api_helpers.wait_for_state(client, run_id, {"awaiting_review"})

    assert detail["sap_action"] is None
    assert client.get("/suppliers/SUP-003").json()["sap"]["status"] == "approved"

    decision = client.post(
        f"/runs/{run_id}/decision",
        json={"decision": "approve", "reviewer": "alice", "note": "permit gap cleared"},
    )
    assert decision.status_code == 200, decision.text

    approved = client.get(f"/runs/{run_id}").json()
    assert approved["sap_action"]["status"] == "approved"
    assert approved["sap_action"]["real"] is False
    assert client.get("/suppliers/SUP-003").json()["sap"]["status"] == "approved"


def test_override_blocks_the_vendor(client: TestClient, source_router: object) -> None:
    run_id = _create_run(client, {"record_id": "REC-003"})
    api_helpers.wait_for_state(client, run_id, {"awaiting_review"})

    decision = client.post(
        f"/runs/{run_id}/decision",
        json={"decision": "override", "reviewer": "bob", "note": "unresolved conflict"},
    )
    assert decision.status_code == 200, decision.text

    detail = client.get(f"/runs/{run_id}").json()
    assert detail["sap_action"]["status"] == "blocked"
    assert detail["sap_action"]["purchasing_block"] is True
    assert client.get("/suppliers/SUP-003").json()["sap"]["status"] == "blocked"


def test_batch_records_erp_actions_and_counts(client: TestClient, source_router: object) -> None:
    response = client.post("/batch-runs", json={"size": 4})
    assert response.status_code == 202, response.text
    batch_id = str(response.json()["run_id"])
    api_helpers.wait_for_state(client, batch_id, {"complete"}, path="/batch-runs")

    summary = client.get(f"/batch-runs/{batch_id}").json()
    assert summary["sap_actions"] == {"approved": 2, "blocked": 1, "failed": 0}

    expected = {"REC-001": "approved", "REC-002": "blocked", "REC-004": "approved"}
    for record_id, status in expected.items():
        detail = client.get(f"/runs/{batch_id}:{record_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["sap_action"]["status"] == status
        assert len([step for step in detail.json()["steps"] if step["kind"] == "sap"]) == 1

    ambiguous = client.get(f"/runs/{batch_id}:REC-003")
    assert ambiguous.json()["state"] == "awaiting_review"
    assert ambiguous.json()["sap_action"] is None


def test_vendor_state_replays_across_an_api_restart(
    tmp_path: Path, datasets: SeedDatasets, source_router: object
) -> None:
    first = create_app(services_factory=api_helpers.test_services_factory(tmp_path, datasets))
    with TestClient(first) as client:
        run_id = _create_run(client, {"scenario": "high_risk_live"})
        api_helpers.wait_for_state(client, run_id, {"complete"})
        assert client.get("/suppliers/SUP-002").json()["sap"]["status"] == "blocked"

    # A new app over the same database replays the action log into the stub.
    restarted = create_app(services_factory=api_helpers.test_services_factory(tmp_path, datasets))
    with TestClient(restarted) as client:
        sap = client.get("/suppliers/SUP-002").json()["sap"]
        assert sap["status"] == "blocked"
        assert sap["purchasing_block"] is True
        assert sap["last_action"]["run_id"] == run_id


def test_erp_outage_is_recorded_but_does_not_fail_the_run(
    tmp_path: Path, datasets: SeedDatasets, source_router: object
) -> None:
    app = create_app(
        services_factory=api_helpers.test_services_factory(
            tmp_path, datasets, sap_gateway=FailingSapGateway()
        )
    )
    with TestClient(app) as client:
        run_id = _create_run(client, {"record_id": "REC-001"})
        detail = api_helpers.wait_for_state(client, run_id, {"complete"})

        assert detail["verdict"] == "compliant"
        assert detail["dds"]["released"] is True
        action = detail["sap_action"]
        assert action["status"] == "failed"
        assert "IntegrationError" in action["error"]
        assert any("ERP action failed" in disclosure for disclosure in detail["disclosures"])

        dds = client.get(f"/dds/{run_id}")
        assert dds.json()["erpAction"]["status"] == "failed"
        assert dds.json()["erpAction"]["error"]


def test_stub_odata_contract_is_api_hub_accurate(client: TestClient) -> None:
    supplier = client.get("/mock-sap/A_Supplier('SUP-001')")
    assert supplier.status_code == 200
    payload = supplier.json()
    assert payload["@odata.context"] == "$metadata#A_Supplier/$entity"
    assert payload["Supplier"] == "SUP-001"
    assert payload["PurchasingIsBlocked"] is False
    assert payload["PostingIsBlocked"] is False
    assert payload["PaymentIsBlockedForSupplier"] is False

    patched = client.request(
        "PATCH",
        "/mock-sap/A_Supplier('SUP-001')",
        json={"PurchasingIsBlocked": True},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["PurchasingIsBlocked"] is True
    assert patched.json()["PostingIsBlocked"] is True

    partner = client.get("/mock-sap/A_BusinessPartner('SUP-001')")
    assert partner.json()["BusinessPartner"] == "SUP-001"
    assert partner.json()["BusinessPartnerIsBlocked"] is True

    unblocked = client.patch(
        "/mock-sap/A_Supplier('SUP-001')",
        json={"PurchasingIsBlocked": False},
    )
    assert unblocked.status_code == 200
    assert unblocked.json()["PurchasingIsBlocked"] is False
    assert unblocked.json()["PostingIsBlocked"] is False
