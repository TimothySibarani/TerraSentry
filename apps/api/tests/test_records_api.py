"""Intake API: submitted plots run end to end without seed data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import api_helpers
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from terrasentry_api.main import create_app
from terrasentry_core.tools.datasets import SeedDatasets

SQUARE: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[101.0, 0.5], [101.02, 0.5], [101.02, 0.52], [101.0, 0.52], [101.0, 0.5]]],
}


def body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "plot": {
            "country": "ID",
            "geometry": SQUARE,
            "label": "Blok A",
            "province": "Riau",
            "kabupaten": "Siak",
        },
        "supplier": {"legal_name": "PT Contoh Sawit", "certifications": ["ISPO"]},
        "legality": {"permit_type": "hgu", "permit_number": "12/HGU/BPN/2019", "concession_area_ha": 900},
        "consignment": {
            "commodity": "oil_palm",
            "description": "Crude palm oil",
            "net_weight_kg": 25000,
            "harvest_year": 2026,
        },
    }
    payload.update(overrides)
    return payload


def test_submitted_record_runs_to_a_released_dds(client: TestClient, source_router: respx.MockRouter) -> None:
    created = client.post("/records", json=body())
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["provenance"] == "supplier_declared"
    assert 480 < record["area_ha"] < 510
    assert record["latest_run"] is None

    run = client.post("/runs", json={"record_id": record["record_id"], "model": "scripted"})
    assert run.status_code == 202, run.text
    detail = api_helpers.wait_for_state(
        client, run.json()["run_id"], {"complete", "awaiting_review", "failed"}
    )
    assert detail["state"] == "complete", detail
    assert detail["verdict"] == "compliant"
    assert detail["assessment"]["expected_archetype"] is None
    assert any("Declared by the supplier" in text for text in detail["disclosures"])
    assert not any("Sumatra and Kalimantan" in text for text in detail["disclosures"])

    dds = client.get(f"/dds/{detail['run_id']}")
    assert dds.status_code == 200
    producer = dds.json()["statement"]["commodities"][0]["producers"][0]
    assert producer["name"] == "PT Contoh Sawit"

    listed = client.get(f"/records/{record['record_id']}").json()
    assert listed["latest_run"]["verdict"] == "compliant"


def test_point_plot_and_geometry_preview(client: TestClient) -> None:
    point = {"type": "Point", "coordinates": [101.0, 0.5]}
    preview = client.post("/records/validate-geometry", json={"geometry": point, "declared_area_ha": 3})
    assert preview.status_code == 200
    assert preview.json()["area_ha"] == 3
    rejected = client.post("/records/validate-geometry", json={"geometry": point, "declared_area_ha": 6})
    assert rejected.status_code == 422
    assert rejected.json()["detail"][0]["loc"] == ["body", "plot", "declared_area_ha"]


def test_invalid_submission_maps_to_a_field(client: TestClient) -> None:
    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
    response = client.post("/records", json=body(plot={"country": "ID", "geometry": bowtie, "label": "x"}))
    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["body", "plot", "geometry"]
    assert "Self-intersection" in detail["msg"]
    assert client.get("/records").json() == []


@pytest.mark.parametrize(
    "geometry,area",
    [
        (
            {
                "type": "Polygon",
                "coordinates": [
                    [[179.999, 0], [-179.999, 0], [-179.999, 0.01], [179.999, 0.01], [179.999, 0]]
                ],
            },
            None,
        ),
        ({"type": "Point", "coordinates": [179.9999, 0]}, 3),
        ({"type": "Point", "coordinates": [0, 90]}, 3),
    ],
)
def test_unsupported_query_geography_is_422_before_registration(
    client: TestClient, source_router: respx.MockRouter, geometry: dict[str, Any], area: float | None
) -> None:
    plot = {"country": "ID", "geometry": geometry, "label": "Review", "declared_area_ha": area}
    for response in (
        client.post("/records/validate-geometry", json={"geometry": geometry, "declared_area_ha": area}),
        client.post("/records", json=body(plot=plot)),
    ):
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "plot", "geometry"]
    assert client.get("/records").json() == []
    assert len(source_router.calls) == 0


def test_import_creates_valid_rows_and_reports_bad_ones(client: TestClient) -> None:
    csv_text = (
        "country,label,wkt,legal_name,commodity,description,net_weight_kg,harvest_year,permit_type,permit_number\n"
        'ID,"Blok 1","POLYGON((101 0.5, 101.01 0.5, 101.01 0.51, 101 0.51, 101 0.5))",'
        "PT Satu,oil_palm,CPO,1000,2026,hgu,1/HGU\n"
        'ID,"Blok 2","POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))",PT Dua,oil_palm,CPO,1000,2026,none,\n'
        'ID,"Blok 3",,PT Tiga,cocoa,Cocoa beans,500,2026,none,\n'
    )
    response = client.post("/records/import", files={"file": ("portfolio.csv", csv_text, "text/csv")})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total_rows"] == 3
    assert [item["label"] for item in result["created"]] == ["Blok 1"]
    assert [(error["row"], error["field"]) for error in result["errors"]] == [
        (2, "plot.geometry"),
        (3, "plot.geometry"),
    ]
    assert len(client.get("/records").json()) == 1


def test_list_can_filter_by_source(client: TestClient) -> None:
    client.post("/records", json=body())
    csv_text = (
        "country,label,wkt,legal_name,commodity,description,net_weight_kg,harvest_year\n"
        'ID,"Blok 9","POLYGON((101 0.5, 101.01 0.5, 101.01 0.51, 101 0.51, 101 0.5))",'
        "PT Sembilan,oil_palm,CPO,1000,2026\n"
    )
    client.post("/records/import", files={"file": ("portfolio.csv", csv_text, "text/csv")})

    submitted = client.get("/records?source=submitted").json()
    imported = client.get("/records?source=import").json()
    assert [row["source"] for row in submitted] == ["submitted"]
    assert [row["source"] for row in imported] == ["import"]
    assert len(client.get("/records").json()) == 2
    assert client.get("/records?source=seed").status_code == 422


def test_import_rejects_oversized_and_overlong_files(client: TestClient) -> None:
    oversized = b"label,wkt\n" + b"x" * (5 * 1024 * 1024 + 16)
    too_big = client.post("/records/import", files={"file": ("big.csv", oversized, "text/csv")})
    assert too_big.status_code == 413

    header = "country,label,wkt,legal_name,commodity,description,net_weight_kg,harvest_year\n"
    row = (
        'ID,"Blok","POLYGON((101 0.5, 101.01 0.5, 101.01 0.51, 101 0.51, 101 0.5))",'
        "PT X,oil_palm,CPO,1,2026\n"
    )
    too_many = client.post(
        "/records/import",
        files={"file": ("many.csv", header + row * 501, "text/csv")},
    )
    assert too_many.status_code == 422
    assert client.get("/records").json() == []


def test_import_handles_a_bom_and_semicolon_delimiter(client: TestClient) -> None:
    csv_text = (
        '\ufeff"country";"label";"wkt";"legal_name";"commodity";"description";"net_weight_kg";"harvest_year"\n'
        '"ID";"Blok 9";"POLYGON((101 0.5, 101.01 0.5, 101.01 0.51, 101 0.51, 101 0.5))";'
        '"PT Sembilan";"oil_palm";"CPO";"500";"2026"\n'
    )
    response = client.post(
        "/records/import",
        files={"file": ("portfolio.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["errors"] == []
    assert result["created"][0]["label"] == "Blok 9"


def test_malformed_geojson_rows_preserve_row_numbers(client: TestClient) -> None:
    valid = {
        "type": "Feature",
        "geometry": SQUARE,
        "properties": {
            "country": "ID",
            "label": "Good",
            "legal_name": "PT Good",
            "commodity": "oil_palm",
            "description": "CPO",
            "net_weight_kg": 10,
            "harvest_year": 2026,
        },
    }
    features = [
        123,
        {**valid, "properties": "bad"},
        {**valid, "properties": {**valid["properties"], "commodity": 123}},
        valid,
    ]
    response = client.post(
        "/records/import",
        files={
            "file": (
                "plots.geojson",
                json.dumps({"type": "FeatureCollection", "features": features}),
                "application/geo+json",
            )
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total_rows"] == 4
    assert [error["row"] for error in result["errors"]] == [1, 2, 3]
    assert len(result["created"]) == 1


@pytest.mark.parametrize("bulk", [False, True])
def test_commit_failure_does_not_publish_records(
    client: TestClient, datasets: SeedDatasets, monkeypatch: pytest.MonkeyPatch, bulk: bool
) -> None:
    async def fail_commit(self: AsyncSession) -> None:
        raise RuntimeError("injected commit failure")

    before = datasets.submitted_records()
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="injected commit"):
            if bulk:
                csv_text = (
                    "country,label,wkt,legal_name,commodity,description,net_weight_kg,harvest_year\n"
                    'ID,Blok,"POLYGON((101 0.5,101.01 0.5,101.01 0.51,101 0.51,101 0.5))",'
                    "PT Good,oil_palm,CPO,10,2026\n"
                )
                client.post("/records/import", files={"file": ("plots.csv", csv_text, "text/csv")})
            else:
                client.post("/records", json=body())
    assert datasets.submitted_records() == before


def test_batch_over_submitted_record_ids(client: TestClient, source_router: respx.MockRouter) -> None:
    ids = [client.post("/records", json=body()).json()["record_id"] for _ in range(2)]
    batch = client.post("/batch-runs", json={"record_ids": ids})
    assert batch.status_code == 202, batch.text
    summary = api_helpers.wait_for_state(
        client, batch.json()["run_id"], {"complete", "failed"}, path="/batch-runs"
    )
    assert summary["state"] == "complete"
    assert summary["record_count"] == 2
    assert summary["verdict_breakdown"]["compliant"] == 2
    assert summary["expected_breakdown"] == {}
    assert client.post("/batch-runs", json={"record_ids": ["REC-U-NOPE"]}).status_code == 404


def test_submitted_records_survive_a_restart(tmp_path: Path, source_router: respx.MockRouter) -> None:
    datasets = api_helpers.build_datasets()
    factory = api_helpers.test_services_factory(tmp_path, datasets)
    with TestClient(create_app(services_factory=factory)) as first:
        record_id = first.post("/records", json=body()).json()["record_id"]
    fresh = api_helpers.build_datasets()
    with TestClient(
        create_app(services_factory=api_helpers.test_services_factory(tmp_path, fresh))
    ) as second:
        run = second.post("/runs", json={"record_id": record_id})
        assert run.status_code == 202, run.text
        detail = api_helpers.wait_for_state(second, run.json()["run_id"], {"complete", "failed"})
        assert detail["state"] == "complete"


def test_write_token_guards_writes_but_not_reads(tmp_path: Path) -> None:
    factory = api_helpers.test_services_factory(tmp_path, api_token="s3cret")
    with TestClient(create_app(services_factory=factory)) as client:
        assert client.get("/health").json()["auth_enabled"] is True
        assert client.get("/records").status_code == 200
        assert client.post("/records", json=body()).status_code == 401
        wrong = client.post("/records", json=body(), headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401
        ok = client.post("/records", json=body(), headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 201
