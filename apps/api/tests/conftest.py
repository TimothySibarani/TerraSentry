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
        from terrasentry_integrations.sources.gfw_layers import LAYER_DEFINITIONS

        for name, (dataset, version, _, _) in LAYER_DEFINITIONS.items():
            router.post(
                f"https://data-api.globalforestwatch.org/dataset/{dataset}/{version}/query/json"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "status": "success",
                        "data": [{"overlap_ha": 0}] if name in {"peatlands", "forest_baseline"} else [],
                    },
                )
            )
        yield router


@pytest.fixture
def signal_router() -> Iterator[respx.MockRouter]:
    """Like ``source_router`` but every polygon fully overlaps a protected area (a screening signal)."""
    import json

    from terrasentry_integrations.sources.gfw_layers import LAYER_DEFINITIONS

    def protected_overlap(request: httpx.Request) -> httpx.Response:
        geometry = json.loads(request.content)["geometry"]
        row = {"gfw_fid": 1, "name": "Test reserve", "gfw_geojson": json.dumps(geometry)}
        return httpx.Response(200, json={"status": "success", "data": [row]})

    with respx.mock(assert_all_called=False) as router:
        router.post(api_helpers.GFW_URL).mock(
            return_value=httpx.Response(200, json={"status": "success", "data": []})
        )
        router.get(url__regex=api_helpers.FIRMS_REGEX).mock(return_value=httpx.Response(200, text=""))
        for name, (dataset, version, _, _) in LAYER_DEFINITIONS.items():
            route = router.post(
                f"https://data-api.globalforestwatch.org/dataset/{dataset}/{version}/query/json"
            )
            if name == "protected_areas":
                route.mock(side_effect=protected_overlap)
            else:
                data = [{"overlap_ha": 0}] if name in {"peatlands", "forest_baseline"} else []
                route.mock(return_value=httpx.Response(200, json={"status": "success", "data": data}))
        yield router


@pytest.fixture
def app(tmp_path: Path, datasets: SeedDatasets) -> FastAPI:
    return create_app(services_factory=api_helpers.test_services_factory(tmp_path, datasets))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
