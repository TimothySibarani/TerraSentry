"""SAP gateway seam: protocol, contract models, stub, and HTTP client.

``SAP_MODE`` selects the transport (see :mod:`terrasentry_integrations.sap.factory`):

- ``stub`` — the schema-accurate in-process :class:`StubSapService`
  (PRD Option 2), also served by the API's ``/mock-sap`` router.
- ``sandbox`` — API Business Accelerator Hub sandbox over HTTP.
- ``live`` — a real tenant or BTP Integration Suite endpoint over HTTP.

The runner only sees :class:`SapGateway`; swapping the transport changes
nothing above this package.
"""

from terrasentry_integrations.sap.client import HttpSapClient
from terrasentry_integrations.sap.factory import (
    build_sap_gateway,
    resolve_sap_mode,
    sap_mode_is_real,
)
from terrasentry_integrations.sap.models import (
    STATUS_APPROVED,
    STATUS_BLOCKED,
    STATUS_FAILED,
    BusinessPartnerEntity,
    SapMode,
    SupplierEntity,
    SupplierPatch,
    VendorStatus,
    supplier_entity_from_status,
    vendor_status_from_supplier,
)
from terrasentry_integrations.sap.protocol import SapGateway
from terrasentry_integrations.sap.stub import StubSapService

__all__ = [
    "STATUS_APPROVED",
    "STATUS_BLOCKED",
    "STATUS_FAILED",
    "BusinessPartnerEntity",
    "HttpSapClient",
    "SapGateway",
    "SapMode",
    "StubSapService",
    "SupplierEntity",
    "SupplierPatch",
    "VendorStatus",
    "build_sap_gateway",
    "resolve_sap_mode",
    "sap_mode_is_real",
    "supplier_entity_from_status",
    "vendor_status_from_supplier",
]
