"""Generate the demo supply base: one mill, three aggregators, ~25 suppliers.

    python -m scripts.seed_portfolio

Everything it writes is SYNTHETIC and deterministic (fixed seed), so the portfolio looks
identical on every machine and every rehearsal. No real company is depicted.

The cohort is shaped to look like an actual Indonesian timber supply base rather than a
tidy test fixture:

  * A few large concessions and a long tail of smallholder plots. Most Indonesian
    supply-chain risk lives in that tail, and most of those plots are **under 4 hectares**
    -- which EUDR Article 9 treats differently: a GPS point suffices, no polygon required.
    A demo with only big concessions quietly dodges the hardest real case.
  * Smallholders sit under cooperatives and collectors, because they do not contract with
    a mill directly.
  * Scores spread across every band. A screening tool that flags everything is as useless
    as one that flags nothing, and judges will look for that.

SUP-001 and SUP-002 are left untouched -- they are the hand-built narrative cases the
demo script and the existing tests depend on.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

DATA = Path("data")
SEED = 20261031  # Demo Day
rng = random.Random(SEED)

AGGREGATORS = [
    {"id": "AGG-01", "name": "Koperasi Tani Hutan Sanggau", "type": "cooperative", "region": "Kalimantan Barat"},
    {"id": "AGG-02", "name": "UD Sumber Rimba Kapuas", "type": "collector", "region": "Kalimantan Barat"},
    {"id": "AGG-03", "name": "Koperasi Rimba Jaya Sintang", "type": "cooperative", "region": "Kalimantan Barat"},
]

FIRST = ["Budi", "Siti", "Andi", "Rina", "Yohanes", "Dewi", "Hendra", "Maria", "Agus", "Lestari",
         "Bambang", "Sri", "Joko", "Ani", "Rudi", "Wayan", "Nur", "Teguh", "Ratna", "Iwan"]
LAST = ["Santoso", "Wijaya", "Tarigan", "Hartono", "Kusuma", "Prasetyo", "Simanjuntak", "Halim",
        "Nugroho", "Sihombing", "Permana", "Situmorang", "Gunawan", "Rahmawati", "Siregar"]

# (label, plots, area range ha, band we are aiming for)
COHORT = [
    ("concession", 2, (900, 4200), "GO"),
    ("concession", 1, (600, 1500), "CONDITIONAL"),
    ("concession", 1, (700, 2000), "ESCALATE_LOSS"),
    ("smallholder", 8, (0.8, 3.6), "GO"),           # below the 4 ha polygon threshold
    ("smallholder", 5, (1.2, 3.2), "CONDITIONAL"),
    ("smallholder", 2, (2.0, 3.8), "ESCALATE_FIRE"),
    ("smallholder", 1, (1.5, 2.5), "NO_GO"),
    ("smallholder", 1, (0.9, 2.0), "BLOCKED"),
]


def square(lon: float, lat: float, area_ha: float, swap: bool = False) -> dict:
    """A square plot of the requested area, centred on lon/lat."""
    side_m = math.sqrt(area_ha * 10_000)
    d_lat = side_m / 110_574 / 2
    d_lon = side_m / (111_320 * math.cos(math.radians(lat))) / 2
    ring = [
        [lon - d_lon, lat - d_lat], [lon + d_lon, lat - d_lat],
        [lon + d_lon, lat + d_lat], [lon - d_lon, lat + d_lat],
        [lon - d_lon, lat - d_lat],
    ]
    if swap:
        # A real and very common supplier error: latitude and longitude transposed.
        # The geometry tool must catch it and block the assessment rather than
        # silently analysing a plot in the wrong hemisphere.
        ring = [[lat, lon] for lon, lat in ring]
    return {"type": "Polygon", "coordinates": [ring]}


def profile_for(band: str) -> dict:
    """Pick inputs that land in the intended band. Scores are still computed by the rubric."""
    if band == "GO":
        return {"loss": 0.0, "hotspots": 0, "high": 0, "permit": True, "anomaly": False}
    if band == "CONDITIONAL":
        # No deforestation, so no hard gate -- lands on penalties alone (60-79).
        return {"loss": 0.0, "hotspots": rng.randint(18, 32), "high": rng.randint(6, 14),
                "permit": None, "anomaly": False}
    if band == "ESCALATE_LOSS":
        # Post-cutoff loss trips a hard gate, so the score is capped at 59 no matter what.
        return {"loss": round(rng.uniform(3.0, 40.0), 1), "hotspots": rng.randint(8, 25),
                "high": rng.randint(4, 15), "permit": True, "anomaly": rng.random() < 0.5}
    if band == "ESCALATE_FIRE":
        # No loss, no gate -- heavy fire plus an unverifiable permit gets there on merit.
        return {"loss": 0.0, "hotspots": rng.randint(45, 80), "high": rng.randint(25, 50),
                "permit": None, "anomaly": False}
    if band == "NO_GO":
        return {"loss": round(rng.uniform(60.0, 180.0), 1), "hotspots": rng.randint(40, 70),
                "high": rng.randint(30, 55), "permit": False, "anomaly": True}
    return {"loss": 0.0, "hotspots": 0, "high": 0, "permit": True, "anomaly": False}


def main() -> None:
    payload = json.loads((DATA / "entities" / "suppliers.json").read_text(encoding="utf-8"))

    # Keep the two hand-built narrative suppliers; regenerate everything after them.
    payload["entities"] = [e for e in payload["entities"] if e["entity_id"] in
                           ("ENT-001", "ENT-002", "ENT-003", "ENT-004")]
    payload["suppliers"] = [s for s in payload["suppliers"] if s["supplier_id"] in ("SUP-001", "SUP-002")]
    payload["aggregators"] = AGGREGATORS
    payload["mill"] = {"id": "MILL-01", "name": "Pabrik Pulp Kapuas Hilir", "commodity": "timber"}

    # The two originals belong to the mill directly.
    for s in payload["suppliers"]:
        s.setdefault("aggregator", None)
        s.setdefault("tier", "concession")
        s.setdefault("volume_m3_month", 4200 if s["supplier_id"] == "SUP-001" else 2600)

    n, ent_n = 2, 100
    for tier, count, (lo, hi), band in COHORT:
        for _ in range(count):
            n += 1
            ent_n += 1
            sid, eid = f"SUP-{n:03d}", f"ENT-{ent_n:03d}"
            area = round(rng.uniform(lo, hi), 2)
            lon = 110.30 + rng.uniform(0, 1.05)
            lat = -0.55 + rng.uniform(0, 0.62)

            if tier == "smallholder":
                agg = rng.choice(AGGREGATORS)["id"]
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
                legal = f"Kebun Rakyat {name}"
                volume = rng.randint(8, 60)
            else:
                agg = None
                legal = f"PT {rng.choice(['Hutan','Rimba','Kayu','Wana','Bumi'])} " \
                        f"{rng.choice(['Sejahtera','Makmur','Lestari','Perkasa','Abadi'])} " \
                        f"{rng.choice(['Nusantara','Borneo','Kapuas','Mandiri'])}"
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
                volume = rng.randint(800, 5000)

            permit = f"IUPHHK-HT/{rng.randint(100, 899)}/{rng.randint(2012, 2023)}"

            payload["entities"].append({
                "entity_id": eid,
                "legal_name": legal,
                "registration_number": f"AHU-{rng.randint(1000000, 9999999)}.AH.01.01.TAHUN {rng.randint(2012, 2024)}",
                "registered_address": f"Jl. {rng.choice(['Merdeka','Sudirman','Diponegoro','Gajah Mada'])} "
                                      f"No. {rng.randint(1, 200)}, {rng.choice(['Sanggau','Sintang','Pontianak','Kapuas Hulu'])}, Kalimantan Barat",
                "incorporated_on": f"{rng.randint(2012, 2023)}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}",
                "directors": [name],
                "shareholders": [name],
                "permit_numbers": [permit],
                "parcels": [f"PARCEL-{sid}"],
            })

            payload["suppliers"].append({
                "supplier_id": sid, "entity_id": eid, "legal_name": legal,
                "commodity": "timber", "country_of_production": "ID",
                "polygon": f"data/polygons/{sid}.geojson",
                "parcel_id": f"PARCEL-{sid}", "adjacent_parcels": [],
                "permit_number": permit, "aggregator": agg, "tier": tier,
                "volume_m3_month": volume,
            })

            prof = profile_for(band)
            if prof["permit"] is not None:
                payload["permits"][permit] = {
                    "holder": legal,
                    "valid_from": "2019-01-01",
                    "valid_to": "2049-12-31",
                    "status": "active" if prof["permit"] else "revoked",
                }

            # geometry
            geom = square(lon, lat, area, swap=(band == "BLOCKED"))
            (DATA / "polygons" / f"{sid}.geojson").write_text(json.dumps({
                "type": "Feature",
                "properties": {"supplier_id": sid, "parcel_id": f"PARCEL-{sid}",
                               "note": "SYNTHETIC demo geometry. Not a real plot."},
                "geometry": geom,
            }, indent=2), encoding="utf-8")

            # forest change
            (DATA / "cache" / f"forest_change_{sid}.json").write_text(json.dumps({
                "_note": "SYNTHETIC pre-computed result for the portfolio demo.",
                "supplier_id": sid,
                "polygon_area_ha": area,
                "tree_cover_2020_ha": round(area * rng.uniform(0.75, 0.96), 2),
                "loss_since_cutoff_ha": prof["loss"],
                "interior_loss_ha": prof["loss"],
                "boundary_loss_ha": 0.0,
                "loss_by_year": {"2023": prof["loss"]} if prof["loss"] else {},
                "canopy_threshold_pct": 30,
                "dataset": "Hansen Global Forest Change (SYNTHETIC)",
                "notes": [],
            }, indent=2), encoding="utf-8")

            # hotspots
            pts = [{"lon": round(lon + rng.uniform(-0.004, 0.004), 5),
                    "lat": round(lat + rng.uniform(-0.004, 0.004), 5),
                    "acq_date": f"2023-0{rng.randint(7,9)}-{rng.randint(1,28):02d}",
                    "confidence": "h" if i < prof["high"] else "n",
                    "frp": round(rng.uniform(2, 30), 1),
                    "id": f"SYNTH:{sid}:{i}"} for i in range(prof["hotspots"])]
            (DATA / "cache" / f"hotspots_{sid}.json").write_text(json.dumps({
                "_note": "SYNTHETIC hotspots for the portfolio demo.",
                "supplier_id": sid,
                "inside": {"total": len(pts), "high_confidence": prof["high"],
                           "by_year": {"2023": len(pts)} if pts else {},
                           "peak_month": {"month": "2023-08", "count": len(pts)} if len(pts) > 9 else None,
                           "points": pts},
                "buffer_only": {"total": 0, "high_confidence": 0, "by_year": {},
                                "peak_month": None, "points": []},
            }, indent=2), encoding="utf-8")

    (DATA / "entities" / "suppliers.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    smallholders = sum(1 for s in payload["suppliers"] if s.get("tier") == "smallholder")
    print(f"suppliers written : {len(payload['suppliers'])} ({smallholders} smallholder)")
    print(f"aggregators       : {len(AGGREGATORS)}")
    print(f"total volume      : {sum(s['volume_m3_month'] for s in payload['suppliers']):,} m3/month")


if __name__ == "__main__":
    main()
