"""API test fixtures: deterministic source mocks and a lifespan-managed client."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import api_helpers
import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from terrasentry_api.main import create_app
from terrasentry_core.tools.datasets import SeedDatasets


@pytest.fixture
def datasets() -> SeedDatasets:
    return api_helpers.build_datasets()


@pytest.fixture
def source_router() -> Iterator[respx.MockRouter]:
    """Deterministic, zero-loss GFW and empty FIRMS responses for every polygon."""
    with respx.mock(assert_all_called=False) as router:
        router.post(api_helpers.GFW_URL).mock(
            return_value=httpx.Response(200, json={"status": "success", "data": []})
        )
        router.get(url__regex=api_helpers.FIRMS_REGEX).mock(return_value=httpx.Response(200, text=""))
        yield router


@pytest.fixture
def app(tmp_path: Path, datasets: SeedDatasets) -> FastAPI:
    return create_app(services_factory=api_helpers.test_services_factory(tmp_path, datasets))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
