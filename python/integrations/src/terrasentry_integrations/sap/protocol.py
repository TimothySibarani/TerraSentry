"""The seam every SAP transport implements: stub, sandbox, or a live tenant."""

from __future__ import annotations

from typing import Protocol

from terrasentry_integrations.sap.models import VendorStatus


class SapGateway(Protocol):
    """Vendor status and purchasing block actions, independent of transport."""

    async def get_vendor_status(self, vendor_id: str) -> VendorStatus: ...

    async def update_vendor_status(self, vendor_id: str, status: str) -> VendorStatus: ...

    async def set_purchasing_block(self, vendor_id: str, blocked: bool) -> VendorStatus: ...

    async def close(self) -> None: ...


__all__ = ["SapGateway"]
