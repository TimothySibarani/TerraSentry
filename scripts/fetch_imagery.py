"""Find and render Sentinel-2 composites for the evidence map.

    python -m scripts.fetch_imagery --supplier SUP-001 --search-only
    python -m scripts.fetch_imagery --supplier SUP-001

Why Sentinel-2 and not Google Maps: Google discards old imagery once new imagery
arrives, stores no acquisition date, and its terms forbid storing and re-serving the
images -- which is exactly what an evidence pack has to do. Sentinel-2 is dated, free,
archived back to 2017, and lives in the AWS Registry of Open Data, so the imagery in a
TerraSentry dossier comes from an AWS open dataset.

Data: https://registry.opendata.aws/sentinel-2-l2a-cogs/
Search: Earth-search STAC API (no key required)

Practical warning for Indonesia: equatorial cloud cover is the binding constraint, not
data availability. A four-month window over Kalimantan can yield a single usable scene.
Widen the window before lowering your standards on cloud percentage.

Rendering requires rasterio, which is not in the default requirements because it is a
heavy install and only the geospatial owner needs it:

    pip install rasterio

``--search-only`` works without it and is enough to confirm which scenes exist.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from terrasentry.pipeline import DATA, find_supplier, load_registry_payload  # noqa: E402
from terrasentry.tools import geometry as geo  # noqa: E402

STAC_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"
OUT_DIR = DATA / "cache" / "imagery"

# EUDR cutoff is 31 Dec 2020, so the "before" composite must sit as close to it as cloud
# cover allows. Windows are deliberately wide -- see the cloud warning above.
DEFAULT_BEFORE = "2020-06-01/2021-06-30"
DEFAULT_AFTER = "2025-06-01/2026-09-30"
DEFAULT_MAX_CLOUD = 40


def search(bbox: tuple[float, float, float, float], window: str, max_cloud: int) -> list[dict[str, Any]]:
    """Query Earth-search for scenes intersecting the bbox within a date window."""
    start, end = window.split("/")
    body = {
        "collections": [COLLECTION],
        "bbox": list(bbox),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "query": {"eo:cloud_cover": {"lt": max_cloud}},
        "limit": 50,
    }
    resp = requests.post(STAC_URL, json=body, timeout=60)
    resp.raise_for_status()
    features = resp.json().get("features", [])
    return sorted(features, key=lambda f: f["properties"].get("eo:cloud_cover", 100))


def describe(scene: dict[str, Any]) -> str:
    p = scene["properties"]
    return f"{scene['id']}  {p['datetime'][:10]}  cloud {p.get('eo:cloud_cover', 0):.1f}%"


def render(scene: dict[str, Any], bbox: tuple[float, float, float, float], out_png: Path) -> dict[str, Any]:
    """Clip the true-colour asset to the bbox and write a PNG.

    Reads only the window covering the plot. The asset is a Cloud-Optimized GeoTIFF, so
    this pulls a few hundred kilobytes over HTTP range requests rather than the whole
    scene -- which is what makes this practical to run from a Lambda.
    """
    try:
        import numpy as np
        import rasterio
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds
    except ImportError:
        raise SystemExit(
            "Rendering needs rasterio and numpy:  pip install rasterio numpy\n"
            "Use --search-only to confirm scene availability without them."
        )

    href = scene["assets"].get("visual", {}).get("href")
    if not href:
        raise SystemExit(f"Scene {scene['id']} has no 'visual' asset to render.")

    with rasterio.open(href) as src:
        left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox, densify_pts=21)
        window = from_bounds(left, bottom, right, top, transform=src.transform)
        data = src.read([1, 2, 3], window=window, boundless=True, fill_value=0)

    rgb = np.transpose(data, (1, 2, 0))
    # Percentile stretch: raw TCI over tropical forest is dark and flat, and an
    # unstretched image reads as a black rectangle on a projector.
    lo, hi = np.percentile(rgb[rgb > 0], (2, 98)) if (rgb > 0).any() else (0, 255)
    rgb = np.clip((rgb.astype("float32") - lo) / max(hi - lo, 1) * 255, 0, 255).astype("uint8")

    out_png.parent.mkdir(parents=True, exist_ok=True)
    _write_png(rgb, out_png)

    return {
        "date": scene["properties"]["datetime"][:10],
        "scene_id": scene["id"],
        "cloud_cover": round(scene["properties"].get("eo:cloud_cover", 0), 1),
        "url": f"/data/cache/imagery/{out_png.name}",
        "bounds": list(bbox),
        "source": "Sentinel-2 L2A, AWS Registry of Open Data",
    }


def _write_png(rgb, path: Path) -> None:
    """Write RGB to PNG using only the standard library (zlib + struct)."""
    import struct
    import zlib

    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Sentinel-2 composites for a supplier plot.")
    parser.add_argument("--supplier", default="SUP-001")
    parser.add_argument("--before", default=DEFAULT_BEFORE, help="start/end around the EUDR cutoff")
    parser.add_argument("--after", default=DEFAULT_AFTER, help="start/end for the current view")
    parser.add_argument("--max-cloud", type=int, default=DEFAULT_MAX_CLOUD)
    parser.add_argument("--search-only", action="store_true", help="List scenes; do not download.")
    args = parser.parse_args()

    supplier = find_supplier(load_registry_payload(), args.supplier)
    sid = supplier["supplier_id"]
    geom = geo.load_geojson(supplier["polygon"])
    report = geo.validate(geom)
    bbox = geo.buffer_bbox(report.bbox, km=1.5)  # a little context around the plot

    print(f"\n{supplier['legal_name']} ({sid})")
    print(f"bbox {tuple(round(v, 4) for v in bbox)}  |  cloud cover under {args.max_cloud}%\n")

    manifest = {"supplier_id": sid, "bbox": list(bbox), "scenes": []}

    for label, window in (("before (EUDR cutoff)", args.before), ("after (current)", args.after)):
        scenes = search(bbox, window, args.max_cloud)
        print(f"{label}  {window}  ->  {len(scenes)} scene(s)")
        for s in scenes[:5]:
            print(f"    {describe(s)}")
        if not scenes:
            print("    none. Widen the window -- equatorial cloud cover is the constraint.\n")
            continue
        print()

        if not args.search_only:
            best = scenes[0]
            tag = "before" if label.startswith("before") else "after"
            out = OUT_DIR / f"{sid}_{tag}.png"
            print(f"    rendering {best['id']} -> {out.name}")
            manifest["scenes"].append(render(best, bbox, out))

    if args.search_only:
        print("Search only -- nothing written. Drop --search-only to render.\n")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{sid}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nmanifest -> {OUT_DIR / f'{sid}.json'}")
    print("The panel will pick these up on the next screening.\n")


if __name__ == "__main__":
    main()
