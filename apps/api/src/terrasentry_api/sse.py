"""SSE wire encoding and the production response configuration.

``sse-starlette`` writes the frames; this module owns the two things every
stream must agree on: JSON-encoding the structured event payloads and the
response hardening (a send timeout so a stalled client cannot pin a task, and
no-store/nosniff headers).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from sse_starlette.sse import EventSourceResponse

from terrasentry_api.runner import RunManager

SSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}
SSE_SEND_TIMEOUT_SECONDS = 60.0


async def encode_events(manager: RunManager, run_id: str) -> AsyncIterator[dict[str, str]]:
    """Turn structured run events into ``event``/``data`` SSE frames."""
    async for event in manager.stream(run_id):
        yield {
            "event": str(event["event"]),
            "data": json.dumps(event["data"], ensure_ascii=False),
        }


def event_source_response(manager: RunManager, run_id: str, *, ping: int) -> EventSourceResponse:
    """The hardened ``EventSourceResponse`` shared by the run and batch streams."""
    return EventSourceResponse(
        encode_events(manager, run_id),
        ping=ping,
        send_timeout=SSE_SEND_TIMEOUT_SECONDS,
        headers=dict(SSE_HEADERS),
    )


__all__ = [
    "SSE_HEADERS",
    "SSE_SEND_TIMEOUT_SECONDS",
    "encode_events",
    "event_source_response",
]
