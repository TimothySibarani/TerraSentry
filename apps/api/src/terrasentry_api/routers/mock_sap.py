"""Mock SAP endpoints behind ``SAP_MODE=stub`` (M7 wires the gateway to these).

Payload field names are kept close to the API Business Hub vendor shapes; the
store is in-process and defaults every vendor to approved and unblocked.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from terrasentry_api.schemas import SapBlockIn, SapStatusIn, SapVendorOut
from terrasentry_api.services import AppServices, get_services

router = APIRouter(prefix="/mock-sap", tags=["mock-sap"])

ServicesDep = Annotated[AppServices, Depends(get_services)]


@router.get("/vendors/{vendor_id}", response_model=SapVendorOut)
async def get_vendor(vendor_id: str, services: ServicesDep) -> SapVendorOut:
    return SapVendorOut.from_vendor(services.mock_sap.get_vendor_status(vendor_id))


@router.put("/vendors/{vendor_id}/status", response_model=SapVendorOut)
async def update_vendor_status(
    vendor_id: str,
    payload: SapStatusIn,
    services: ServicesDep,
) -> SapVendorOut:
    vendor = services.mock_sap.update_vendor_status(vendor_id, payload.status)
    return SapVendorOut.from_vendor(vendor)


@router.put("/vendors/{vendor_id}/purchasing-block", response_model=SapVendorOut)
async def set_purchasing_block(
    vendor_id: str,
    payload: SapBlockIn,
    services: ServicesDep,
) -> SapVendorOut:
    vendor = services.mock_sap.set_purchasing_block(vendor_id, payload.blocked)
    return SapVendorOut.from_vendor(vendor)


__all__ = ["router"]
