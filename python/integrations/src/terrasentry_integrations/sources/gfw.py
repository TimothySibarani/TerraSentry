"""Global Forest Watch (Hansen GFC) client with cache, limits, and batch jobs."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from terrasentry_integrations.cache import CacheBackend, CacheEntry, geometry_hash
from terrasentry_integrations.errors import (
    MissingCredentialError,
    SourceResponseError,
    SourceUnavailable,
)
from terrasentry_integrations.settings import IntegrationSettings
from terrasentry_integrations.sources.http import SourceHttpClient, SourceHttpConfig

_SAFE_DATASET = re.compile(r"^[a-z0-9_]+$")
_SAFE_VERSION = re.compile(r"^(latest|v\d{1,8}(?:\.\d{1,3}){0,2})$")

_JOB_TERMINAL_STATUSES = {"success", "partial_success", "failed", "error"}


class TreeCoverLossYear(BaseModel):
    year: int
    loss_ha: float


class TreeCoverLossResult(BaseModel):
    dataset: str
    version: str
    geometry_hash: str
    date_window: str
    start_year: int
    end_year: int
    total_loss_ha: float
    by_year: list[TreeCoverLossYear] = Field(default_factory=list)
    cached: bool = False
    fetched_at: datetime | None = None


class BatchJobStatus(BaseModel):
    job_id: str
    status: str = "pending"
    progress: str | None = None
    download_link: str | None = None
    failed_geometries_link: str | None = None
    message: str | None = None


class BatchLossResult(BaseModel):
    job_id: str
    status: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    failed_geometries_link: str | None = None
    cached: bool = False
    fetched_at: datetime | None = None


def _parse_json_body(source: str, text: str) -> Any:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceResponseError(source, f"invalid JSON response: {exc}") from exc
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError as exc:
            raise SourceResponseError(source, "nested JSON response could not be parsed") from exc
    return parsed


def _extract_rows(response: httpx.Response) -> list[dict[str, Any]]:
    payload = _parse_json_body("gfw", response.text)
    if isinstance(payload, dict):
        status = payload.get("status")
        if status not in (None, "success"):
            raise SourceResponseError("gfw", f"query failed: {payload.get('message', status)}")
        data = payload.get("data", payload.get("rows", []))
    else:
        data = payload
    if not isinstance(data, list):
        raise SourceResponseError("gfw", "expected a list of rows from the query endpoint")
    return [dict(row) for row in data if isinstance(row, dict)]


def _year_and_loss(row: dict[str, Any]) -> tuple[int, float] | None:
    year: int | None = None
    loss: float | None = None
    for key, value in row.items():
        lowered = str(key).lower()
        if year is None and "year" in lowered:
            year = int(value)
        elif loss is None and ("loss_ha" in lowered or "area__ha" in lowered or lowered == "sum"):
            loss = float(value)
    if year is None or loss is None:
        return None
    return year, loss


def _extract_download_rows(response: httpx.Response) -> list[dict[str, Any]]:
    content_type = response.headers.get("content-type", "")
    if "csv" in content_type or response.text.lstrip().startswith("fid,"):
        reader = csv.DictReader(io.StringIO(response.text))
        return [dict(row) for row in reader]
    payload = _parse_json_body("gfw", response.text)
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [dict(row) for row in payload["data"] if isinstance(row, dict)]
    return []


class GfwClient:
    """Queries Hansen GFC tree cover loss statistics from the GFW Data API.

    Missing credentials no longer block construction: the API builds its source
    clients at startup so health/suppliers keep working without keys, and the
    typed :class:`MissingCredentialError` is raised on a cache miss instead.
    A warm cache can therefore serve a credential-free offline demo.
    """

    def __init__(
        self,
        settings: IntegrationSettings,
        *,
        cache: CacheBackend,
        http: SourceHttpClient | None = None,
    ) -> None:
        self._missing_credentials: MissingCredentialError | None = (
            None if settings.has_gfw_key else MissingCredentialError("gfw", "GFW_API_KEY")
        )
        if not _SAFE_DATASET.match(settings.gfw_tcl_dataset):
            raise ValueError(f"invalid GFW dataset identifier: {settings.gfw_tcl_dataset!r}")
        if not _SAFE_VERSION.match(settings.gfw_tcl_version):
            raise ValueError(f"invalid GFW dataset version: {settings.gfw_tcl_version!r}")
        self._settings = settings
        self._cache = cache
        self._dataset = settings.gfw_tcl_dataset
        self._version = settings.gfw_tcl_version
        self._http = http or SourceHttpClient(
            SourceHttpConfig(
                source="gfw",
                base_url=settings.gfw_api_base_url.rstrip("/"),
                rate_limit=settings.gfw_rate_limit_per_min,
                headers={
                    "x-api-key": settings.gfw_api_key,
                    "Origin": settings.gfw_api_origin,
                    "Accept": "application/json",
                },
            )
        )

    def require_credentials(self) -> None:
        """Raise the deferred credential failure, called on a cache miss."""
        if self._missing_credentials is not None:
            raise self._missing_credentials

    async def close(self) -> None:
        await self._http.close()

    def loss_sql(self, start_year: int, end_year: int) -> str:
        return (
            "SELECT umd_tree_cover_loss__year, SUM(area__ha) AS loss_ha "
            "FROM results "
            f"WHERE umd_tree_cover_loss__year >= {int(start_year)} "
            f"AND umd_tree_cover_loss__year <= {int(end_year)} "
            "GROUP BY umd_tree_cover_loss__year "
            "ORDER BY umd_tree_cover_loss__year"
        )

    async def tree_cover_loss(
        self,
        geometry: dict[str, Any],
        *,
        start_year: int = 2001,
        end_year: int | None = None,
        refresh: bool = False,
    ) -> TreeCoverLossResult:
        """Annual tree cover loss (hectares) inside a GeoJSON polygon."""
        if end_year is None:
            end_year = datetime.now(tz=UTC).year - 1
        if start_year > end_year:
            raise ValueError(f"start_year {start_year} is after end_year {end_year}")

        geometry_hash_value = geometry_hash(geometry)
        date_window = f"{start_year}-{end_year}"

        if not refresh:
            cached = await self._cache.get("gfw", geometry_hash_value, date_window)
            if cached is not None:
                return TreeCoverLossResult.model_validate(cached.payload).model_copy(update={"cached": True})

        self.require_credentials()
        sql = self.loss_sql(start_year, end_year)
        path = f"/dataset/{self._dataset}/{self._version}/query/json"
        response = await self._http.post(path, json={"sql": sql, "geometry": geometry})
        rows = _extract_rows(response)
        by_year: list[TreeCoverLossYear] = []
        for row in rows:
            parsed = _year_and_loss(row)
            if parsed is not None:
                year, loss = parsed
                by_year.append(TreeCoverLossYear(year=year, loss_ha=round(loss, 4)))
        by_year.sort(key=lambda item: item.year)
        result = TreeCoverLossResult(
            dataset=self._dataset,
            version=self._version,
            geometry_hash=geometry_hash_value,
            date_window=date_window,
            start_year=start_year,
            end_year=end_year,
            total_loss_ha=round(sum(item.loss_ha for item in by_year), 4),
            by_year=by_year,
            fetched_at=datetime.now(tz=UTC),
        )
        await self._cache.set(
            CacheEntry(
                source="gfw",
                geometry_hash=geometry_hash_value,
                date_window=date_window,
                request={"method": "POST", "path": path, "sql": sql},
                status_code=response.status_code,
                fetched_at=datetime.now(tz=UTC),
                payload=result.model_dump(mode="json"),
            )
        )
        return result

    async def tree_cover_loss_batch(
        self,
        features: Sequence[tuple[str, dict[str, Any]]],
        *,
        start_year: int = 2001,
        end_year: int | None = None,
        poll_interval: float = 2.0,
        max_wait_seconds: float = 300.0,
        refresh: bool = False,
    ) -> BatchLossResult:
        """Run the same loss query for a large list of features via the async batch job API."""
        if end_year is None:
            end_year = datetime.now(tz=UTC).year - 1
        feature_collection = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"fid": fid}, "geometry": geometry}
                for fid, geometry in features
            ],
        }
        geometry_hash_value = geometry_hash(feature_collection)
        date_window = f"{start_year}-{end_year}"

        if not refresh:
            cached = await self._cache.get("gfw", geometry_hash_value, date_window)
            if cached is not None:
                return BatchLossResult.model_validate(cached.payload).model_copy(update={"cached": True})

        self.require_credentials()
        sql = self.loss_sql(start_year, end_year)
        path = f"/dataset/{self._dataset}/{self._version}/query/batch"
        response = await self._http.post(
            path, json={"sql": sql, "feature_collection": feature_collection, "id_field": "fid"}
        )
        body = _parse_json_body("gfw", response.text)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict) or "job_id" not in data:
            raise SourceResponseError("gfw", "batch endpoint did not return a job_id")
        job = BatchJobStatus.model_validate(data)
        job = await self._poll_job(job.job_id, poll_interval=poll_interval, max_wait_seconds=max_wait_seconds)

        rows: list[dict[str, Any]] = []
        if job.download_link:
            download = await self._http.get(job.download_link)
            rows = _extract_download_rows(download)

        result = BatchLossResult(
            job_id=job.job_id,
            status=job.status,
            rows=rows,
            failed_geometries_link=job.failed_geometries_link,
            fetched_at=datetime.now(tz=UTC),
        )
        await self._cache.set(
            CacheEntry(
                source="gfw",
                geometry_hash=geometry_hash_value,
                date_window=date_window,
                request={"method": "POST", "path": path, "sql": sql, "features": len(features)},
                status_code=response.status_code,
                fetched_at=datetime.now(tz=UTC),
                payload=result.model_dump(mode="json"),
            )
        )
        return result

    async def _poll_job(
        self, job_id: str, *, poll_interval: float, max_wait_seconds: float
    ) -> BatchJobStatus:
        deadline = time.monotonic() + max_wait_seconds
        while True:
            response = await self._http.get(f"/job/{job_id}")
            body = _parse_json_body("gfw", response.text)
            data = body.get("data", body) if isinstance(body, dict) else body
            status = BatchJobStatus.model_validate(data)
            if status.status in _JOB_TERMINAL_STATUSES:
                if status.status in {"failed", "error"}:
                    raise SourceUnavailable(
                        "gfw",
                        f"batch job {job_id} ended with status {status.status}: "
                        f"{status.message or 'no message'}",
                    )
                return status
            if time.monotonic() >= deadline:
                raise SourceUnavailable(
                    "gfw",
                    f"batch job {job_id} did not finish within {max_wait_seconds:.0f}s "
                    f"(last status {status.status})",
                )
            await asyncio.sleep(poll_interval)
