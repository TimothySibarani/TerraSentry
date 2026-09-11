"""SAP gateway: stub state, API-Hub payload shapes, HTTP transports, factory."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from terrasentry_integrations.errors import (
    IntegrationError,
    MissingCredentialError,
    SourceResponseError,
)
from terrasentry_integrations.sap import (
    STATUS_APPROVED,
    STATUS_BLOCKED,
    HttpSapClient,
    StubSapService,
    SupplierEntity,
    SupplierPatch,
    VendorStatus,
    build_sap_gateway,
    sap_mode_is_real,
)
from terrasentry_integrations.settings import IntegrationSettings

ODATA_BASE = "https://sandbox.example/sap/opu/odata/sap/API_BUSINESS_PARTNER"
SUPPLIER_URL = f"{ODATA_BASE}/A_Supplier('SUP-001')"
BUSINESS_PARTNER_URL = f"{ODATA_BASE}/A_BusinessPartner('SUP-001')"

SUPPLIER_PAYLOAD = {
    "Supplier": "SUP-001",
    "PurchasingIsBlocked": False,
    "PostingIsBlocked": False,
    "PaymentIsBlockedForSupplier": False,
}


def _sandbox_settings(**overrides: Any) -> IntegrationSettings:
    values: dict[str, Any] = {
        "sap_mode": "sandbox",
        "sap_base_url": f"{ODATA_BASE}/",
        "sap_api_key": "SANDBOX-KEY",
        "sap_rate_limit_per_min": 100_000,
    }
    values.update(overrides)
    return IntegrationSettings(**values)


def test_stub_uses_api_hub_entity_field_names() -> None:
    service = StubSapService(["SUP-001"])
    supplier = service.supplier_entity("SUP-001")
    assert isinstance(supplier, SupplierEntity)
    assert supplier.to_odata() == {
        "Supplier": "SUP-001",
        "PurchasingIsBlocked": False,
        "PostingIsBlocked": False,
        "PaymentIsBlockedForSupplier": False,
    }
    partner = service.business_partner_entity("SUP-001")
    assert partner.to_odata() == {
        "BusinessPartner": "SUP-001",
        "BusinessPartnerIsBlocked": False,
    }


async def test_stub_flips_status_and_block() -> None:
    service = StubSapService(["SUP-001"])
    assert (await service.get_vendor_status("SUP-001")).status == STATUS_APPROVED

    blocked = await service.update_vendor_status("SUP-001", STATUS_BLOCKED)
    assert blocked.status == STATUS_BLOCKED
    assert blocked.purchasing_block is True
    assert service.supplier_entity("SUP-001").to_odata()["PostingIsBlocked"] is True

    unblocked = await service.set_purchasing_block("SUP-001", False)
    assert unblocked.status == STATUS_APPROVED
    assert unblocked.purchasing_block is False

    unknown = await service.get_vendor_status("SUP-404")
    assert unknown.status == STATUS_APPROVED


async def test_stub_restore_replays_persisted_state() -> None:
    service = StubSapService()
    service.restore(
        [
            VendorStatus(vendor_id="SUP-001", status=STATUS_BLOCKED, purchasing_block=True),
            VendorStatus(vendor_id="SUP-002", status=STATUS_APPROVED),
        ]
    )
    assert (await service.get_vendor_status("SUP-001")).status == STATUS_BLOCKED
    assert (await service.get_vendor_status("SUP-002")).status == STATUS_APPROVED


async def test_stub_odata_patch_applies_purchasing_block() -> None:
    service = StubSapService(["SUP-001"])
    entity = service.apply_supplier_patch("SUP-001", SupplierPatch(PurchasingIsBlocked=True))
    assert entity.purchasing_is_blocked is True
    assert (await service.get_vendor_status("SUP-001")).status == STATUS_BLOCKED


async def test_stub_odata_patch_stays_blocked_while_any_indicator_is_set() -> None:
    service = StubSapService(["SUP-001"])
    service.apply_supplier_patch(
        "SUP-001",
        SupplierPatch(PurchasingIsBlocked=True, PostingIsBlocked=False),
    )
    assert (await service.get_vendor_status("SUP-001")).status == STATUS_BLOCKED

    # An explicit false on a field we do not track must not clear the block.
    entity = service.apply_supplier_patch("SUP-001", SupplierPatch(PostingIsBlocked=False))
    assert entity.purchasing_is_blocked is True
    assert (await service.get_vendor_status("SUP-001")).status == STATUS_BLOCKED

    approved = service.apply_supplier_patch("SUP-001", SupplierPatch(PurchasingIsBlocked=False))
    assert approved.purchasing_is_blocked is False
    assert (await service.get_vendor_status("SUP-001")).status == STATUS_APPROVED


def test_factory_selects_transport_by_mode() -> None:
    stub = StubSapService(["SUP-001"])
    assert build_sap_gateway(IntegrationSettings(sap_mode="stub"), stub=stub) is stub
    assert isinstance(build_sap_gateway(IntegrationSettings(sap_mode="stub")), StubSapService)
    assert isinstance(
        build_sap_gateway(_sandbox_settings()),
        HttpSapClient,
    )
    with pytest.raises(IntegrationError):
        build_sap_gateway(IntegrationSettings(sap_mode="martian"))


def test_sap_mode_is_real_only_for_hosted_endpoints() -> None:
    assert sap_mode_is_real("sandbox") is True
    assert sap_mode_is_real("live") is True
    assert sap_mode_is_real("stub") is False


async def test_sandbox_get_uses_apikey_header() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(SUPPLIER_URL).mock(return_value=httpx.Response(200, json=SUPPLIER_PAYLOAD))
        client = HttpSapClient(_sandbox_settings())
        try:
            vendor = await client.get_vendor_status("SUP-001")
        finally:
            await client.close()
    assert vendor.status == STATUS_APPROVED
    assert route.calls[0].request.headers["APIKey"] == "SANDBOX-KEY"
    assert route.calls[0].request.headers["Accept"] == "application/json"


async def test_sandbox_update_sends_the_full_block_contract() -> None:
    blocked_payload = {
        **SUPPLIER_PAYLOAD,
        "PurchasingIsBlocked": True,
        "PostingIsBlocked": True,
        "PaymentIsBlockedForSupplier": True,
    }
    with respx.mock(assert_all_called=False) as mock:
        route = mock.patch(SUPPLIER_URL).mock(return_value=httpx.Response(200, json=blocked_payload))
        client = HttpSapClient(_sandbox_settings())
        try:
            vendor = await client.update_vendor_status("SUP-001", STATUS_BLOCKED)
        finally:
            await client.close()
    assert vendor.status == STATUS_BLOCKED
    assert vendor.purchasing_block is True
    assert json.loads(route.calls[0].request.content) == {
        "PurchasingIsBlocked": True,
        "PostingIsBlocked": True,
        "PaymentIsBlockedForSupplier": True,
    }


async def test_sandbox_patch_sends_odata_fields() -> None:
    blocked_payload = {
        **SUPPLIER_PAYLOAD,
        "PurchasingIsBlocked": True,
        "PostingIsBlocked": True,
        "PaymentIsBlockedForSupplier": True,
    }
    with respx.mock(assert_all_called=False) as mock:
        route = mock.patch(SUPPLIER_URL).mock(return_value=httpx.Response(200, json=blocked_payload))
        client = HttpSapClient(_sandbox_settings())
        try:
            vendor = await client.set_purchasing_block("SUP-001", True)
        finally:
            await client.close()
    assert vendor.status == STATUS_BLOCKED
    assert route.calls[0].request.content == b'{"PurchasingIsBlocked":true}'


async def test_business_partner_entity_is_readable() -> None:
    payload = {"BusinessPartner": "SUP-001", "BusinessPartnerIsBlocked": True}
    with respx.mock(assert_all_called=False) as mock:
        mock.get(BUSINESS_PARTNER_URL).mock(return_value=httpx.Response(200, json=payload))
        client = HttpSapClient(_sandbox_settings())
        try:
            partner = await client.get_business_partner("SUP-001")
        finally:
            await client.close()
    assert partner.business_partner_is_blocked is True


async def test_live_uses_oauth_and_caches_the_token() -> None:
    token_url = "https://auth.example/oauth/token"
    payload = {"Supplier": "SUP-001", "PurchasingIsBlocked": False}
    with respx.mock(assert_all_called=False) as mock:
        token_route = mock.post(token_url).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "TOKEN", "expires_in": 3600, "token_type": "Bearer"},
            )
        )
        supplier_route = mock.get(SUPPLIER_URL).mock(return_value=httpx.Response(200, json=payload))
        settings = IntegrationSettings(
            sap_mode="live",
            sap_base_url=f"{ODATA_BASE}/",
            sap_token_url=token_url,
            sap_client_id="client",
            sap_client_secret="secret",
            sap_rate_limit_per_min=100_000,
        )
        client = HttpSapClient(settings)
        try:
            await client.get_vendor_status("SUP-001")
            await client.get_vendor_status("SUP-001")
        finally:
            await client.close()
    assert token_route.call_count == 1
    assert supplier_route.calls[0].request.headers["Authorization"] == "Bearer TOKEN"


async def test_live_refreshes_a_revoked_token_once() -> None:
    token_url = "https://auth.example/oauth/token"
    payload = {"Supplier": "SUP-001", "PurchasingIsBlocked": False}
    with respx.mock(assert_all_called=False) as mock:
        token_route = mock.post(token_url).mock(
            side_effect=[
                httpx.Response(200, json={"access_token": "TOKEN-1", "expires_in": 3600}),
                httpx.Response(200, json={"access_token": "TOKEN-2", "expires_in": 3600}),
            ]
        )
        supplier_route = mock.get(SUPPLIER_URL).mock(
            side_effect=[
                httpx.Response(401, json={"error": {"message": {"value": "revoked"}}}),
                httpx.Response(200, json=payload),
            ]
        )
        settings = IntegrationSettings(
            sap_mode="live",
            sap_base_url=f"{ODATA_BASE}/",
            sap_token_url=token_url,
            sap_client_id="client",
            sap_client_secret="secret",
            sap_rate_limit_per_min=100_000,
        )
        client = HttpSapClient(settings)
        try:
            vendor = await client.get_vendor_status("SUP-001")
        finally:
            await client.close()
    assert vendor.status == STATUS_APPROVED
    assert token_route.call_count == 2
    assert supplier_route.calls[1].request.headers["Authorization"] == "Bearer TOKEN-2"


async def test_missing_sandbox_credentials_fail_on_call() -> None:
    client = HttpSapClient(IntegrationSettings(sap_mode="sandbox", sap_base_url=""))
    try:
        with pytest.raises(MissingCredentialError):
            await client.get_vendor_status("SUP-001")
    finally:
        await client.close()


async def test_odata_error_payload_is_a_typed_failure() -> None:
    error_body = {
        "error": {
            "code": "/IWBEP/CX_MGW_BUSI_EXCEPTION",
            "message": {"lang": "en", "value": "Supplier not found"},
        }
    }
    with respx.mock(assert_all_called=False) as mock:
        mock.get(SUPPLIER_URL).mock(return_value=httpx.Response(404, json=error_body))
        client = HttpSapClient(_sandbox_settings())
        try:
            with pytest.raises(SourceResponseError):
                await client.get_vendor_status("SUP-001")
        finally:
            await client.close()
