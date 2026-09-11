"""Write agent-run artifacts so M4/M5 and the offline demo can read them."""

from __future__ import annotations

import json
from pathlib import Path

from terrasentry_core.agents.schemas import AgentRunResult


def write_agent_run(result: AgentRunResult, out_dir: Path) -> list[Path]:
    """Write the run JSON and, once released, the DDS JSON/XML and evidence."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    run_path = out_dir / f"{result.run_id}.json"
    run_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    written.append(run_path)

    assessment = result.assessment
    if assessment is not None:
        prefix = out_dir / result.run_id
        dds_json = prefix.with_suffix(".dds.json")
        dds_xml = prefix.with_suffix(".dds.xml")
        evidence_json = prefix.with_suffix(".evidence.json")
        dds_json.write_text(assessment.dds.to_json(), encoding="utf-8")
        dds_xml.write_text(assessment.dds.to_xml(), encoding="utf-8")
        evidence_json.write_text(
            json.dumps(
                [entry.model_dump(mode="json") for entry in assessment.evidence],
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        written.extend([dds_json, dds_xml, evidence_json])
    return written


__all__ = ["write_agent_run"]
