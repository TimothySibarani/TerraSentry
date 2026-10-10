"""Operator configuration is validated, authenticated, persisted and snapshotted."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import api_helpers
import pytest
import respx
from fastapi.testclient import TestClient
from terrasentry_api.main import create_app
from terrasentry_core.tools.datasets import SeedDatasets


def profile(**overrides: Any) -> dict[str, Any]:
    value = api_helpers.make_operator().model_dump(
        exclude={"operator_id", "synthetic", "provenance", "disclosure"}
    )
    value.update(
        legal_name="Declared Importer",
        country="be",
        country_of_activity="be",
        border_cross_country="de",
        identifier_value="NL12345",
    )
    value.update(overrides)
    return value


def test_setting_survives_restart_and_running_batch_keeps_snapshot(
    tmp_path: Path, datasets: SeedDatasets, source_router: respx.MockRouter
) -> None:
    factory = api_helpers.test_services_factory(tmp_path, datasets)
    with TestClient(create_app(factory)) as client:
        fallback = client.get("/settings/operator").json()
        assert not fallback["configured"] and fallback["profile"]["synthetic"]
        saved = client.put("/settings/operator", json=profile())
        assert saved.status_code == 200, saved.text
        assert saved.json()["profile"]["country"] == "BE"
        assert saved.json()["profile"]["identifier_value"] == "NL12345"  # issuer may differ from address
        batch = client.post("/batch-runs", json={"size": 4}).json()
        assert client.put("/settings/operator", json=profile(legal_name="Later Importer")).status_code == 200
        api_helpers.wait_for_state(client, batch["run_id"], {"complete", "failed"}, path="/batch-runs")
        rows = client.get(f"/batch-runs/{batch['run_id']}/records").json()
        assert len(rows) == 4
        assert len({row["assessment_date"] for row in rows}) == 1
        for row in rows:
            assert row["operator_profile"]["legal_name"] == "Declared Importer"
            detail = client.get(f"/runs/{row['run_id']}").json()
            if detail["dds"]["released"]:
                dds = client.get(f"/dds/{row['run_id']}").json()
                assert dds["statement"]["representedOperator"]["operatorName"] == "Declared Importer"
    with TestClient(create_app(factory)) as client:
        saved = client.get("/settings/operator").json()
        assert saved["configured"] and saved["profile"]["legal_name"] == "Later Importer"


def test_pending_review_keeps_operator_and_date_after_restart(
    tmp_path: Path, datasets: SeedDatasets, source_router: respx.MockRouter
) -> None:
    factory = api_helpers.test_services_factory(tmp_path, datasets)
    with TestClient(create_app(factory)) as client:
        assert client.put("/settings/operator", json=profile()).status_code == 200
        run_id = client.post("/runs", json={"record_id": "REC-003"}).json()["run_id"]
        pending = api_helpers.wait_for_state(client, run_id, {"awaiting_review"})
        evidence = client.get(f"/runs/{run_id}/evidence").json()
        assert client.put("/settings/operator", json=profile(legal_name="Later Importer")).status_code == 200
    with TestClient(create_app(factory)) as client:
        decision = client.post(
            f"/runs/{run_id}/decision", json={"decision": "approve", "reviewer": "analyst"}
        )
        assert decision.status_code == 200, decision.text
        dds = client.get(f"/dds/{run_id}").json()
        assert dds["statement"]["representedOperator"]["operatorName"] == "Declared Importer"
        assert dds["assessment"]["assessmentDate"] == pending["assessment_date"]
        assert "Declared Importer" in client.get(f"/dds/{run_id}/xml").text
        assert client.get(f"/runs/{run_id}/evidence").json() == evidence


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("legal_name", "  "),
        ("country", "XX"),
        ("identifier_value", "ID12345"),
        ("identifier_value", "NL12-34"),
        ("email", "bad"),
    ],
)
def test_invalid_settings_map_to_fields(client: TestClient, field: str, value: str) -> None:
    response = client.put("/settings/operator", json=profile(**{field: value}))
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert not client.get("/settings/operator").json()["configured"]


def test_settings_write_requires_configured_token(tmp_path: Path, datasets: SeedDatasets) -> None:
    with TestClient(
        create_app(api_helpers.test_services_factory(tmp_path, datasets, api_token="test-write"))
    ) as client:
        assert client.get("/settings/operator").status_code == 200
        assert client.put("/settings/operator", json=profile()).status_code == 401
        assert (
            client.put(
                "/settings/operator", json=profile(), headers={"Authorization": "Bearer test-write"}
            ).status_code
            == 200
        )


def test_legacy_record_without_country_rejects_single_and_batch_before_queue(
    client: TestClient, datasets: SeedDatasets
) -> None:
    record = datasets.records[0].model_copy(deep=True)
    record.record_id = "REC-LEGACY-NO-COUNTRY"
    record.polygon.country = None
    datasets.register(record)
    single = client.post("/runs", json={"record_id": record.record_id})
    batch = client.post("/batch-runs", json={"record_ids": [datasets.records[1].record_id, record.record_id]})
    assert single.status_code == batch.status_code == 422
    assert single.json()["detail"][0]["loc"] == ["body", "plot", "country"]
    assert client.get("/runs").json() == []
