"""Shared builders and HTTP mocks for the M3 agent tests.

No credentials, no network: every source response is synthesized from the
request geometry, so the reference pipeline and the agent path see identical
data and their assessments can be compared directly.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel
from terrasentry_core.agents.models import ModelBundle
from terrasentry_core.agents.scripted import AdaptiveAutopilotResponder, AutopilotResponder, ScriptedModel
from terrasentry_core.agents.verification import VerificationReport
from terrasentry_core.seed import DEFAULT_RNG_SEED, generate_batch, operator_dataset
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_integrations.settings import IntegrationSettings

GFW_URL = "https://data-api.globalforestwatch.org/dataset/umd_tree_cover_loss/v1.13/query/json"
FIRMS_REGEX = r"https://firms\.modaps\.eosdis\.nasa\.gov/api/area/csv/TESTKEY/VIIRS_SNPP_NRT/.*"
FIXED_TIME = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
_SQL_START_YEAR = re.compile(r"umd_tree_cover_loss__year >= (\d+)")

FIRMS_HEADER = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
    "confidence,version,bright_ti5,frp,daynight"
)


def settings() -> IntegrationSettings:
    """High-limit test settings with placeholder credentials."""
    return IntegrationSettings(
        gfw_api_key="test-key",
        gfw_rate_limit_per_min=100_000,
        firms_map_key="TESTKEY",
        firms_rate_limit_per_10min=100_000,
    )


def datasets(*, rng_seed: int = DEFAULT_RNG_SEED) -> SeedDatasets:
    batch = generate_batch(rng_seed=rng_seed)
    return SeedDatasets(batch, operator_dataset(batch).operator)


def gfw_loss_for(geometry: dict[str, Any]) -> float:
    """Deterministic loss per polygon, derived from its first longitude."""
    lon = float(geometry["coordinates"][0][0][0])
    return round((abs(lon) * 100) % 12, 4)


def gfw_side_effect(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    match = _SQL_START_YEAR.search(str(body.get("sql", "")))
    year = int(match.group(1)) if match else datetime.now(tz=UTC).year - 1
    loss = gfw_loss_for(body["geometry"])
    return httpx.Response(
        200,
        json={"status": "success", "data": [{"umd_tree_cover_loss__year": year, "loss_ha": loss}]},
    )


def bbox_of(request: httpx.Request) -> tuple[float, float, float, float]:
    west, south, east, north = (float(value) for value in request.url.path.split("/")[-3].split(","))
    return west, south, east, north


def firms_count_for(bbox: tuple[float, float, float, float]) -> int:
    """Deterministic hotspot count per bounding box."""
    west, _south, east, _north = bbox
    return int(abs(west + east) * 50) % 9


def firms_side_effect(request: httpx.Request) -> httpx.Response:
    west, south, east, north = bbox_of(request)
    count = firms_count_for((west, south, east, north))
    if count == 0:
        return httpx.Response(200, text="")
    today = datetime.now(tz=UTC).date().isoformat()
    center_lat = (south + north) / 2
    center_lon = (west + east) / 2
    rows = [
        f"{center_lat + index * 1e-5},{center_lon + index * 1e-5},330.1,1.0,1.0,{today},"
        "1010,VIIRS,NOAA-20,n,2.0NRT,295.0,12.5,D"
        for index in range(count)
    ]
    return httpx.Response(200, text="\n".join([FIRMS_HEADER, *rows]) + "\n")


def accepted_verification() -> VerificationReport:
    return VerificationReport(
        accepted=True,
        checked_claims=["llm.scripted"],
        notes=["scripted verifier: deterministic checks are the gate"],
    )


def scripted_models(
    record: Any,
    *,
    review: VerificationReport | None = None,
    adaptive: bool = True,
    skip_deep_dives: bool = False,
) -> ModelBundle:
    """Models for one record: the adaptive (default) or fixed autopilot route plus a verifier review."""
    structured: dict[type[BaseModel], BaseModel] = {VerificationReport: review or accepted_verification()}
    responder = (
        AdaptiveAutopilotResponder.for_record(
            record, structured_outputs=structured, skip_deep_dives=skip_deep_dives
        )
        if adaptive
        else AutopilotResponder.for_record(record, structured_outputs=structured)
    )
    return ModelBundle(
        orchestrator=ScriptedModel(responder=responder),
        extraction=ScriptedModel(responder=responder),
    )


def _feature_row_for(request: httpx.Request, **properties: Any) -> httpx.Response:
    """One vector-layer row that covers the whole request geometry (a full overlap)."""
    geometry = json.loads(request.content)["geometry"]
    return httpx.Response(
        200,
        json={
            "status": "success",
            "data": [{"gfw_fid": 1, "gfw_geojson": json.dumps(geometry), **properties}],
        },
    )


def mock_context_layers(
    router,
    *,
    overlaps: dict[str, dict[str, Any]] | None = None,
    unavailable: frozenset[str] = frozenset(),
):
    """Mock every GFW context layer: clear by default.

    ``overlaps`` maps a layer name to feature properties for a full-geometry overlap on that
    vector layer; ``unavailable`` layers answer with an HTTP error so the layer is unavailable.
    """
    from terrasentry_integrations.sources.gfw_layers import LAYER_DEFINITIONS

    for name, (dataset, version, _, _) in LAYER_DEFINITIONS.items():
        url = f"https://data-api.globalforestwatch.org/dataset/{dataset}/{version}/query/json"
        if name in unavailable:
            router.post(url).mock(return_value=httpx.Response(422, json={"status": "failed"}))
        elif overlaps and name in overlaps:
            router.post(url).mock(
                side_effect=lambda request, props=overlaps[name]: _feature_row_for(request, **props)
            )
        else:
            router.post(url).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "status": "success",
                        "data": [{"overlap_ha": 0}] if name in {"peatlands", "forest_baseline"} else [],
                    },
                )
            )
