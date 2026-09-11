"""In-memory stub behind the ``SAP_MODE=stub`` contract.

The M4 milestone only needs the endpoints and payload shapes; M7 wires the
:class:`~terrasentry_integrations.sap.SapGateway` client and the compliance
decision to it. Values default to an approved, unblocked vendor so the demo can
flip a status and show the change.
"""

from __future__ import annotations

from collections.abc import Iterable

from terrasentry_integrations.sap import VendorStatus


class MockSapStore:
    """Vendor status and purchasing block, in process memory."""

    def __init__(self, vendor_ids: Iterable[str] = ()) -> None:
        self._vendors: dict[str, VendorStatus] = {}
        for vendor_id in vendor_ids:
            self._vendors[vendor_id] = VendorStatus(vendor_id=vendor_id, status="approved")

    def _vendor(self, vendor_id: str) -> VendorStatus:
        existing = self._vendors.get(vendor_id)
        if existing is None:
            existing = VendorStatus(vendor_id=vendor_id, status="approved")
            self._vendors[vendor_id] = existing
        return existing

    def get_vendor_status(self, vendor_id: str) -> VendorStatus:
        return self._vendor(vendor_id)

    def update_vendor_status(self, vendor_id: str, status: str) -> VendorStatus:
        vendor = self._vendor(vendor_id)
        vendor.status = status
        return vendor

    def set_purchasing_block(self, vendor_id: str, blocked: bool) -> VendorStatus:
        vendor = self._vendor(vendor_id)
        vendor.purchasing_block = blocked
        return vendor


__all__ = ["MockSapStore"]
