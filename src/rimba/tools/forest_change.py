"""Tree-cover change against the EUDR baseline of 31 December 2020.

This is the real technical core of the project and the part that will take the
longest. Everything else is plumbing around this answer:

    "How much forest was inside this polygon on 31 December 2020,
     and how much of it is gone now?"

Three backends are defined, in increasing order of effort:

  1. :class:`CachedBackend` -- reads a pre-computed JSON result. **Use this on stage.**
     Demo Day must not depend on a network call or a raster computation completing
     in front of judges.
  2. :class:`GfwDataApiBackend` -- queries the Global Forest Watch Data API, which can
     run zonal statistics server-side. Fastest route to a real number.
  3. :class:`LocalRasterBackend` -- downloads Hansen Global Forest Change tiles and
     computes the zonal statistic locally with rasterio. Most control, most work,
     no external rate limits.

Method, for all backends:

    loss_ha = area of pixels inside the polygon where
              treecover2000 >= canopy_threshold AND lossyear >= 2021

The Hansen ``lossyear`` band encodes the year of loss as 1..N counting from 2000,
so ``lossyear >= 21`` corresponds to loss in 2021 or later -- i.e. after the EUDR
cutoff of 31 December 2020. Verify the encoding against the version of the dataset
you actually download; it has changed between releases.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

# EUDR cutoff: land must be deforestation-free since 31 December 2020,
# so any loss recorded in 2021 or later is in scope.
EUDR_CUTOFF_YEAR = 2020
FIRST_IN_SCOPE_LOSS_YEAR = EUDR_CUTOFF_YEAR + 1

# Hansen GFC treats a pixel as forest above a canopy density threshold. 30% is the
# convention in most published analyses; state whichever you use in the DDS, because
# the number moves materially with this choice.
DEFAULT_CANOPY_THRESHOLD = 30


@dataclass
class ForestChangeResult:
    """Zonal statistics for one polygon."""

    polygon_area_ha: float
    tree_cover_2020_ha: float
    loss_since_cutoff_ha: float
    loss_by_year: dict[str, float] = field(default_factory=dict)
    canopy_threshold: int = DEFAULT_CANOPY_THRESHOLD
    dataset: str = "Hansen Global Forest Change"
    backend: str = "unknown"
    notes: list[str] = field(default_factory=list)

    @property
    def loss_share_of_plot(self) -> float:
        """Loss as a fraction of the whole plot (0..1)."""
        if self.polygon_area_ha <= 0:
            return 0.0
        return self.loss_since_cutoff_ha / self.polygon_area_ha

    @property
    def is_deforestation_free(self) -> bool:
        """The blunt EUDR question. Any post-cutoff loss puts this in doubt.

        Deliberately strict: this returns the technical observation, not a legal
        conclusion. Small losses can have lawful explanations (infrastructure,
        natural disturbance) -- that is a judgement for a human, informed by the
        agent's escalation, not something to bury behind a tolerance threshold here.
        """
        return self.loss_since_cutoff_ha <= 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "polygon_area_ha": round(self.polygon_area_ha, 3),
            "tree_cover_2020_ha": round(self.tree_cover_2020_ha, 3),
            "loss_since_cutoff_ha": round(self.loss_since_cutoff_ha, 3),
            "loss_share_of_plot": round(self.loss_share_of_plot, 5),
            "loss_by_year": {k: round(v, 3) for k, v in sorted(self.loss_by_year.items())},
            "canopy_threshold_pct": self.canopy_threshold,
            "dataset": self.dataset,
            "backend": self.backend,
            "is_deforestation_free": self.is_deforestation_free,
            "notes": self.notes,
        }


class ForestChangeBackend(ABC):
    """Interface every backend implements, so the agent tool never has to care which is active."""

    name: str = "abstract"

    @abstractmethod
    def analyse(
        self,
        geom: BaseGeometry,
        polygon_area_ha: float,
        canopy_threshold: int = DEFAULT_CANOPY_THRESHOLD,
    ) -> ForestChangeResult:
        ...


class CachedBackend(ForestChangeBackend):
    """Reads pre-computed results keyed by supplier id. Use this for Demo Day.

    Populate the cache with ``scripts/precompute_forest_change.py`` (to be written by
    the geospatial owner) using one of the live backends, then commit the JSON.
    """

    name = "cache"

    def __init__(self, cache_dir: str | Path = "data/cache") -> None:
        self.cache_dir = Path(cache_dir)

    def analyse(
        self,
        geom: BaseGeometry,
        polygon_area_ha: float,
        canopy_threshold: int = DEFAULT_CANOPY_THRESHOLD,
        supplier_id: str | None = None,
    ) -> ForestChangeResult:
        if supplier_id is None:
            raise ValueError("CachedBackend requires supplier_id to locate the cached result")
        path = self.cache_dir / f"forest_change_{supplier_id}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"No cached forest-change result at {path}. "
                "Run the precompute script before the demo."
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ForestChangeResult(
            polygon_area_ha=payload["polygon_area_ha"],
            tree_cover_2020_ha=payload["tree_cover_2020_ha"],
            loss_since_cutoff_ha=payload["loss_since_cutoff_ha"],
            loss_by_year=payload.get("loss_by_year", {}),
            canopy_threshold=payload.get("canopy_threshold_pct", canopy_threshold),
            dataset=payload.get("dataset", "Hansen Global Forest Change"),
            backend="cache",
            notes=payload.get("notes", []),
        )


class GfwDataApiBackend(ForestChangeBackend):
    """Global Forest Watch Data API backend.

    GFW exposes datasets that can be queried with a geometry to return zonal
    statistics without downloading rasters. This is the fastest path to a real
    number and the recommended first implementation.

    TODO(geospatial owner):
      * Register at https://data-api.globalforestwatch.org/ and obtain an API key.
      * Confirm the current dataset slug and version for Hansen tree-cover loss --
        GFW versions these (e.g. ``umd_tree_cover_loss``) and the version string
        changes with each annual release. Do not hardcode a version you have not
        confirmed responds today.
      * Confirm the response units. GFW returns area in hectares for most
        aggregations, but check rather than assume.
    """

    name = "gfw_data_api"
    BASE = "https://data-api.globalforestwatch.org"

    def __init__(self, api_key: str | None = None, timeout: int = 60) -> None:
        self.api_key = api_key or os.environ.get("GFW_API_KEY", "")
        self.timeout = timeout

    def analyse(
        self,
        geom: BaseGeometry,
        polygon_area_ha: float,
        canopy_threshold: int = DEFAULT_CANOPY_THRESHOLD,
    ) -> ForestChangeResult:
        raise NotImplementedError(
            "GfwDataApiBackend is a documented stub. Implement against the live API "
            "and confirm the dataset slug/version before relying on the numbers. "
            "See the class docstring for the exact checklist."
        )

    def _post_query(self, dataset: str, version: str, sql: str, geom: BaseGeometry) -> dict:
        """Reference shape of a GFW zonal query. Left here as a starting point."""
        url = f"{self.BASE}/dataset/{dataset}/{version}/query"
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        resp = requests.post(
            url,
            headers=headers,
            json={"sql": sql, "geometry": mapping(geom)},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()


class LocalRasterBackend(ForestChangeBackend):
    """Hansen GFC tiles processed locally with rasterio.

    Most control, no rate limits, but you own the data pipeline.

    TODO(geospatial owner):
      * Hansen tiles are published as 10x10 degree GeoTIFFs. For a single Indonesian
        province you typically need one to four tiles of each band.
      * Bands needed: ``treecover2000``, ``lossyear``, and optionally ``datamask``
        to exclude water and no-data.
      * Compute per-pixel area properly. Hansen pixels are ~30 m at the equator but
        shrink in ground area with latitude -- multiplying a pixel count by a constant
        is the single most common source of wrong numbers in this analysis.
      * Mask with the polygon (``rasterio.mask.mask``), then count pixels where
        ``treecover2000 >= canopy_threshold`` and ``lossyear >= 21``.
      * rasterio in AWS Lambda needs a container image; the wheel exceeds the zip
        layer limit. AWS Batch or a Fargate task is often the simpler route.
    """

    name = "local_raster"

    def __init__(self, tile_dir: str | Path = "data/rasters") -> None:
        self.tile_dir = Path(tile_dir)

    def analyse(
        self,
        geom: BaseGeometry,
        polygon_area_ha: float,
        canopy_threshold: int = DEFAULT_CANOPY_THRESHOLD,
    ) -> ForestChangeResult:
        raise NotImplementedError(
            "LocalRasterBackend is a documented stub. See the class docstring for the "
            "implementation checklist, especially per-pixel area by latitude."
        )


def get_backend(name: str | None = None) -> ForestChangeBackend:
    """Resolve a backend by name, defaulting to the environment or the cache."""
    name = (name or os.environ.get("FOREST_CHANGE_BACKEND", "cache")).lower()
    if name == "cache":
        return CachedBackend()
    if name in ("gfw", "gfw_data_api"):
        return GfwDataApiBackend()
    if name in ("local", "local_raster"):
        return LocalRasterBackend()
    raise ValueError(f"Unknown forest-change backend: {name}")
