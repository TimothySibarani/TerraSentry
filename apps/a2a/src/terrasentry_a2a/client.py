"""Thin async client for the TerraSentry API; failures become an ``ApiError`` safe to show a user."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

TERMINAL_STATES = frozenset({"complete", "failed", "awaiting_review"})
_PAGE = 200


class ApiError(Exception):
    """The TerraSentry API could not do what was asked; the message is safe to show a user."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Supplier(_Model):
    supplier_id: str
    legal_name: str
    trading_name: str = ""


class Finding(_Model):
    code: str
    level: str
    points: int = 0
    detail: str = ""


class _Assessment(_Model):
    findings: list[Finding] = Field(default_factory=list)


class _Verdict(_Model):
    assessment: _Assessment


class Run(_Model):
    run_id: str
    state: str
    record_id: str | None = None
    supplier_id: str | None = None
    model: str = ""
    summary: str = ""
    error: str | None = None
    verdict: str | None = None
    score: int | None = None
    assessment: _Verdict | None = None
    pending_assessment: _Verdict | None = None

    @property
    def findings(self) -> list[Finding]:
        verdict = self.assessment or self.pending_assessment
        return verdict.assessment.findings if verdict else []


class Batch(_Model):
    run_id: str
    state: str
    record_count: int = 0
    states: dict[str, int] = Field(default_factory=dict)
    verdict_breakdown: dict[str, int] = Field(default_factory=dict)


class TerraSentryClient:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        *,
        http: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = http or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError("The TerraSentry API is unreachable right now.") from exc
        if response.status_code == 404:
            raise ApiError("TerraSentry has no record of that.")
        if response.status_code in {401, 403}:
            raise ApiError("The TerraSentry API rejected the proxy's credentials.")
        if response.status_code >= 400:
            raise ApiError(f"The TerraSentry API answered {response.status_code}.")
        return response.json()

    async def list_suppliers(self) -> list[Supplier]:
        suppliers: list[Supplier] = []
        offset = 0
        while True:
            page = await self._request("GET", "/suppliers", params={"limit": _PAGE, "offset": offset})
            suppliers.extend(Supplier.model_validate(item) for item in page)
            if len(page) < _PAGE:
                return suppliers
            offset += _PAGE

    async def start_screening(self, record_id: str) -> Batch:
        body = {"mode": "screening", "record_ids": [record_id]}
        return Batch.model_validate(await self._request("POST", "/batch-runs", json=body))

    async def get_batch(self, batch_id: str) -> Batch:
        return Batch.model_validate(await self._request("GET", f"/batch-runs/{batch_id}"))

    async def start_agent_run(self, record_id: str, model: str) -> Run:
        body = {"record_id": record_id, "model": model}
        return Run.model_validate(await self._request("POST", "/runs", json=body))

    async def get_run(self, run_id: str) -> Run:
        return Run.model_validate(await self._request("GET", f"/runs/{run_id}"))


__all__ = [
    "TERMINAL_STATES",
    "ApiError",
    "Batch",
    "Finding",
    "Run",
    "Supplier",
    "TerraSentryClient",
]
