from typing import Protocol

from pydantic import BaseModel


class VendorStatus(BaseModel):
    vendor_id: str
    status: str
    purchasing_block: bool = False


class SapGateway(Protocol):
    async def get_vendor_status(self, vendor_id: str) -> VendorStatus: ...

    async def update_vendor_status(self, vendor_id: str, status: str) -> VendorStatus: ...

    async def set_purchasing_block(self, vendor_id: str, blocked: bool) -> VendorStatus: ...
