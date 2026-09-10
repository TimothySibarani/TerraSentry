import re
from typing import Any

import httpx
import pytest
import respx
from terrasentry_core.reference.pipeline import run_reference_pipeline
from terrasentry_core.seed.schemas import SeedPolygon
from terrasentry_integrations.cache import MemoryCache
from terrasentry_integrations.errors import CacheMissError
from terrasentry_integrations.settings import IntegrationSettings
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient

GFW_URL = "https://data-api.globalforestwatch.org/dataset/umd_tree_cover_loss/v1.13/query/json"
FIRMS_REGEX = (
    r"https://firms\.modaps\.eosdis\.nasa\.gov/api/area/csv/"
    r"TESTKEY/VIIRS_SNPP_NRT/.*"
)

POLYGON: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[-0.01, -0.01], [0.01, -0.01], [0.01, 0.01], [-0.01, 0.01], [-0.01, -0.01]]],
}

SEED_POLYGON = SeedPolygon(
    id="PLY-TEST",
    label="Test polygon",
    region="Test region",
    province="Test province",
    archetype="compliant",
    is_demo=True,
    area_ha=100.0,
    centroid_lat=0.0,
    centroid_lon=0.0,
    geometry=POLYGON,
)

CSV_TEXT = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
    "confidence,version,bright_ti5,frp,daynight\n"
    "0.0,0.0,330.1,1.0,1.0,2026-01-02,1010,VIIRS,NOAA-20,n,2.0NRT,295.0,12.5,D\n"
)


def _settings() -> IntegrationSettings:
    return IntegrationSettings(
        gfw_api_key="test-key",
        gfw_rate_limit_per_min=1000,
        firms_map_key="TESTKEY",
        firms_rate_limit_per_10min=1000,
    )


async def test_reference_pipeline_live_then_offline_cache() -> None:
    cache = MemoryCache()
    with respx.mock(assert_all_called=False) as mock:
        gfw_route = mock.post(GFW_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": [{"umd_tree_cover_loss__year": 2020, "loss_ha": 3.0}],
                },
            )
        )
        firms_route = mock.get(url__regex=re.compile(FIRMS_REGEX)).mock(
            return_value=httpx.Response(200, text=CSV_TEXT)
        )
        gfw = GfwClient(_settings(), cache=cache)
        firms = FirmsClient(_settings(), cache=cache)
        try:
            live_run = await run_reference_pipeline(
                [SEED_POLYGON], gfw=gfw, firms=firms, cache=cache, window_days=5, years=2
            )
            report = live_run.reports[0]
            assert report.errors == []
            assert report.loss is not None
            assert report.loss.total_loss_ha == 3.0
            assert report.hotspots is not None
            assert report.hotspots.detection_count == 1

            cache.offline = True
            offline_run = await run_reference_pipeline(
                [SEED_POLYGON],
                gfw=gfw,
                firms=firms,
                cache=cache,
                window_days=5,
                years=2,
                offline=True,
            )
            offline_report = offline_run.reports[0]
            assert offline_report.loss is not None
            assert offline_report.loss.cached is True
            assert offline_report.hotspots is not None
            assert offline_report.hotspots.cached is True
        finally:
            await gfw.close()
            await firms.close()
    assert gfw_route.call_count == 1
    assert firms_route.call_count == 1


async def test_reference_pipeline_offline_cold_cache_fails() -> None:
    cache = MemoryCache(offline=True)
    gfw = GfwClient(_settings(), cache=cache)
    firms = FirmsClient(_settings(), cache=cache)
    try:
        with pytest.raises(CacheMissError):
            await run_reference_pipeline([SEED_POLYGON], gfw=gfw, firms=firms, cache=cache, offline=True)
    finally:
        await gfw.close()
        await firms.close()
