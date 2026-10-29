"""Context queries must clip features, preserve holes, and never cache failures."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from shapely.geometry import shape
from terrasentry_integrations.cache import CacheEntry, MemoryCache, geometry_hash
from terrasentry_integrations.geometry import geodesic_area_ha
from terrasentry_integrations.settings import IntegrationSettings
from terrasentry_integrations.sources.gfw import GfwClient
from terrasentry_integrations.sources.gfw_layers import LAYER_DEFINITIONS, ContextLayer

PLOT = {"type": "Polygon", "coordinates": [[[101, 0], [101.01, 0], [101.01, 0.01], [101, 0.01], [101, 0]]]}
OUTER = {"type": "Polygon", "coordinates": [[[100, -1], [102, -1], [102, 1], [100, 1], [100, -1]]]}


def url(name: str) -> str:
    dataset, version, _, _ = LAYER_DEFINITIONS[name]
    return f"https://data-api.globalforestwatch.org/dataset/{dataset}/{version}/query/json"


def register(router: respx.MockRouter) -> None:
    for name in LAYER_DEFINITIONS:
        router.post(url(name)).mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": [{"overlap_ha": 0}] if name in {"peatlands", "forest_baseline"} else [],
                },
            )
        )


async def test_clip_union_boundary_and_cache_replay() -> None:
    cache = MemoryCache()
    gfw = GfwClient(IntegrationSettings(gfw_api_key="test", gfw_rate_limit_per_min=10000), cache=cache)
    with respx.mock(assert_all_called=False) as router:
        register(router)
        edge = {
            "type": "Polygon",
            "coordinates": [[[101.01, 0], [101.02, 0], [101.02, 0.01], [101.01, 0.01], [101.01, 0]]],
        }
        route = router.post(url("protected_areas")).mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": [
                        {"gfw_fid": 1, "name": "Named reserve", "gfw_geojson": json.dumps(OUTER)},
                        {"gfw_fid": 2, "name": "Duplicate footprint", "gfw_geojson": OUTER},
                        {"gfw_fid": 3, "name": "Boundary only", "gfw_geojson": edge},
                    ],
                },
            )
        )
        try:
            fresh = await gfw.context_layers(PLOT, country="ID")
            layer = fresh.layers[0]
            assert layer.status == "success"
            assert layer.overlap_ha == pytest.approx(geodesic_area_ha(shape(PLOT)))
            assert len(layer.features) == 2
            assert layer.features[0].properties["name"] == "Named reserve"
            assert sum(feature.overlap_ha for feature in layer.features) > layer.overlap_ha
            cache.offline = True
            replay = await gfw.context_layers(PLOT, country="ID")
            assert replay.layers[0].cached
            assert replay.model_dump(exclude={"layers": {"__all__": {"cached"}}}) == fresh.model_dump(
                exclude={"layers": {"__all__": {"cached"}}}
            )
            assert route.call_count == 1
        finally:
            await gfw.close()


async def test_failed_layer_retries_while_successful_siblings_stay_cached() -> None:
    cache = MemoryCache()
    gfw = GfwClient(IntegrationSettings(gfw_api_key="test", gfw_rate_limit_per_min=10000), cache=cache)
    with respx.mock(assert_all_called=False) as router:
        register(router)
        failed = router.post(url("moratorium")).mock(
            return_value=httpx.Response(200, json={"status": "success", "data": [{"gfw_fid": 1}]})
        )
        protected = router.routes[0]
        try:
            first = await gfw.context_layers(PLOT, country="ID")
            assert not first.complete and first.layers[1].status == "unavailable"
            second = await gfw.context_layers(PLOT, country="ID")
            assert not second.complete
            assert failed.call_count == 2 and protected.call_count == 1
            other_country = await gfw.context_layers(PLOT, country="BR")
            assert other_country.layers[1].status == "not_applicable"
        finally:
            await gfw.close()


async def test_pagination_ceiling_is_an_explicit_gap() -> None:
    gfw = GfwClient(
        IntegrationSettings(gfw_api_key="test", gfw_rate_limit_per_min=10000), cache=MemoryCache()
    )
    with respx.mock(assert_all_called=False) as router:
        register(router)
        route = router.post(url("protected_areas")).mock(
            return_value=httpx.Response(
                200,
                json={"status": "success", "data": [{"gfw_fid": i, "gfw_geojson": PLOT} for i in range(100)]},
            )
        )
        try:
            result = await gfw.context_layers(PLOT, country="ID")
            assert result.layers[0].status == "unavailable"
            assert "1000" in (result.layers[0].error or "")
            assert route.call_count == 11
        finally:
            await gfw.close()


@pytest.mark.parametrize("raw", [False, True, "", "1", [], {}, -1, float("inf"), float("nan"), 10**400])
async def test_malformed_raster_is_unavailable_and_not_cached(raw: Any) -> None:
    cache = MemoryCache()
    gfw = GfwClient(IntegrationSettings(gfw_api_key="test", gfw_rate_limit_per_min=10000), cache=cache)
    with respx.mock(assert_all_called=False) as router:
        register(router)
        route = router.post(url("peatlands")).mock(
            return_value=httpx.Response(
                200, text=json.dumps({"status": "success", "data": [{"overlap_ha": raw}]})
            )
        )
        try:
            for _ in range(2):
                result = await gfw.context_layers(PLOT, country="ID")
                assert result.layers[5].status == "unavailable" and not result.layers[5].cached
                assert not result.complete
            assert route.call_count == 2
            assert cache.stats().writes == 6
        finally:
            await gfw.close()


@pytest.mark.parametrize("raw", [None, 0, 0.0, 2.5])
async def test_valid_raster_null_zero_and_area_are_cached(raw: float | None) -> None:
    gfw = GfwClient(
        IntegrationSettings(gfw_api_key="test", gfw_rate_limit_per_min=10000), cache=MemoryCache()
    )
    with respx.mock(assert_all_called=False) as router:
        register(router)
        route = router.post(url("peatlands")).mock(
            return_value=httpx.Response(200, json={"status": "success", "data": [{"overlap_ha": raw}]})
        )
        try:
            result = await gfw.context_layers(PLOT, country="ID")
            warm = await gfw.context_layers(PLOT, country="ID")
            assert result.layers[5].status == "success" and result.layers[5].overlap_ha == (raw or 0)
            assert warm.layers[5].cached and route.call_count == 1
        finally:
            await gfw.close()


async def test_old_raster_revision_and_missing_aggregate_cannot_supply_zero() -> None:
    cache = MemoryCache()
    old_layer = ContextLayer(
        name="peatlands",
        dataset="gfw_peatlands",
        version="v20230315",
        query_revision="clip-1",
        geometry_hash=geometry_hash(PLOT),
        status="success",
    )
    await cache.set(
        CacheEntry(
            source="gfw_layers",
            geometry_hash=geometry_hash(PLOT),
            date_window="gfw_peatlands:v20230315:clip-1",
            status_code=200,
            fetched_at=datetime(2026, 10, 2, tzinfo=UTC),
            payload=old_layer.model_dump(mode="json"),
        )
    )
    gfw = GfwClient(IntegrationSettings(gfw_api_key="test", gfw_rate_limit_per_min=10000), cache=cache)
    with respx.mock(assert_all_called=False) as router:
        register(router)
        route = router.post(url("peatlands")).mock(return_value=httpx.Response(200, json={"data": [{}]}))
        try:
            result = await gfw.context_layers(PLOT, country="ID")
            assert result.layers[5].status == "unavailable" and route.call_count == 1
            assert "missing raster" in (result.layers[5].error or "")
        finally:
            await gfw.close()


async def test_dateline_source_features_and_legacy_queries_are_unavailable() -> None:
    dateline = {
        "type": "Polygon",
        "coordinates": [[[179.999, 0], [-179.999, 0], [-179.999, 0.01], [179.999, 0.01], [179.999, 0]]],
    }
    gfw = GfwClient(
        IntegrationSettings(gfw_api_key="test", gfw_rate_limit_per_min=10000), cache=MemoryCache()
    )
    with respx.mock(assert_all_called=False) as router:
        register(router)
        route = router.post(url("protected_areas")).mock(
            return_value=httpx.Response(200, json={"data": [{"gfw_fid": 1, "gfw_geojson": dateline}]})
        )
        try:
            result = await gfw.context_layers(PLOT, country="ID")
            assert result.layers[0].status == "unavailable"
            assert "antimeridian" in (result.layers[0].error or "")
            before = len(router.calls)
            legacy = await gfw.context_layers(dateline, country="ID")
            assert all(layer.status == "unavailable" for layer in legacy.layers)
            assert len(router.calls) == before and route.call_count == 1
        finally:
            await gfw.close()


async def test_raster_sum_above_plot_area_is_capped_and_raw_kept() -> None:
    plot_ha = geodesic_area_ha(shape(PLOT))
    gfw = GfwClient(
        IntegrationSettings(gfw_api_key="test", gfw_rate_limit_per_min=10000), cache=MemoryCache()
    )
    with respx.mock(assert_all_called=False) as router:
        register(router)
        router.post(url("peatlands")).mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": [{"overlap_ha": plot_ha + 0.4}]}
            )
        )
        try:
            for _ in range(2):  # fresh, then from cache
                peat = (await gfw.context_layers(PLOT, country="ID")).layers[5]
                assert peat.overlap_ha == plot_ha
                assert peat.raw_overlap_ha == pytest.approx(plot_ha + 0.4)
        finally:
            await gfw.close()
