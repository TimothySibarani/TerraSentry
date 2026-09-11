"""Supplier reads over the seeded dataset plus the mock SAP vendor endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_suppliers_are_seeded_and_labelled_synthetic(client: TestClient) -> None:
    response = client.get("/suppliers")
    assert response.status_code == 200
    suppliers = response.json()
    assert len(suppliers) == 4
    first = suppliers[0]
    assert first["synthetic"] is True
    assert first["disclosure"]


def test_supplier_detail_includes_parcels(client: TestClient) -> None:
    response = client.get("/suppliers/SUP-001")
    assert response.status_code == 200
    detail = response.json()
    assert detail["supplier_id"] == "SUP-001"
    assert len(detail["parcels"]) == 1
    assert detail["parcels"][0]["polygon_id"] == "POLY-001"
    assert client.get("/suppliers/NOPE").status_code == 404


def test_mock_sap_vendor_status_flip(client: TestClient) -> None:
    initial = client.get("/mock-sap/vendors/SUP-001")
    assert initial.status_code == 200
    assert initial.json() == {
        "vendor_id": "SUP-001",
        "status": "approved",
        "purchasing_block": False,
    }

    updated = client.put("/mock-sap/vendors/SUP-001/status", json={"status": "blocked"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "blocked"

    blocked = client.put("/mock-sap/vendors/SUP-001/purchasing-block", json={"blocked": True})
    assert blocked.status_code == 200
    assert blocked.json()["purchasing_block"] is True

    unknown = client.get("/mock-sap/vendors/SUP-404")
    assert unknown.status_code == 200
    assert unknown.json()["status"] == "approved"
