"""SAP HTTP client for the Business Accelerator Hub sandbox or a live tenant.

Both transports speak the ``API_BUSINESS_PARTNER`` OData entity shapes:

- sandbox: the Hub's free sandbox, authenticated with an ``APIKey`` header.
- live: a real tenant or BTP Integration Suite endpoint, authenticated with a
  cached OAuth client-credentials bearer token.

Requests go through the shared :class:`SourceHttpClient`, so retries, the
per-source rate limit, and typed failures behave exactly like the GFW/FIRMS
clients. Configuration is validated at call time, not construction time, so an
unconfigured SAP mode cannot stop the API from starting.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from terrasentry_integrations.errors import (
    MissingCredentialError,
    SourceAuthError,
    SourceResponseError,
)
from terrasentry_integrations.sap.models import (
    SAP_APIKEY_HEADER,
    STATUS_BLOCKED,
    BusinessPartnerEntity,
    SupplierEntity,
    VendorStatus,
    normalize_sap_mode,
    vendor_status_from_supplier,
)
from terrasentry_integrations.settings import IntegrationSettings
from terrasentry_integrations.sources.http import SourceHttpClient, SourceHttpConfig

SUPPLIER_SELECT = "Supplier,PurchasingIsBlocked,PostingIsBlocked,PaymentIsBlockedForSupplier"
BUSINESS_PARTNER_SELECT = "BusinessPartner,BusinessPartnerIsBlocked"


class HttpSapClient:
    """A :class:`~terrasentry_integrations.sap.protocol.SapGateway` over HTTP."""

    def __init__(self, settings: IntegrationSettings) -> None:
        self._settings = settings
        self._mode = normalize_sap_mode(settings.sap_mode)
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._http = SourceHttpClient(
            SourceHttpConfig(
                source=f"sap-{self._mode}",
                base_url=settings.sap_base_url.strip() or "http://sap.invalid",
                rate_limit=max(settings.sap_rate_limit_per_min, 1),
                time_period=60.0,
                max_attempts=3,
                timeout_seconds=30.0,
                # OData V2 gateways default to Atom; negotiate JSON explicitly.
                headers={"Accept": "application/json"},
            )
        )

    @property
    def mode(self) -> str:
        return self._mode

    # -- gateway API -------------------------------------------------------------

    async def get_vendor_status(self, vendor_id: str) -> VendorStatus:
        entity = await self._get_entity("A_Supplier", vendor_id, SUPPLIER_SELECT)
        return vendor_status_from_supplier(SupplierEntity.model_validate(entity))

    async def get_business_partner(self, vendor_id: str) -> BusinessPartnerEntity:
        entity = await self._get_entity("A_BusinessPartner", vendor_id, BUSINESS_PARTNER_SELECT)
        return BusinessPartnerEntity.model_validate(entity)

    async def update_vendor_status(self, vendor_id: str, status: str) -> VendorStatus:
        blocked = status == STATUS_BLOCKED
        entity = await self._patch_entity(
            vendor_id,
            {
                "PurchasingIsBlocked": blocked,
                "PostingIsBlocked": blocked,
                "PaymentIsBlockedForSupplier": blocked,
            },
        )
        return vendor_status_from_supplier(SupplierEntity.model_validate(entity))

    async def set_purchasing_block(self, vendor_id: str, blocked: bool) -> VendorStatus:
        entity = await self._patch_entity(vendor_id, {"PurchasingIsBlocked": blocked})
        return vendor_status_from_supplier(SupplierEntity.model_validate(entity))

    async def close(self) -> None:
        await self._http.close()

    # -- transport helpers -------------------------------------------------------

    def _ensure_configured(self) -> None:
        settings = self._settings
        if not settings.sap_base_url.strip():
            raise MissingCredentialError("SAP", "SAP_BASE_URL")
        if self._mode == "sandbox" and not settings.sap_api_key.strip():
            raise MissingCredentialError("SAP", "SAP_API_KEY")
        if self._mode == "live":
            if not settings.sap_token_url.strip():
                raise MissingCredentialError("SAP", "SAP_TOKEN_URL")
            if not settings.sap_client_id.strip() or not settings.sap_client_secret.strip():
                raise MissingCredentialError("SAP", "SAP_CLIENT_ID/SAP_CLIENT_SECRET")

    async def _auth_headers(self) -> dict[str, str]:
        self._ensure_configured()
        if self._mode == "sandbox":
            return {SAP_APIKEY_HEADER: self._settings.sap_api_key.strip()}
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return {"Authorization": f"Bearer {self._token}"}
        return await self._fetch_token()

    async def _fetch_token(self) -> dict[str, str]:
        async with self._token_lock:
            if self._token is not None and time.monotonic() < self._token_expires_at:
                return {"Authorization": f"Bearer {self._token}"}
            response = await self._http.post(
                self._settings.sap_token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._settings.sap_client_id,
                    "client_secret": self._settings.sap_client_secret,
                },
            )
            try:
                payload: Any = response.json()
            except ValueError as exc:
                raise SourceResponseError("sap-live", "token endpoint did not return JSON") from exc
            token = payload.get("access_token") if isinstance(payload, dict) else None
            if not isinstance(token, str) or not token:
                raise SourceAuthError("sap-live", "token endpoint returned no access_token")
            expires_in = payload.get("expires_in")
            ttl = float(expires_in) if isinstance(expires_in, (int, float)) else 300.0
            self._token = token
            self._token_expires_at = time.monotonic() + max(ttl - 30.0, 5.0)
            return {"Authorization": f"Bearer {token}"}

    async def _get_entity(self, entity_set: str, vendor_id: str, select: str) -> dict[str, Any]:
        response = await self._authorized(
            "GET",
            self._entity_path(entity_set, vendor_id),
            params={"$select": select},
        )
        return _json_object(response, self._mode)

    async def _patch_entity(self, vendor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._authorized(
            "PATCH",
            self._entity_path("A_Supplier", vendor_id),
            json=payload,
        )
        return _json_object(response, self._mode)

    async def _authorized(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send one authenticated request, refreshing a revoked live token once."""
        try:
            return await self._http.request(method, path, headers=await self._auth_headers(), **kwargs)
        except SourceAuthError:
            if self._mode != "live":
                raise
            # A cached token can be revoked before its TTL; retry with a fresh one.
            self._token = None
            self._token_expires_at = 0.0
            return await self._http.request(method, path, headers=await self._auth_headers(), **kwargs)

    @staticmethod
    def _entity_path(entity_set: str, vendor_id: str) -> str:
        escaped = vendor_id.replace("'", "''")
        return f"{entity_set}('{escaped}')"


def _json_object(response: Any, mode: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SourceResponseError(f"sap-{mode}", "SAP response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SourceResponseError(f"sap-{mode}", "SAP response was not a JSON object")
    if "error" in payload:
        detail = payload["error"]
        message = detail.get("message", {}) if isinstance(detail, dict) else {}
        text = message.get("value") if isinstance(message, dict) else str(detail)
        raise SourceResponseError(f"sap-{mode}", f"OData error: {text}")
    return payload


__all__ = ["BUSINESS_PARTNER_SELECT", "SUPPLIER_SELECT", "HttpSapClient"]
