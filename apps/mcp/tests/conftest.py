"""Fixtures: a mocked TerraSentry API and an in-process MCP client that can answer elicitation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import respx
from mcp.client import Client
from mcp_helpers import API, VirtualClock
from mcp_types import ElicitResult
from terrasentry_mcp.client import TerraSentryApi
from terrasentry_mcp.server import build_server
from terrasentry_mcp.settings import McpSettings


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=False) as router:
        yield router


@pytest.fixture
def clock() -> VirtualClock:
    return VirtualClock()


@pytest.fixture
def connect(api: respx.MockRouter, clock: VirtualClock) -> Callable[..., Any]:
    """``async with connect(answer=...) as client``; ``answer`` is the user's elicitation reply."""

    @asynccontextmanager
    async def open_client(answer: str | None = None) -> AsyncIterator[Client]:
        server = build_server(
            TerraSentryApi(API),
            McpSettings(cockpit_base_url="https://cockpit.test", mcp_wait_seconds=5.0),
            sleep=clock.sleep,
            clock=clock,
        )
        prompts: list[str] = []

        async def respond(context: Any, params: Any) -> ElicitResult:
            prompts.append(params.message)
            assert answer is not None
            return ElicitResult(action="accept", content={"confirm": answer == "yes"})  # type: ignore[arg-type]

        callback = respond if answer is not None else None
        async with Client(server, elicitation_callback=callback) as client:
            client.prompts = prompts  # type: ignore[attr-defined]
            yield client

    return open_client
