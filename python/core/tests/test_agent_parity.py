"""Parity: the agent path reproduces the reference pipeline's assessment.

Architecture cross-cutting rule 5: the reference pipeline is the baseline and
the agent must match it for the same inputs. Fingerprints, assessments, and DDS
documents are compared; timestamps live only in the evidence snapshots.
"""

from __future__ import annotations

from typing import Any

import agent_helpers
from terrasentry_core.agents.orchestrator import RunOrchestrator
from terrasentry_core.assessment.pipeline import assess_record
from terrasentry_core.domain.enums import RunState
from terrasentry_core.reference.pipeline import run_reference_pipeline
from terrasentry_core.seed.schemas import BatchRecord


def _parity_records(data: Any) -> list[BatchRecord]:
    records = [
        data.record_for_scenario("compliant_live"),
        data.record_for_scenario("high_risk_live"),
        *data.records[:4],
    ]
    unique: dict[str, BatchRecord] = {record.record_id: record for record in records}
    return list(unique.values())


async def test_agent_assessment_matches_reference(source_router, source_clients) -> None:
    data = agent_helpers.datasets()
    records = _parity_records(data)
    reference_run = await run_reference_pipeline(
        [record.polygon for record in records],
        gfw=source_clients.gfw,
        firms=source_clients.firms,
        cache=source_clients.cache,
        window_days=30,
        years=5,
    )
    reports = {report.polygon_id: report for report in reference_run.reports}

    for record in records:
        expected = assess_record(reports[record.polygon.id], record, data.operator)
        orchestrator = RunOrchestrator(
            gfw=source_clients.gfw,
            firms=source_clients.firms,
            datasets=data,
            models=agent_helpers.scripted_models(record),
        )
        result = await orchestrator.run(record.record_id)
        candidate = result.assessment or result.pending_assessment
        assert result.verification is not None and result.verification.accepted, result.trace
        assert result.state in {RunState.COMPLETE, RunState.AWAITING_REVIEW}
        assert candidate is not None, result.trace
        assert candidate.fingerprint == expected.fingerprint, record.record_id
        assert candidate.assessment == expected.assessment, record.record_id
        assert candidate.dds == expected.dds, record.record_id
