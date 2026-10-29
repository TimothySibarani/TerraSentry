"""Exercise Alembic's actual SQLite schema, populated upgrades and application startup."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import api_helpers
from sqlalchemy import MetaData, create_engine, inspect
from terrasentry_api.config import Settings
from terrasentry_api.rehearsal import run_recorded_batch
from terrasentry_api.services import build_services
from terrasentry_api.store import RunStore
from terrasentry_integrations.settings import IntegrationSettings

ROOT = Path(__file__).resolve().parents[3]


def migrate(path: Path, *arguments: str, success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini", *arguments],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{path}"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, result.stdout + result.stderr
    return result


def test_sqlite_migration_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "audit.db"
    for arguments in [
        ("upgrade", "head"),
        ("upgrade", "head"),
        ("check",),
        ("downgrade", "base"),
        ("upgrade", "head"),
        ("check",),
    ]:
        migrate(path, *arguments)
    engine = create_engine(f"sqlite:///{path}")
    try:
        assert set(inspect(engine).get_table_names()) == {
            "alembic_version",
            "suppliers",
            "parcels",
            "records",
            "operator_settings",
            "runs",
            "run_steps",
            "evidence",
            "verdicts",
            "dds_documents",
            "sap_actions",
        }
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    finally:
        engine.dispose()


def test_populated_historical_upgrade_keeps_audit_rows(tmp_path: Path) -> None:
    path = tmp_path / "audit.db"
    migrate(path, "upgrade", "fa63e54f2542")
    engine = create_engine(f"sqlite:///{path}")
    metadata = MetaData()
    metadata.reflect(engine)
    now = datetime(2026, 10, 25, 7, 30, tzinfo=UTC)
    record = api_helpers.make_record(1)
    try:
        with engine.begin() as connection:
            supplier = record.legality.model_dump()
            connection.execute(
                metadata.tables["suppliers"]
                .insert()
                .values(
                    **{key: value for key, value in supplier.items() if key in metadata.tables["suppliers"].c}
                )
            )
            parcel = record.polygon.model_dump()
            connection.execute(
                metadata.tables["parcels"]
                .insert()
                .values(
                    polygon_id=parcel.pop("id"),
                    supplier_id=record.supplier_id,
                    **{key: value for key, value in parcel.items() if key in metadata.tables["parcels"].c},
                )
            )
            connection.execute(
                metadata.tables["runs"]
                .insert()
                .values(
                    id="legacy",
                    kind="scenario",
                    record_id=record.record_id,
                    supplier_id=record.supplier_id,
                    polygon_id=record.polygon.id,
                    state="complete",
                    model="scripted",
                    summary="preserved",
                    disclosures=[],
                    metrics={"legacy": True},
                    created_at=now,
                )
            )
            connection.execute(
                metadata.tables["run_steps"]
                .insert()
                .values(
                    run_id="legacy",
                    step_id="STEP-001",
                    seq=1,
                    kind="tool",
                    name="legacy",
                    detail="",
                    at=now,
                    payload={"original": [1, 2]},
                )
            )
            connection.execute(
                metadata.tables["evidence"]
                .insert()
                .values(
                    run_id="legacy",
                    evidence_id="EV-legacy",
                    schema_version=1,
                    claim="legacy",
                    value={"ha": 1},
                    source="gfw",
                    artifact={},
                    cached=True,
                    synthetic=False,
                )
            )
            connection.execute(
                metadata.tables["verdicts"]
                .insert()
                .values(
                    run_id="legacy",
                    record_id=record.record_id,
                    supplier_id=record.supplier_id,
                    polygon_id=record.polygon.id,
                    rubric_version="1",
                    score=0,
                    verdict="compliant",
                    risk_level="negligible",
                    fingerprint="a" * 64,
                    findings=[],
                    citations={},
                    disclosures=[],
                    data_gaps=[],
                    expected_archetype="compliant",
                    pending=False,
                    created_at=now,
                )
            )
            connection.execute(
                metadata.tables["dds_documents"]
                .insert()
                .values(
                    run_id="legacy",
                    document={"legacy": [1, 2]},
                    xml="<legacy/>",
                    released=True,
                    created_at=now,
                )
            )
            connection.execute(
                metadata.tables["sap_actions"]
                .insert()
                .values(
                    run_id="legacy",
                    supplier_id=record.supplier_id,
                    vendor_id=record.supplier_id,
                    mode="stub",
                    status="approved",
                    purchasing_block=False,
                    real=False,
                    performed_at=now,
                )
            )
        migrate(path, "upgrade", "d915f2b473a8")
        metadata = MetaData()
        metadata.reflect(engine)
        with engine.begin() as connection:
            connection.execute(
                metadata.tables["records"]
                .insert()
                .values(
                    record_id="REC-U-legacy",
                    supplier_id=record.supplier_id,
                    polygon_id=record.polygon.id,
                    source="submitted",
                    payload=record.model_dump(mode="json"),
                    geometry=record.polygon.geometry,
                    created_at=now,
                )
            )
            connection.execute(
                metadata.tables["operator_settings"]
                .insert()
                .values(
                    id=1,
                    profile=api_helpers.make_operator().model_dump(mode="json"),
                    updated_at=now,
                )
            )
        migrate(path, "upgrade", "head")
        migrate(path, "check")
        with engine.connect() as connection:
            for table in metadata.tables.values():
                if table.name != "alembic_version":
                    assert len(connection.execute(table.select()).all()) == 1, table.name
            assert connection.exec_driver_sql("SELECT country FROM parcels").scalar() == "ID"
            assert connection.exec_driver_sql("SELECT erp_mode FROM runs").scalar() == "auto"
            assert connection.execute(metadata.tables["dds_documents"].select()).one().document == {
                "legacy": [1, 2]
            }
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    finally:
        engine.dispose()


def test_migrations_reject_existing_foreign_key_violations(tmp_path: Path) -> None:
    path = tmp_path / "audit.db"
    migrate(path, "upgrade", "head")
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO run_steps (run_id, step_id, seq, kind, name, detail, at, payload) "
                "VALUES ('missing', 'STEP-001', 1, 'tool', 'bad', '', '2026-10-25', '{}')"
            )
        result = migrate(path, "upgrade", "head", success=False)
        assert "foreign key violations" in result.stderr
    finally:
        engine.dispose()


def test_real_services_boot_from_migrations_and_preserve_sqlite_cache(
    tmp_path: Path, source_router: object
) -> None:
    path = tmp_path / "audit.db"
    migrate(path, "upgrade", "head")
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{path}",
        seed_data_dir=str(ROOT / "data/seed"),
        agent_model="scripted",
        rehearsal_as_of="2026-09-11",
    )
    integration = IntegrationSettings(
        cache_backend="sqlite",
        cache_sqlite_path=tmp_path / "cache.db",
        cache_offline=False,
        cache_fixtures_dir="",
        gfw_api_key="test-key",
        gfw_rate_limit_per_min=100_000,
        firms_map_key="TESTKEY",
        firms_rate_limit_per_10min=100_000,
        sap_mode="stub",
        adverse_media_mode="off",
    )

    async def run() -> None:
        async with build_services(settings, integration) as services:
            report = await run_recorded_batch(services=services, size=4, poll_seconds=0.01)
            assert report["summary"]["state"] == "complete"
            async with services.session_factory() as session:
                assert await RunStore(session).count_suppliers() == 50
        offline = integration.model_copy(update={"cache_offline": True})
        async with build_services(settings, offline) as services:
            async with services.session_factory() as session:
                assert await RunStore(session).get_run(report["batch_run_id"]) is not None
            replay = await run_recorded_batch(
                services=services, size=4, mode="agent", model="scripted", poll_seconds=0.01
            )
            assert replay["summary"]["state"] == "complete"
            assert services.cache.stats().offline_misses == 0
            assert services.cache.stats().hits > 0

    asyncio.run(run())
