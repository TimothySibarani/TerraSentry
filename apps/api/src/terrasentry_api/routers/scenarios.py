"""Demo scenario catalog: what each scenario submits and what it is built to show."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from terrasentry_core.agents.factory import FAULT_SCENARIOS

from terrasentry_api.schemas import ModelMode, ScenarioOut
from terrasentry_api.services import AppServices, get_services

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

ServicesDep = Annotated[AppServices, Depends(get_services)]

#: Presentation copy per scenario id; records come from the seed (``demo_polygons.json``).
_COPY: dict[str, tuple[str, str]] = {
    "compliant_live": (
        "Compliant scenario",
        "Clean parcel: geospatial, thermal and legality screening find nothing to chase, so the "
        "Supervisor does not re-task anyone. The verifier confirms and a DDS is released.",
    ),
    "high_risk_live": (
        "High-risk scenario",
        "Riau peat plot: screening raises signals, so the Supervisor re-tasks the legality and "
        "geospatial analysts for a deep dive and the trace shows each reason. The rubric still owns "
        "the verdict, the verifier re-derives every metric, and the vendor is blocked in SAP (stub).",
    ),
    "fire_live": (
        "Forest fire scenario",
        "South Sumatra peat plot inside a live FIRMS fire cluster: about 450 active detections in "
        "the last 30 days. Fire is one of several flags (legality, loss and moratorium also flag), "
        "so the plot is high risk and waits for a person. The verifier re-derives the detection count.",
    ),
    "coverage_catch": (
        "Verifier catch",
        "The scripted Supervisor skips the required deep dive on the high-risk plot. The verifier's "
        "coverage check rejects the run, so no DDS is released.",
    ),
}


@router.get("", response_model=list[ScenarioOut])
async def list_scenarios(
    services: ServicesDep,
    model: Annotated[ModelMode | None, Query(description="Only scenarios this model can run")] = None,
) -> list[ScenarioOut]:
    out: list[ScenarioOut] = []
    for scenario_id in [*services.datasets.scenarios(), *FAULT_SCENARIOS]:
        fault = scenario_id in FAULT_SCENARIOS
        if fault and model not in (None, "scripted"):
            continue
        base = FAULT_SCENARIOS[scenario_id][0] if fault else scenario_id
        label, description = _COPY.get(scenario_id, (scenario_id.replace("_", " "), ""))
        out.append(
            ScenarioOut(
                id=scenario_id,
                label=label,
                description=description,
                models=["scripted"] if fault else None,
                fault_injection=fault,
                record=services.datasets.record_for_scenario(base),
            )
        )
    return out


__all__ = ["router"]
