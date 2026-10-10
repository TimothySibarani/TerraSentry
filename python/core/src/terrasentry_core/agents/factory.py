"""Model-bundle selection shared by the agent CLI and the M4 API.

``scripted`` runs the full graph with no network and no Bedrock calls (the
deterministic verifier checks are still the hard gate); ``bedrock`` uses the
orchestrator/extraction model ids configured in the environment.
"""

from __future__ import annotations

from terrasentry_core.agents.models import ModelBundle
from terrasentry_core.agents.scripted import AdaptiveAutopilotResponder, ScriptedModel
from terrasentry_core.agents.verification import VerificationReport
from terrasentry_core.seed.schemas import BatchRecord

MODEL_MODES = ("scripted", "bedrock")
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
    """Resolve a ``scripted`` or ``bedrock`` mode to a concrete :class:`ModelBundle`."""
    if mode == "bedrock":
        return ModelBundle.from_settings()
    return scripted_bundle(record, skip_deep_dives=skip_deep_dives)


__all__ = ["DEFAULT_MODEL_MODE", "FAULT_SCENARIOS", "MODEL_MODES", "model_bundle_for", "scripted_bundle"]
