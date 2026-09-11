"""In-process stub behind ``SAP_MODE=stub`` (PRD Option 2).

One service instance is shared by the FastAPI ``/mock-sap`` router and the
runner's :class:`~terrasentry_integrations.sap.protocol.SapGateway`, so a status
flip is visible both to the agents and to anyone curling the stub. Payloads use
the real ``API_BUSINESS_PARTNER`` entity shapes; the routes live in
``apps/api/.../routers/mock_sap.py``.

Vendor ids default to approved and unblocked so the demo can flip a status and
show the change. The API replays the persisted action log into
:meth:`restore` at startup, so the stub state survives a restart.
"""

from __future__ import annotations

from collections.abc import Iterable

from terrasentry_integrations.sap.models import (
    STATUS_APPROVED,
    STATUS_BLOCKED,
    BusinessPartnerEntity,
    SupplierEntity,
    SupplierPatch,
    VendorStatus,
    supplier_entity_from_status,
)


class StubSapService:
    """Vendor status and purchasing block, in process memory, SAP-shaped."""

    def __init__(self, vendor_ids: Iterable[str] = ()) -> None:
        self._vendors: dict[str, VendorStatus] = {}
        for vendor_id in vendor_ids:
            self._vendors[vendor_id] = VendorStatus(vendor_id=vendor_id, status=STATUS_APPROVED)

    # -- state -----------------------------------------------------------------

    def _vendor(self, vendor_id: str) -> VendorStatus:
        existing = self._vendors.get(vendor_id)
        if existing is None:
            existing = VendorStatus(vendor_id=vendor_id, status=STATUS_APPROVED)
            self._vendors[vendor_id] = existing
        return existing

    def restore(self, vendors: Iterable[VendorStatus]) -> None:
        """Replay persisted vendor states, e.g. the latest action per supplier."""
        for vendor in vendors:
            self._vendors[vendor.vendor_id] = vendor.model_copy()

    async def get_vendor_status(self, vendor_id: str) -> VendorStatus:
        return self._vendor(vendor_id).model_copy()

    async def update_vendor_status(self, vendor_id: str, status: str) -> VendorStatus:
        vendor = self._vendor(vendor_id)
        vendor.status = status
        vendor.purchasing_block = status == STATUS_BLOCKED
        return vendor.model_copy()

    async def set_purchasing_block(self, vendor_id: str, blocked: bool) -> VendorStatus:
        vendor = self._vendor(vendor_id)
        vendor.purchasing_block = blocked
        vendor.status = STATUS_BLOCKED if blocked else STATUS_APPROVED
        return vendor.model_copy()

    async def close(self) -> None:
        """Nothing to release; present so stub and HTTP gateways are interchangeable."""

    # -- API-Hub-accurate payloads ----------------------------------------------

    def supplier_entity(self, vendor_id: str) -> SupplierEntity:
        return supplier_entity_from_status(self._vendor(vendor_id))

    def business_partner_entity(self, vendor_id: str) -> BusinessPartnerEntity:
        vendor = self._vendor(vendor_id)
        return BusinessPartnerEntity(
            BusinessPartner=vendor.vendor_id,
            BusinessPartnerIsBlocked=vendor.status == STATUS_BLOCKED,
        )

    def apply_supplier_patch(self, vendor_id: str, patch: SupplierPatch) -> SupplierEntity:
        """Apply an OData ``A_Supplier`` PATCH body and return the entity.

        A vendor is non-orderable when any blocking indicator is set, so the
        patch sets ``blocked`` if any supplied flag is true. Only the purchasing
        flag is tracked internally, so an explicit ``false`` on the other two is
        treated as "leave as is" rather than a partial unblock.
        """
        vendor = self._vendor(vendor_id)
        blocked = vendor.purchasing_block
        if patch.purchasing_is_blocked is not None:
            vendor.purchasing_block = patch.purchasing_is_blocked
            blocked = patch.purchasing_is_blocked
        if patch.posting_is_blocked is True or patch.payment_is_blocked_for_supplier is True:
            blocked = True
        vendor.status = STATUS_BLOCKED if blocked else STATUS_APPROVED
        return supplier_entity_from_status(vendor)


__all__ = ["StubSapService"]
