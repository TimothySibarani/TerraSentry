"""Select the SAP transport from ``SAP_MODE``: stub, sandbox, or live."""

from __future__ import annotations

from terrasentry_integrations.errors import IntegrationError
from terrasentry_integrations.sap.client import HttpSapClient
from terrasentry_integrations.sap.models import SapMode, normalize_sap_mode
from terrasentry_integrations.sap.protocol import SapGateway
from terrasentry_integrations.sap.stub import StubSapService
from terrasentry_integrations.settings import IntegrationSettings


def build_sap_gateway(
    settings: IntegrationSettings,
    *,
    stub: StubSapService | None = None,
) -> SapGateway:
    """A gateway for the configured mode.

    ``stub`` reuses the shared service instance when one is provided so the
    runner and the ``/mock-sap`` router see the same vendor state; sandbox and
    live return the HTTP client (credentials are checked on the first call).
    """
    mode = resolve_sap_mode(settings)
    if mode == "stub":
        return stub if stub is not None else StubSapService()
    return HttpSapClient(settings)


def resolve_sap_mode(settings: IntegrationSettings) -> SapMode:
    try:
        return normalize_sap_mode(settings.sap_mode)
    except ValueError as exc:
        raise IntegrationError(str(exc)) from exc


def sap_mode_is_real(mode: str) -> bool:
    """True when the action reaches an SAP-hosted endpoint (sandbox or live)."""
    return normalize_sap_mode(mode) != "stub"


__all__ = ["build_sap_gateway", "resolve_sap_mode", "sap_mode_is_real"]
