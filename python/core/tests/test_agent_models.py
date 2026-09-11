"""Model routing comes from the environment, not hardcoded model ids."""

from __future__ import annotations

import pytest
from terrasentry_core.agents.models import build_model
from terrasentry_core.agents.settings import AgentSettings
from terrasentry_core.errors import MissingModelError


def test_model_for_role_reads_the_configured_ids() -> None:
    settings = AgentSettings(
        bedrock_model_orchestrator="orchestrator-model",
        bedrock_model_extraction="extraction-model",
    )
    assert settings.model_for("orchestrator") == "orchestrator-model"
    assert settings.model_for("extraction") == "extraction-model"
    assert settings.missing_models == []


def test_build_model_requires_a_configured_model() -> None:
    settings = AgentSettings(bedrock_model_orchestrator="", bedrock_model_extraction="")
    assert settings.missing_models == ["BEDROCK_MODEL_ORCHESTRATOR", "BEDROCK_MODEL_EXTRACTION"]
    with pytest.raises(MissingModelError, match="BEDROCK_MODEL_ORCHESTRATOR"):
        build_model("orchestrator", settings=settings)
    with pytest.raises(MissingModelError, match="BEDROCK_MODEL_EXTRACTION"):
        build_model("extraction", settings=settings)
