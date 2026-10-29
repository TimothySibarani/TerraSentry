"""Thin async client for the TerraSentry API; failures become an ``ApiError`` safe to show an agent."""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError


class ApiError(ToolError):
    """The TerraSentry API could not do what was asked; the message tells the caller what to fix.

    A ``ToolError`` is the SDK's deliberate failure: its message reaches the agent, whereas any
    other exception is masked behind a generic "Error executing tool".
    """


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or "no detail"
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return "; ".join(
            f"{'.'.join(str(part) for part in item.get('loc', [])[1:])}: {item.get('msg')}"
            for item in detail
            if isinstance(item, dict)
        )
    return str(detail or body)[:200]


class TerraSentryApi:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        *,
        http: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._base_url = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(base_url=self._base_url, headers=headers, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(
                f"The TerraSentry API at {self._base_url} is unreachable. Start it with `pnpm dev`."
            ) from exc
        if response.status_code in {401, 403}:
            raise ApiError("The TerraSentry API rejected the token; set TERRASENTRY_API_TOKEN.")
        if response.status_code >= 400:
            raise ApiError(f"{response.status_code}: {_detail(response)}")
        if "json" in response.headers.get("content-type", ""):
            return response.json()
        return response.text

    # -- reads ------------------------------------------------------------------------------

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/runs/{run_id}")

    async def get_evidence(self, run_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/runs/{run_id}/evidence")

    async def list_runs(
        self, *, state: str | None = None, kind: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if state:
            params["state"] = state
        if kind:
            params["kind"] = kind
        return await self._request("GET", "/runs", params=params)

    async def get_batch(self, batch_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/batch-runs/{batch_id}")

    async def get_dds(self, run_id: str, *, xml: bool = False) -> Any:
        return await self._request("GET", f"/dds/{run_id}/xml" if xml else f"/dds/{run_id}")

    async def list_suppliers(self, *, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        return await self._request("GET", "/suppliers", params={"limit": limit, "offset": offset})

    # -- writes -----------------------------------------------------------------------------

    async def create_record(self, submission: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/records", json=submission)

    async def import_records(self, filename: str, content: bytes) -> dict[str, Any]:
        return await self._request("POST", "/records/import", files={"file": (filename, content)})

    async def start_run(self, *, record_id: str, model: str | None, erp_mode: str) -> dict[str, Any]:
        body: dict[str, Any] = {"record_id": record_id, "erp_mode": erp_mode}
        if model:
            body["model"] = model
        return await self._request("POST", "/runs", json=body)

    async def start_batch(
        self, *, record_ids: list[str], mode: str, model: str | None, erp_mode: str
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"record_ids": record_ids, "mode": mode, "erp_mode": erp_mode}
        if model and mode == "agent":
            body["model"] = model
        return await self._request("POST", "/batch-runs", json=body)

    async def decide(self, run_id: str, *, decision: str, reviewer: str, note: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/runs/{run_id}/decision",
            json={"decision": decision, "reviewer": reviewer, "note": note},
        )

    async def confirm_erp_action(self, run_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/runs/{run_id}/erp-action")

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/runs/{run_id}/cancel")


__all__ = ["ApiError", "TerraSentryApi"]
