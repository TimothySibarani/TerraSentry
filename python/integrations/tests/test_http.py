import httpx
import pytest
import respx
from terrasentry_integrations.errors import SourceAuthError, SourceResponseError, SourceUnavailable
from terrasentry_integrations.sources.http import (
    SourceHttpClient,
    SourceHttpConfig,
    parse_retry_after,
)


def _client() -> SourceHttpClient:
    config = SourceHttpConfig(
        source="test",
        base_url="https://example.test",
        rate_limit=1000,
        time_period=1.0,
        max_attempts=3,
        wait_max=0.05,
        wait_jitter=0.01,
    )
    return SourceHttpClient(config)


def test_parse_retry_after() -> None:
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after(" 0 ") == 0.0
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None
    assert parse_retry_after(None) is None


async def test_retries_429_then_succeeds() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://example.test/data").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "0"}),
                httpx.Response(200, text="ok"),
            ]
        )
        client = _client()
        try:
            response = await client.get("/data")
        finally:
            await client.close()
    assert response.status_code == 200
    assert route.call_count == 2


async def test_auth_error_is_not_retried() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://example.test/data").mock(return_value=httpx.Response(401))
        client = _client()
        try:
            with pytest.raises(SourceAuthError):
                await client.get("/data")
        finally:
            await client.close()
    assert route.call_count == 1


async def test_server_error_exhausts_attempts() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://example.test/data").mock(return_value=httpx.Response(503))
        client = _client()
        try:
            with pytest.raises(SourceUnavailable):
                await client.get("/data")
        finally:
            await client.close()
    assert route.call_count == 3


async def test_client_error_is_not_retried() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://example.test/data").mock(return_value=httpx.Response(400))
        client = _client()
        try:
            with pytest.raises(SourceResponseError):
                await client.get("/data")
        finally:
            await client.close()
    assert route.call_count == 1
