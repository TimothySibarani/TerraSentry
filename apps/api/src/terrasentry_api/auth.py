"""Optional shared-token guard for write endpoints.

``API_TOKEN`` empty keeps the API open, which is only acceptable on a local or
otherwise trusted network; ``/health`` reports ``auth_enabled`` so the cockpit
can warn. When set, every non-read request needs ``Authorization: Bearer``.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from terrasentry_api.services import AppServices, get_services

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def require_write_token(
    request: Request,
    services: Annotated[AppServices, Depends(get_services)],
) -> None:
    expected = services.settings.api_token
    if not expected or request.method in _READ_METHODS:
        return
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


__all__ = ["require_write_token"]
