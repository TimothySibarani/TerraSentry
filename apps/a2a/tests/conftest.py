"""Fixtures: a mocked TerraSentry API and a virtual clock so polling never really sleeps."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from a2a_helpers import API, SUPPLIERS, VirtualClock, settings
from terrasentry_a2a.client import TerraSentryClient
from terrasentry_a2a.skills import Skills


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=False) as router:
        router.get("/suppliers").mock(return_value=httpx.Response(200, json=SUPPLIERS))
        yield router


@pytest.fixture
def clock() -> VirtualClock:
    return VirtualClock()


@pytest.fixture
def skills(api: respx.MockRouter, clock: VirtualClock) -> Skills:
    return Skills(TerraSentryClient(API), settings(), sleep=clock.sleep, clock=clock)
