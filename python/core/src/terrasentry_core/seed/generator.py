"""Deterministic generation of demo polygons and the 50-record batch."""

from __future__ import annotations

import json
import math
import random

from pyproj import Geod
from shapely.affinity import scale
from shapely.geometry import Polygon, mapping

from terrasentry_core.seed.legality import generate_legality
from terrasentry_core.seed.regions import REGIONS, Region
from terrasentry_core.seed.schemas import (
    Archetype,
    BatchDataset,
    BatchRecord,
    LegalityDataset,
    Scenario,
    SeedDataset,
    SeedPolygon,
)

DEFAULT_RNG_SEED = 20260911
BATCH_DISTRIBUTION: dict[str, int] = {"compliant": 30, "high_risk": 12, "ambiguous": 8}
DEMO_QUOTA: dict[str, int] = {"compliant": 3, "high_risk": 3, "ambiguous": 2}

_HA_PER_SQ_DEGREE = 1_230_000.0
_GEOD = Geod(ellps="WGS84")

_AREA_RANGES: dict[str, tuple[float, float]] = {
    "compliant": (300.0, 4000.0),
    "high_risk": (500.0, 6000.0),
    "ambiguous": (100.0, 1500.0),
}


def geodesic_area_ha(polygon: Polygon) -> float:
    area, _ = _GEOD.geometry_area_perimeter(polygon)
    return abs(area) / 10_000.0


def _vertices_polygon(rng: random.Random, lon: float, lat: float, target_ha: float) -> Polygon:
    radius = math.sqrt(max(target_ha, 1.0) / _HA_PER_SQ_DEGREE / math.pi)
    lat_scale = max(math.cos(math.radians(lat)), 0.2)
    points: list[tuple[float, float]] = []
    vertex_count = rng.randint(5, 8)
    for angle in sorted(rng.uniform(0.0, 2 * math.pi) for _ in range(vertex_count)):
        factor = rng.uniform(0.65, 1.35)
        points.append(
            (
                lon + math.cos(angle) * radius * factor / lat_scale,
                lat + math.sin(angle) * radius * factor,
            )
        )
    points.append(points[0])
    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon


def _polygon_for(rng: random.Random, region: Region, target_ha: float, *, demo: bool) -> Polygon:
    bbox = region.demo_bbox if demo and region.demo_bbox else region.bbox
    west, south, east, north = bbox
    lon = rng.uniform(west, east)
    lat = rng.uniform(south, north)
    polygon = _vertices_polygon(rng, lon, lat, target_ha)
    actual = geodesic_area_ha(polygon)
    if actual > 0:
        factor = math.sqrt(target_ha / actual)
        polygon = scale(polygon, xfact=factor, yfact=factor, origin=(lon, lat))
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon


def _to_seed_polygon(
    rng: random.Random,
    *,
    index: int,
    region: Region,
    archetype: Archetype,
    demo: bool,
    scenario: Scenario | None,
) -> SeedPolygon:
    target_ha = rng.uniform(*_AREA_RANGES[archetype])
    polygon = _polygon_for(rng, region, target_ha, demo=demo)
    centroid = polygon.centroid
    if scenario == "compliant_live":
        label = f"Live scenario A — compliant ({region.name})"
    elif scenario == "high_risk_live":
        label = f"Live scenario B — high risk ({region.name})"
    elif demo:
        label = f"Demo {archetype} — {region.name}"
    else:
        label = f"Batch record — {region.name} ({archetype})"
    return SeedPolygon(
        id=f"PLY-{index:03d}",
        label=label,
        region=region.name,
        province=region.province,
        archetype=archetype,
        scenario=scenario,
        is_demo=demo,
        area_ha=round(geodesic_area_ha(polygon), 2),
        centroid_lat=round(centroid.y, 6),
        centroid_lon=round(centroid.x, 6),
        geometry=json.loads(json.dumps(mapping(polygon))),
    )


def _repeat_archetype(archetype: Archetype, count: int) -> list[Archetype]:
    return [archetype] * count


def generate_batch(*, rng_seed: int = DEFAULT_RNG_SEED, batch_size: int | None = None) -> BatchDataset:
    """Generate the 30/12/8 batch plus the embedded demo subset (deterministic per seed)."""
    rng = random.Random(rng_seed)
    archetypes: list[Archetype] = []
    archetypes.extend(_repeat_archetype("compliant", BATCH_DISTRIBUTION["compliant"]))
    archetypes.extend(_repeat_archetype("high_risk", BATCH_DISTRIBUTION["high_risk"]))
    archetypes.extend(_repeat_archetype("ambiguous", BATCH_DISTRIBUTION["ambiguous"]))
    if batch_size is not None:
        archetypes = archetypes[:batch_size]
    rng.shuffle(archetypes)

    demo_counts: dict[str, int] = dict.fromkeys(DEMO_QUOTA, 0)
    assigned: set[Scenario] = set()
    records: list[BatchRecord] = []
    for index, archetype in enumerate(archetypes, start=1):
        region = REGIONS[(index - 1) % len(REGIONS)]
        demo = demo_counts[archetype] < DEMO_QUOTA[archetype]
        scenario: Scenario | None = None
        if demo:
            demo_counts[archetype] += 1
            if archetype == "compliant" and "compliant_live" not in assigned:
                scenario = "compliant_live"
            elif archetype == "high_risk" and "high_risk_live" not in assigned:
                scenario = "high_risk_live"
            if scenario is not None:
                assigned.add(scenario)
        polygon = _to_seed_polygon(
            rng,
            index=index,
            region=region,
            archetype=archetype,
            demo=demo,
            scenario=scenario,
        )
        supplier_id = f"SUP-{index:03d}"
        legality = generate_legality(
            rng,
            supplier_id=supplier_id,
            index=index,
            archetype=archetype,
            region=region,
        )
        records.append(
            BatchRecord(
                record_id=f"REC-{index:03d}",
                supplier_id=supplier_id,
                polygon=polygon,
                legality=legality,
                expected_archetype=archetype,
            )
        )

    distribution = {
        archetype: sum(1 for record in records if record.expected_archetype == archetype)
        for archetype in BATCH_DISTRIBUTION
    }
    return BatchDataset(rng_seed=rng_seed, distribution=distribution, records=records)


def demo_dataset(batch: BatchDataset) -> SeedDataset:
    """The hand-picked subset used by the M1 reference pipeline and the live demo."""
    return SeedDataset(
        rng_seed=batch.rng_seed,
        polygons=[record.polygon for record in batch.records if record.polygon.is_demo],
    )


def legality_dataset(batch: BatchDataset) -> LegalityDataset:
    return LegalityDataset(
        rng_seed=batch.rng_seed,
        records=[record.legality for record in batch.records],
    )
