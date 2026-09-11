"""CLI: scripted end-to-end runs, artifacts, exit codes, and HITL decisions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import agent_helpers
import httpx
import respx
from terrasentry_core.agents.cli import main
from terrasentry_core.seed.schemas import BatchDataset, OperatorDataset
from terrasentry_integrations.settings import get_integration_settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def _use_offline_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("GFW_API_KEY", "test-key")
    monkeypatch.setenv("FIRMS_MAP_KEY", "TESTKEY")
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    get_integration_settings.cache_clear()


def _run_file(directory: Path) -> Path:
    files = [path for path in directory.glob("agent-*.json") if len(path.suffixes) == 1]
    assert len(files) == 1, files
    return files[0]


def test_cli_scripted_run_completes_and_writes_artifacts(
    source_router, tmp_path: Path, monkeypatch
) -> None:
    _use_offline_env(monkeypatch)
    exit_code = main(
        [
            "--record",
            "REC-001",
            "--batch",
            str(REPO_ROOT / "data/seed/batch_50.json"),
            "--operator",
            str(REPO_ROOT / "data/seed/operator.json"),
            "--out",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    run_file = _run_file(tmp_path)
    payload = json.loads(run_file.read_text(encoding="utf-8"))
    assert payload["state"] == "complete"
    assert payload["assessment"]["assessment"]["verdict"] == "high_risk"
    assert payload["verification"]["accepted"] is True
    assert run_file.with_suffix(".dds.json").exists()
    assert run_file.with_suffix(".dds.xml").exists()
    assert run_file.with_suffix(".evidence.json").exists()


def test_cli_hitl_pauses_then_resumes_with_a_decision(
    factories: dict[str, Any], tmp_path: Path, monkeypatch
) -> None:
    _use_offline_env(monkeypatch)
    supplier = factories["supplier"](
        supplier_id="SUP-HITL",
        hgu_number=None,
        pbp_number=None,
        permit_status="active",
        sanctions=[],
    )
    record = factories["batch_record"](
        index=91,
        expected_archetype="ambiguous",
        expected_ambiguity="permit_gap",
        supplier=supplier,
    )
    batch_path = tmp_path / "batch.json"
    operator_path = tmp_path / "operator.json"
    batch_path.write_text(
        BatchDataset(
            rng_seed=1,
            distribution={"compliant": 0, "high_risk": 0, "ambiguous": 1},
            records=[record],
        ).model_dump_json(),
        encoding="utf-8",
    )
    operator_path.write_text(
        OperatorDataset(rng_seed=1, operator=agent_helpers.datasets().operator).model_dump_json(),
        encoding="utf-8",
    )

    with respx.mock(assert_all_called=False) as router:
        router.post(agent_helpers.GFW_URL).mock(
            return_value=httpx.Response(200, json={"status": "success", "data": []})
        )
        router.get(url__regex=re.compile(agent_helpers.FIRMS_REGEX)).mock(
            return_value=httpx.Response(200, text="")
        )

        base = [
            "--record",
            "REC-091",
            "--batch",
            str(batch_path),
            "--operator",
            str(operator_path),
        ]
        paused = main([*base, "--out", str(tmp_path / "paused")])
        resumed = main([*base, "--out", str(tmp_path / "resumed"), "--decision", "approve"])

    assert paused == 2
    assert resumed == 0
    paused_payload = json.loads(_run_file(tmp_path / "paused").read_text(encoding="utf-8"))
    resumed_payload = json.loads(_run_file(tmp_path / "resumed").read_text(encoding="utf-8"))
    assert paused_payload["state"] == "awaiting_review"
    assert paused_payload["assessment"] is None
    assert paused_payload["pending_assessment"] is not None
    assert resumed_payload["state"] == "complete"
    assert resumed_payload["assessment"] is not None
    assert resumed_payload["review"]["decision"] == "approve"
