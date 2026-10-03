"""Pinned context datasets, with local clipping of GFW's spatially filtered rows."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from shapely.errors import ShapelyError
from shapely.geometry import shape
from shapely.ops import unary_union

from terrasentry_integrations.cache import CacheBackend, CacheEntry, geometry_hash
from terrasentry_integrations.errors import IntegrationError, SourceResponseError
from terrasentry_integrations.geometry import crosses_antimeridian, geodesic_area_ha
from terrasentry_integrations.sources.http import SourceHttpClient

QUERY_REVISION = "clip-2"
# Fields verified against the public Data API; versions never silently follow latest.
LAYER_DEFINITIONS: dict[str, tuple[str, str, str, bool]] = {
    "protected_areas": (
        "wdpa_protected_areas",
        "v202512",
        "gfw_fid,site_id,site_pid,name,name_eng,desig,iucn_cat,gfw_geojson",
        False,
    ),
    "moratorium": ("idn_forest_moratorium", "v20200923", "gfw_fid,pippib_en,gfw_geojson", True),
    "oil_palm_concessions": (
        "gfw_oil_palm",
        "v2025",
        "gfw_fid,conc_type,conc_name,company,gfw_geojson",
        True,
    ),
    "wood_fiber_concessions": (
        "gfw_wood_fiber",
        "v2025",
        "gfw_fid,conc_type,conc_name,company,gfw_geojson",
        True,
    ),
    "logging_concessions": ("gfw_logging", "v202106", "gfw_fid,name,company,gfw_geojson", True),
    "peatlands": ("gfw_peatlands", "v20230315", "is__gfw_peatlands", True),
    "forest_baseline": ("jrc_global_forest_cover", "v2020.3", "is__jrc_global_forest_cover", False),
}


class LayerFeature(BaseModel):
    feature_id: str
    overlap_ha: float
    properties: dict[str, Any]
    geometry: dict[str, Any]


class ContextLayer(BaseModel):
    name: str
    dataset: str
    version: str
    query_revision: str = QUERY_REVISION
    geometry_hash: str
    status: Literal["success", "unavailable", "not_applicable"]
    overlap_ha: float = 0.0
    features: list[LayerFeature] = Field(default_factory=list)
    fetched_at: datetime | None = None
    cached: bool = False
    error: str | None = None


class ContextLayersResult(BaseModel):
    layers: list[ContextLayer] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return len(self.layers) == len(LAYER_DEFINITIONS) and all(
            layer.status != "unavailable" for layer in self.layers
        )


async def fetch_context_layer(
    *,
    name: str,
    geometry: dict[str, Any],
    country: str | None,
    http: SourceHttpClient,
    cache: CacheBackend,
    require_credentials: Callable[[], None],
    refresh: bool = False,
    release: str | None = None,
) -> ContextLayer:
    dataset, version, fields, indonesia_only = LAYER_DEFINITIONS[name]
    if release is not None:
        dataset, version = release.split("/", 1)
    geometry_digest = geometry_hash(geometry)
    base = ContextLayer(
        name=name, dataset=dataset, version=version, geometry_hash=geometry_digest, status="unavailable"
    )
    if indonesia_only and country != "ID":
        return base.model_copy(
            update={
                "status": "not_applicable" if country else "unavailable",
                "error": None if country else "production country missing",
            }
        )
    cache_window = f"{dataset}:{version}:{QUERY_REVISION}"
    try:
        plot = shape(geometry)
        if crosses_antimeridian(plot):
            raise SourceResponseError("gfw_layers", "query crosses the antimeridian; split polygons required")
        if not refresh:
            entry = await cache.get("gfw_layers", geometry_digest, cache_window)
            if entry is not None:
                return ContextLayer.model_validate(entry.payload).model_copy(update={"cached": True})
        require_credentials()
        path = f"/dataset/{dataset}/{version}/query/json"
        raster = name in {"peatlands", "forest_baseline"}
        rows: list[dict[str, Any]] = []
        response_bytes = 0
        for offset in range(0, 1001, 100):
            sql = (
                f"SELECT SUM(area__ha) AS overlap_ha FROM results WHERE {fields} = true"
                if raster
                else f"SELECT {fields} FROM data ORDER BY gfw_fid LIMIT 100 OFFSET {offset}"
            )
            response = await http.post(path, json={"sql": sql, "geometry": geometry})
            response_bytes += len(response.content)
            if response_bytes > 10 * 1024 * 1024:
                raise SourceResponseError("gfw_layers", "response exceeds 10 MiB; incomplete query")
            payload = response.json()
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, dict) or payload.get("status", "success") != "success":
                raise SourceResponseError("gfw_layers", "query did not return success")
            page = payload.get("data")
            if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                raise SourceResponseError("gfw_layers", "expected structured rows")
            rows.extend(page)
            if len(rows) > 1000:
                raise SourceResponseError("gfw_layers", "more than 1000 features; incomplete query")
            if raster or len(page) < 100:
                break
        timestamp = datetime.now(tz=UTC)
        if raster:
            if len(rows) != 1 or "overlap_ha" not in rows[0]:
                raise SourceResponseError("gfw_layers", "missing raster area aggregate")
            raw_area = rows[0]["overlap_ha"]
            if raw_area is not None and (isinstance(raw_area, bool) or not isinstance(raw_area, int | float)):
                raise SourceResponseError("gfw_layers", "invalid raster area type")
            area = 0.0 if raw_area is None else float(raw_area)
            if not math.isfinite(area) or area < 0:
                raise SourceResponseError("gfw_layers", "invalid raster area")
            result = base.model_copy(
                update={"status": "success", "overlap_ha": area, "fetched_at": timestamp}
            )
        else:
            clipped = []
            features: list[LayerFeature] = []
            for row in rows:
                raw_geometry = row.get("gfw_geojson")
                parsed_geometry = json.loads(raw_geometry) if isinstance(raw_geometry, str) else raw_geometry
                if not isinstance(parsed_geometry, dict) or row.get("gfw_fid") is None:
                    raise SourceResponseError("gfw_layers", "feature missing id or geometry")
                feature_geometry = shape(parsed_geometry)
                if not feature_geometry.is_valid or feature_geometry.is_empty:
                    raise SourceResponseError("gfw_layers", "invalid feature geometry")
                if crosses_antimeridian(feature_geometry):
                    raise SourceResponseError(
                        "gfw_layers", "feature crosses the antimeridian; cannot clip safely"
                    )
                overlap = feature_geometry.intersection(plot)
                area = geodesic_area_ha(overlap)
                if area <= 0:
                    continue
                clipped.append(overlap)
                features.append(
                    LayerFeature(
                        feature_id=str(row["gfw_fid"]),
                        overlap_ha=area,
                        properties={key: value for key, value in row.items() if key != "gfw_geojson"},
                        geometry=parsed_geometry,
                    )
                )
            features.sort(key=lambda feature: feature.feature_id)
            result = base.model_copy(
                update={
                    "status": "success",
                    "features": features,
                    "overlap_ha": geodesic_area_ha(unary_union(clipped)),
                    "fetched_at": timestamp,
                }
            )
        await cache.set(
            CacheEntry(
                source="gfw_layers",
                geometry_hash=geometry_digest,
                date_window=cache_window,
                request={"path": path, "query_revision": QUERY_REVISION},
                status_code=200,
                fetched_at=timestamp,
                payload=result.model_dump(mode="json"),
            )
        )
        return result
    except (IntegrationError, ValueError, TypeError, OverflowError, KeyError, ShapelyError) as exc:
        return base.model_copy(update={"error": str(exc)})
