"""Shared async HTTP plumbing: per-source rate limiting, retries, typed failures."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from terrasentry_integrations.errors import (
    SourceAuthError,
    SourceRateLimited,
    SourceResponseError,
    SourceUnavailable,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceHttpConfig:
    source: str
    base_url: str
    rate_limit: int = 60
    time_period: float = 60.0
    max_attempts: int = 5
    max_connections: int = 10
    timeout_seconds: float = 30.0
    wait_max: float = 30.0
    wait_jitter: float = 1.0
    headers: Mapping[str, str] = field(default_factory=dict)


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header (seconds form only; HTTP dates fall back to backoff)."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class SourceHttpClient:
    """Thin wrapper over httpx.AsyncClient adding rate limits, retries, and typed errors.

    URLs may contain secrets (the FIRMS MAP_KEY lives in the path), so logs never
    include request URLs.
    """

    def __init__(self, config: SourceHttpConfig) -> None:
        self._config = config
        self._limiter = AsyncLimiter(max(config.rate_limit, 1), config.time_period)
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers=dict(config.headers),
            timeout=httpx.Timeout(config.timeout_seconds, connect=min(10.0, config.timeout_seconds)),
            limits=httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_connections,
            ),
            follow_redirects=True,
        )
        self._wait = wait_exponential_jitter(initial=1.0, jitter=config.wait_jitter, max=config.wait_max)

    @property
    def source(self) -> str:
        return self._config.source

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._config.max_attempts),
            wait=self._wait_for,
            retry=retry_if_exception_type(
                (
                    httpx.TimeoutException,
                    httpx.TransportError,
                    SourceRateLimited,
                    SourceUnavailable,
                )
            ),
            reraise=True,
        ):
            with attempt:
                return await self._attempt(method, url, **kwargs)
        raise SourceUnavailable(self.source, "retry loop produced no result")  # pragma: no cover

    async def close(self) -> None:
        await self._client.aclose()

    def _wait_for(self, retry_state: RetryCallState) -> float:
        outcome = retry_state.outcome
        if outcome is not None:
            exception = outcome.exception()
            if isinstance(exception, SourceRateLimited) and exception.retry_after is not None:
                return exception.retry_after
        return float(self._wait(retry_state))

    async def _attempt(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async with self._limiter:
            response = await self._client.request(method, url, **kwargs)
        status = response.status_code
        if status in (401, 403):
            raise SourceAuthError(self.source, f"authentication failed with HTTP {status}")
        if status == 429:
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            raise SourceRateLimited(self.source, "rate limited (HTTP 429)", retry_after=retry_after)
        if status >= 500:
            raise SourceUnavailable(self.source, f"upstream error HTTP {status}")
        if status >= 400:
            raise SourceResponseError(
                self.source, f"request failed with HTTP {status}: {response.text[:200]}"
            )
        logger.debug("[%s] %s -> %s", self.source, method, status)
        return response
