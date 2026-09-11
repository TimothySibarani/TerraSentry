"""Stub SAP endpoints behind ``SAP_MODE=stub`` (M7 wires the gateway to these).

The primary contract is API-Hub-accurate OData over the
``API_BUSINESS_PARTNER`` entities: ``A_Supplier`` (``Supplier``,
``PurchasingIsBlocked``, ``PostingIsBlocked``, ``PaymentIsBlockedForSupplier``)
and ``A_BusinessPartner`` (``BusinessPartner``, ``BusinessPartnerIsBlocked``).
Reads are GETs and updates are PATCHes carrying the PascalCase OData body.

The ``/vendors`` routes are a TerraSentry convenience view over the same store
used by the agents' :class:`~terrasentry_integrations.sap.protocol.SapGateway`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from terrasentry_integrations.sap import SupplierPatch

from terrasentry_api.schemas import SapBlockIn, SapStatusIn, SapVendorOut
from terrasentry_api.services import AppServices, get_services

router = APIRouter(prefix="/mock-sap", tags=["mock-sap"])

ServicesDep = Annotated[AppServices, Depends(get_services)]


def _with_context(entity_set: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"@odata.context": f"$metadata#{entity_set}/$entity", **payload}


@router.get("/A_Supplier('{vendor_id}')")
async def get_supplier_entity(vendor_id: str, services: ServicesDep) -> dict[str, Any]:
    entity = services.sap_stub.supplier_entity(vendor_id)
    return _with_context("A_Supplier", entity.to_odata())


@router.patch("/A_Supplier('{vendor_id}')", operation_id="patch_supplier_entity")
async def update_supplier_entity(
    vendor_id: str,
    payload: SupplierPatch,
    services: ServicesDep,
) -> dict[str, Any]:
    entity = services.sap_stub.apply_supplier_patch(vendor_id, payload)
    return _with_context("A_Supplier", entity.to_odata())


@router.get("/A_BusinessPartner('{vendor_id}')")
async def get_business_partner_entity(vendor_id: str, services: ServicesDep) -> dict[str, Any]:
    entity = services.sap_stub.business_partner_entity(vendor_id)
    return _with_context("A_BusinessPartner", entity.to_odata())


@router.get("/vendors/{vendor_id}", response_model=SapVendorOut)
async def get_vendor(vendor_id: str, services: ServicesDep) -> SapVendorOut:
    return SapVendorOut.from_vendor(await services.sap_stub.get_vendor_status(vendor_id))


@router.put("/vendors/{vendor_id}/status", response_model=SapVendorOut)
async def update_vendor_status(
    vendor_id: str,
    payload: SapStatusIn,
    services: ServicesDep,
) -> SapVendorOut:
    vendor = await services.sap_stub.update_vendor_status(vendor_id, payload.status)
    return SapVendorOut.from_vendor(vendor)


@router.put("/vendors/{vendor_id}/purchasing-block", response_model=SapVendorOut)
async def set_purchasing_block(
    vendor_id: str,
    payload: SapBlockIn,
    services: ServicesDep,
) -> SapVendorOut:
    vendor = await services.sap_stub.set_purchasing_block(vendor_id, payload.blocked)
    return SapVendorOut.from_vendor(vendor)


__all__ = ["router"]
