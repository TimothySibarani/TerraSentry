import json
from typing import Any

import httpx
import pytest
import respx
from terrasentry_integrations.cache import MemoryCache
from terrasentry_integrations.errors import MissingCredentialError
from terrasentry_integrations.settings import IntegrationSettings
from terrasentry_integrations.sources.gfw import GfwClient

BASE = "https://data-api.globalforestwatch.org"
QUERY_URL = f"{BASE}/dataset/umd_tree_cover_loss/v1.13/query/json"
BATCH_URL = f"{BASE}/dataset/umd_tree_cover_loss/v1.13/query/batch"
JOB_URL = f"{BASE}/job/job-123"
DOWNLOAD_URL = "https://files.globalforestwatch.org/results.json"

POLYGON: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[101.0, 0.0], [101.01, 0.0], [101.01, 0.01], [101.0, 0.01], [101.0, 0.0]]],
}

QUERY_ROWS = {
    "status": "success",
    "data": [
        {"umd_tree_cover_loss__year": 2021, "loss_ha": 4.5},
        {"umd_tree_cover_loss__year": 2019, "loss_ha": 2.0},
        {"umd_tree_cover_loss__year": 2020, "loss_ha": 1.5},
    ],
}


def _settings() -> IntegrationSettings:
    return IntegrationSettings(gfw_api_key="test-key", gfw_rate_limit_per_min=1000)


async def test_tree_cover_loss_parses_and_caches() -> None:
    cache = MemoryCache()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(QUERY_URL).mock(return_value=httpx.Response(200, json=QUERY_ROWS))
        client = GfwClient(_settings(), cache=cache)
        try:
            result = await client.tree_cover_loss(POLYGON, start_year=2019, end_year=2021)
            assert result.total_loss_ha == 8.0
            assert [item.year for item in result.by_year] == [2019, 2020, 2021]
            assert result.cached is False

            body = json.loads(route.calls[0].request.content)
            assert "FROM results" in body["sql"]
            assert body["geometry"] == POLYGON

            cached_result = await client.tree_cover_loss(POLYGON, start_year=2019, end_year=2021)
            assert cached_result.cached is True
            assert cached_result.total_loss_ha == 8.0
        finally:
            await client.close()
    assert route.call_count == 1
    assert cache.stats().writes == 1


async def test_tree_cover_loss_batch_polls_and_downloads() -> None:
    cache = MemoryCache()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(BATCH_URL).mock(
            return_value=httpx.Response(
                202,
                json={
                    "status": "success",
                    "data": {"job_id": "job-123", "job_link": JOB_URL, "status": "pending"},
                },
            )
        )
        mock.get(JOB_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "job_id": "job-123",
                        "status": "success",
                        "download_link": DOWNLOAD_URL,
                    },
                },
            )
        )
        mock.get(DOWNLOAD_URL).mock(
            return_value=httpx.Response(200, json=[{"fid": "PLY-001", "loss_ha": 5.5}])
        )
        client = GfwClient(_settings(), cache=cache)
        try:
            result = await client.tree_cover_loss_batch([("PLY-001", POLYGON)], poll_interval=0.01)
        finally:
            await client.close()
    assert result.status == "success"
    assert result.rows == [{"fid": "PLY-001", "loss_ha": 5.5}]
    assert cache.stats().writes == 1


async def test_constructs_without_a_key_and_fails_on_cache_miss() -> None:
    """The API builds source clients in its lifespan; credentials are checked at fetch time."""
    client = GfwClient(IntegrationSettings(gfw_api_key=""), cache=MemoryCache())
    try:
        with pytest.raises(MissingCredentialError):
            await client.tree_cover_loss(POLYGON, start_year=2021, end_year=2022)
    finally:
        await client.close()
