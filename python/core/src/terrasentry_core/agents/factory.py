"""Model-bundle selection shared by the agent CLI and the M4 API.

``scripted`` runs the full graph with no network and no model calls (the
deterministic verifier checks are still the hard gate); ``sap`` uses the
``AICORE_MODEL_*`` ids (SAP AI Core, via LiteLLM) configured in the environment.
"""

from __future__ import annotations

from terrasentry_core.agents.models import ModelBundle
from terrasentry_core.agents.scripted import AdaptiveAutopilotResponder, ScriptedModel
from terrasentry_core.agents.verification import VerificationReport
from terrasentry_core.seed.schemas import BatchRecord

MODEL_MODES = ("scripted", "sap")
DEFAULT_MODEL_MODE = "scripted"
#: Scripted-only fault injection: scenario -> (real demo scenario, skip the deep dives).
FAULT_SCENARIOS: dict[str, tuple[str, bool]] = {"coverage_catch": ("high_risk_live", True)}


def scripted_bundle(record: BatchRecord, *, skip_deep_dives: bool = False) -> ModelBundle:
    """Models for one record: adaptive autopilot turns plus an accepting verifier review."""
    responder = AdaptiveAutopilotResponder.for_record(
        record,
        skip_deep_dives=skip_deep_dives,
        structured_outputs={
            VerificationReport: VerificationReport(
                accepted=True,
                checked_claims=["llm.scripted"],
                notes=["scripted verifier: deterministic checks are the gate"],
            )
        },
    )
    return ModelBundle(
        orchestrator=ScriptedModel(responder=responder),
        extraction=ScriptedModel(responder=responder),
    )


def model_bundle_for(mode: str, record: BatchRecord, *, skip_deep_dives: bool = False) -> ModelBundle:
    """Resolve a ``scripted`` or ``sap`` mode to a concrete :class:`ModelBundle`."""
    if mode == "sap":
        return ModelBundle.from_aicore()
    if mode == "scripted":
        return scripted_bundle(record, skip_deep_dives=skip_deep_dives)
    raise ValueError(f"unknown model mode {mode!r}; choose one of {', '.join(MODEL_MODES)}")


__all__ = ["DEFAULT_MODEL_MODE", "FAULT_SCENARIOS", "MODEL_MODES", "model_bundle_for", "scripted_bundle"]
