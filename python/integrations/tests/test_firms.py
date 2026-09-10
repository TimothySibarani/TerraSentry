from datetime import date
from typing import Any

import httpx
import respx
from terrasentry_integrations.cache import MemoryCache
from terrasentry_integrations.settings import IntegrationSettings
from terrasentry_integrations.sources.firms import FirmsClient, parse_detections

BASE = "https://firms.modaps.eosdis.nasa.gov/api"
FIRST_CHUNK = f"{BASE}/area/csv/TESTKEY/VIIRS_SNPP_NRT/-0.0100,-0.0100,0.0100,0.0100/5/2026-01-01"
SECOND_CHUNK = f"{BASE}/area/csv/TESTKEY/VIIRS_SNPP_NRT/-0.0100,-0.0100,0.0100,0.0100/2/2026-01-06"

POLYGON: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[-0.01, -0.01], [0.01, -0.01], [0.01, 0.01], [-0.01, 0.01], [-0.01, -0.01]]],
}

CSV_TEXT = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
    "confidence,version,bright_ti5,frp,daynight\n"
    "0.0,0.0,330.1,1.0,1.0,2026-01-02,1010,VIIRS,NOAA-20,n,2.0NRT,295.0,12.5,D\n"
    "0.005,0.005,331.0,1.0,1.0,2026-01-02,1010,VIIRS,NOAA-20,n,2.0NRT,296.0,13.0,D\n"
    "0.0,0.0,330.1,1.0,1.0,2026-01-02,1010,VIIRS,NOAA-20,n,2.0NRT,295.0,12.5,D\n"
    "0.5,0.5,320.0,1.0,1.0,2026-01-03,1020,VIIRS,NOAA-20,n,2.0NRT,292.0,8.0,D\n"
)

MODIS_CSV_TEXT = (
    "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,"
    "confidence,version,bright_t31,frp,type\n"
    "0.0,0.0,330.1,1.0,1.0,2026-01-02,1010,Aqua,MODIS,80,6.1NRT,295.0,12.5,0\n"
)


def _settings() -> IntegrationSettings:
    return IntegrationSettings(firms_map_key="TESTKEY", firms_rate_limit_per_10min=1000)


def test_parse_detections_handles_empty_and_no_data() -> None:
    assert parse_detections("") == []
    assert parse_detections("No data") == []


def test_parse_detections_supports_both_viirs_and_modis_columns() -> None:
    viirs = parse_detections(CSV_TEXT)[0]
    assert viirs.brightness == 330.1
    assert viirs.bright_t31 == 295.0
    modis = parse_detections(MODIS_CSV_TEXT)[0]
    assert modis.brightness == 330.1
    assert modis.bright_t31 == 295.0


async def test_hotspots_chunks_window_and_filters_polygon() -> None:
    cache = MemoryCache()
    with respx.mock(assert_all_called=False) as mock:
        first = mock.get(FIRST_CHUNK).mock(return_value=httpx.Response(200, text=CSV_TEXT))
        second = mock.get(SECOND_CHUNK).mock(return_value=httpx.Response(200, text=""))
        client = FirmsClient(_settings(), cache=cache)
        try:
            result = await client.hotspots_in_polygon(POLYGON, days=7, end_date=date(2026, 1, 7))
            assert result.detection_count == 2
            assert result.total_frp == 25.5
            assert result.window_start == date(2026, 1, 1)
            assert result.window_end == date(2026, 1, 7)
            assert {item.latitude for item in result.detections} == {0.0, 0.005}

            cached = await client.hotspots_in_polygon(POLYGON, days=7, end_date=date(2026, 1, 7))
            assert cached.cached is True
        finally:
            await client.close()
    assert first.call_count == 1
    assert second.call_count == 1
    assert cache.stats().writes == 1
