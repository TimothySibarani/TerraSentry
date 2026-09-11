"""SAP contract models: the internal vendor view and the API-Hub payload shapes.

The internal :class:`VendorStatus` is what TerraSentry acts on and displays. The
``SupplierEntity`` / ``BusinessPartnerEntity`` models mirror the public SAP
S/4HANA ``API_BUSINESS_PARTNER`` OData entities (``A_Supplier`` and
``A_BusinessPartner``) so the stub service and the HTTP client speak the real
field names, not a bespoke shape:

- ``A_Supplier``: ``Supplier``, ``PurchasingIsBlocked``, ``PostingIsBlocked``,
  ``PaymentIsBlockedForSupplier``
- ``A_BusinessPartner``: ``BusinessPartner``, ``BusinessPartnerIsBlocked``

References:
https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/44e06f22436c43e582db6ccd5250e29b/85043858ea0f9244e10000000a4450e5.html
https://help.sap.com/docs/SAP_S4HANA_CLOUD/3c916ef10fc240c9afc594b346ffaf77/da61045826552246e10000000a441470.html
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SapMode = Literal["stub", "sandbox", "live"]

STATUS_APPROVED = "approved"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"

#: Header carrying the Business Accelerator Hub sandbox key.
SAP_APIKEY_HEADER = "APIKey"


class VendorStatus(BaseModel):
    """The ERP-side state TerraSentry acts on, independent of the transport."""

    vendor_id: str
    status: str = STATUS_APPROVED
    purchasing_block: bool = False


class SupplierEntity(BaseModel):
    """SAP S/4HANA ``A_Supplier`` payload (OData V2, PascalCase on the wire)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    supplier: str = Field(alias="Supplier")
    purchasing_is_blocked: bool = Field(default=False, alias="PurchasingIsBlocked")
    posting_is_blocked: bool = Field(default=False, alias="PostingIsBlocked")
    payment_is_blocked_for_supplier: bool = Field(default=False, alias="PaymentIsBlockedForSupplier")

    def to_odata(self) -> dict[str, object]:
        return self.model_dump(by_alias=True)


class SupplierPatch(BaseModel):
    """The subset of ``A_Supplier`` an update may carry."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    purchasing_is_blocked: bool | None = Field(default=None, alias="PurchasingIsBlocked")
    posting_is_blocked: bool | None = Field(default=None, alias="PostingIsBlocked")
    payment_is_blocked_for_supplier: bool | None = Field(default=None, alias="PaymentIsBlockedForSupplier")


class BusinessPartnerEntity(BaseModel):
    """SAP S/4HANA ``A_BusinessPartner`` payload (central blocking indicator)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    business_partner: str = Field(alias="BusinessPartner")
    business_partner_is_blocked: bool = Field(default=False, alias="BusinessPartnerIsBlocked")

    def to_odata(self) -> dict[str, object]:
        return self.model_dump(by_alias=True)


def vendor_status_from_supplier(entity: SupplierEntity) -> VendorStatus:
    """Project the SAP entity onto the internal vendor view.

    Purchasing or posting blocks both make the vendor non-orderable, so both map
    to ``blocked``; ``purchasing_block`` records the purchasing-org indicator.
    """
    blocked = entity.purchasing_is_blocked or entity.posting_is_blocked
    return VendorStatus(
        vendor_id=entity.supplier,
        status=STATUS_BLOCKED if blocked else STATUS_APPROVED,
        purchasing_block=entity.purchasing_is_blocked,
    )


def supplier_entity_from_status(vendor: VendorStatus) -> SupplierEntity:
    """Project the internal view back onto the SAP entity shape."""
    return SupplierEntity(
        Supplier=vendor.vendor_id,
        PurchasingIsBlocked=vendor.purchasing_block,
        PostingIsBlocked=vendor.status == STATUS_BLOCKED,
        PaymentIsBlockedForSupplier=vendor.status == STATUS_BLOCKED,
    )


def normalize_sap_mode(value: str) -> SapMode:
    mode = value.strip().lower()
    if mode == "stub" or mode == "sandbox" or mode == "live":
        return mode
    raise ValueError(f"unknown SAP_MODE {value!r}; expected stub, sandbox, or live")


__all__ = [
    "SAP_APIKEY_HEADER",
    "STATUS_APPROVED",
    "STATUS_BLOCKED",
    "STATUS_FAILED",
    "BusinessPartnerEntity",
    "SapMode",
    "SupplierEntity",
    "SupplierPatch",
    "VendorStatus",
    "normalize_sap_mode",
    "supplier_entity_from_status",
    "vendor_status_from_supplier",
]
