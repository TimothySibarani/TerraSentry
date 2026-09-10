"""Typed failures for the external-source and cache layer."""

from __future__ import annotations


class IntegrationError(Exception):
    """Base class for terrasentry-integrations failures."""


class MissingCredentialError(IntegrationError):
    """A required API key or URL is not configured."""

    def __init__(self, source: str, variable: str) -> None:
        super().__init__(f"{source} requires {variable}; set it in .env (see docs/setup/data-sources.md).")
        self.source = source
        self.variable = variable


class SourceError(IntegrationError):
    """Base class for failures while talking to an external data source."""

    def __init__(self, source: str, message: str) -> None:
        super().__init__(f"[{source}] {message}")
        self.source = source


class SourceAuthError(SourceError):
    """The source rejected our credentials (HTTP 401/403)."""


class SourceRateLimited(SourceError):
    """The source returned HTTP 429; retry after ``retry_after`` seconds when known."""

    def __init__(self, source: str, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(source, message)
        self.retry_after = retry_after


class SourceUnavailable(SourceError):
    """The source returned a retryable 5xx error."""


class SourceResponseError(SourceError):
    """The source returned a response we could not interpret (not retryable)."""


class CacheMissError(IntegrationError):
    """An offline cache lookup failed; no external call was attempted."""

    def __init__(self, source: str, geometry_hash: str, date_window: str) -> None:
        super().__init__(
            f"cache miss for {source} geometry={geometry_hash[:12]} window={date_window} "
            "(offline mode: warm the cache or drop --offline)"
        )
        self.source = source
        self.geometry_hash = geometry_hash
        self.date_window = date_window
