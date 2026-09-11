"""The M7 closed loop: apply a released verdict to SAP and record what happened.

This is the only place that maps a TerraSentry verdict or human decision to an
ERP action. Rules:

- compliant -> vendor approved, purchasing block cleared
- high_risk -> vendor blocked, purchasing block set
- HITL approve -> approved; HITL override -> blocked
- an ERP failure never fails the compliance run: it is recorded with
  ``status=failed`` and a disclosure, and the vendor state is left unchanged.

The gateway is a :class:`~terrasentry_integrations.sap.protocol.SapGateway`, so
the stub, the API Hub sandbox, and a live tenant are interchangeable here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel
from terrasentry_core.dds import ErpAction
from terrasentry_core.domain.enums import Decision, Verdict
from terrasentry_core.tools.trace import TraceStep, utc_now
from terrasentry_integrations.sap import (
    STATUS_APPROVED,
    STATUS_BLOCKED,
    STATUS_FAILED,
    SapGateway,
    sap_mode_is_real,
)

logger = logging.getLogger(__name__)

STUB_MODE_DISCLOSURE = (
    "SAP integration is implemented against SAP's published API contract "
    "(S/4HANA Supplier / Business Partner) and executed by a schema-accurate "
    "local stub; no live SAP tenant was available during the build."
)
SANDBOX_MODE_DISCLOSURE = (
    "SAP integration calls the SAP Business Accelerator Hub sandbox over its published OData contract."
)
LIVE_MODE_DISCLOSURE = "SAP integration calls a live SAP tenant over its published OData contract."

_DISCLOSURES = {
    "stub": STUB_MODE_DISCLOSURE,
    "sandbox": SANDBOX_MODE_DISCLOSURE,
    "live": LIVE_MODE_DISCLOSURE,
}


def disclosure_for_mode(mode: str) -> str:
    return _DISCLOSURES.get(mode.strip().lower(), STUB_MODE_DISCLOSURE)


class SapActionRecord(BaseModel):
    """One ERP action, successful or failed, as persisted and streamed."""

    run_id: str
    supplier_id: str
    vendor_id: str
    mode: str
    status: str
    purchasing_block: bool = False
    real: bool = False
    external_reference: str | None = None
    error: str | None = None
    performed_at: datetime

    @property
    def failed(self) -> bool:
        return self.status == STATUS_FAILED

    @property
    def disclosure(self) -> str:
        if self.failed:
            return (
                f"ERP action failed ({self.error}); the compliance verdict stands and the "
                "vendor state is unchanged."
            )
        blocked = " with purchasing blocked" if self.purchasing_block else ""
        return f"{disclosure_for_mode(self.mode)} Vendor {self.vendor_id} is now {self.status}{blocked}."

    def to_erp_action(self) -> ErpAction:
        """The DDS extension block for an attempted action, failed or not."""
        return ErpAction(
            vendor_id=self.vendor_id,
            status=self.status,
            purchasing_block=self.purchasing_block,
            mode=self.mode,
            real=self.real,
            external_reference=self.external_reference,
            performed_at=self.performed_at,
            disclosure=self.disclosure,
            error=self.error,
        )

    def to_trace_step(self, index: int) -> TraceStep:
        if self.failed:
            detail = f"{self.vendor_id}: ERP action failed ({self.error})"
        else:
            detail = (
                f"{self.vendor_id}: {self.status}"
                f"{' + purchasing block' if self.purchasing_block else ''} "
                f"via {self.mode} ({'real' if self.real else 'stub'})"
            )
        return TraceStep(
            step_id=f"STEP-{index:03d}",
            kind="sap",
            name="sap_action",
            detail=detail,
            at=self.performed_at,
            payload={
                "vendor_id": self.vendor_id,
                "status": self.status,
                "purchasing_block": self.purchasing_block,
                "mode": self.mode,
                "real": self.real,
                "error": self.error,
            },
        )


class SapActionService:
    """Maps final compliance states to ERP actions through the gateway."""

    def __init__(
        self,
        *,
        gateway: SapGateway,
        mode: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._gateway = gateway
        self._mode = mode
        self._clock = clock

    @property
    def mode(self) -> str:
        return self._mode

    async def apply_verdict(
        self,
        *,
        run_id: str,
        supplier_id: str,
        verdict: Verdict,
    ) -> SapActionRecord:
        """Apply a released automated verdict (compliant or high risk)."""
        status = STATUS_BLOCKED if verdict is Verdict.HIGH_RISK else STATUS_APPROVED
        return await self._apply(run_id=run_id, supplier_id=supplier_id, status=status)

    async def apply_decision(
        self,
        *,
        run_id: str,
        supplier_id: str,
        decision: Decision,
    ) -> SapActionRecord:
        """Apply a human decision on the ambiguous branch."""
        status = STATUS_APPROVED if decision is Decision.APPROVE else STATUS_BLOCKED
        return await self._apply(run_id=run_id, supplier_id=supplier_id, status=status)

    async def _apply(self, *, run_id: str, supplier_id: str, status: str) -> SapActionRecord:
        performed_at = self._clock()
        try:
            vendor = await self._gateway.update_vendor_status(supplier_id, status)
        except Exception as exc:
            # An ERP outage must never fail a compliance run: record it instead.
            logger.warning("SAP action failed for %s: %s", supplier_id, exc)
            return SapActionRecord(
                run_id=run_id,
                supplier_id=supplier_id,
                vendor_id=supplier_id,
                mode=self._mode,
                status=STATUS_FAILED,
                error=f"{type(exc).__name__}: {exc}",
                performed_at=performed_at,
            )
        return SapActionRecord(
            run_id=run_id,
            supplier_id=supplier_id,
            vendor_id=vendor.vendor_id,
            mode=self._mode,
            status=vendor.status,
            purchasing_block=vendor.purchasing_block,
            real=sap_mode_is_real(self._mode),
            performed_at=performed_at,
        )


__all__ = [
    "LIVE_MODE_DISCLOSURE",
    "SANDBOX_MODE_DISCLOSURE",
    "STUB_MODE_DISCLOSURE",
    "SapActionRecord",
    "SapActionService",
    "disclosure_for_mode",
]
