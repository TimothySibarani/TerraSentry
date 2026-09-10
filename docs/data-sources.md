# Data sources

## The split, and why it must be stated on stage

| Layer | Status | Verifiable by judges |
|---|---|---|
| Tree-cover change | **Real** (Hansen GFC / GFW) | Yes |
| Fire hotspots | **Real** (NASA FIRMS) | Yes |
| Plot geometry | Synthetic demo polygons | Shape is real, location is invented |
| Corporate entities, directors, addresses | **Synthetic** | No, and say so |
| Permits | Synthetic | No, and say so |

Announce this split during the demo. Real geospatial data plus clearly labelled synthetic
entity data is a defensible engineering position; implying a live registry feed exists
would not survive one informed question.

## NASA FIRMS

- Key: https://firms.modaps.eosdis.nasa.gov/api/map_key/ -- free, instant.
- Endpoint: `/api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{day_range}` with an
  optional trailing `/{YYYY-MM-DD}`.
- **`day_range` maximum is 5.** History requires windowed calls, handled by
  `FirmsClient.fetch_history`.
- Quota: 5000 transactions per 10-minute interval, and a large request may cost more than one.
- Use the `_SP` science-quality archive products for history, `_NRT` for recent weeks.
- Coordinate order is **west, south, east, north**. Getting it wrong returns an empty
  result rather than an error, which is a nasty way to lose an afternoon.

## Tree-cover change

The question: *how much forest stood inside this polygon on 31 December 2020, and how
much is gone now?*

Method: count pixels where `treecover2000 >= threshold` AND `lossyear >= 21` (loss in 2021
or later, i.e. after the EUDR cutoff), then convert to hectares.

Three backends in `tools/forest_change.py`:

1. **CachedBackend** -- pre-computed JSON. Use this on stage.
2. **GfwDataApiBackend** -- https://data-api.globalforestwatch.org/ runs zonal statistics
   server-side. Fastest path to a real number. Confirm the dataset slug and version before
   relying on it; GFW versions these and they change with each annual release.
3. **LocalRasterBackend** -- Hansen tiles plus rasterio. Most control, most work, no rate
   limits.

**The mistake that produces wrong numbers:** multiplying a pixel count by a constant area.
Hansen pixels are roughly 30 m at the equator and shrink in ground area with latitude.
Compute per-pixel area properly, by latitude.

Also note rasterio does not fit in a Lambda zip layer -- use a container image, AWS Batch,
or a Fargate task.

The canopy threshold (30% by convention) moves the result materially. State whichever you
use in the DDS.

## Corporate registry

AHU (Kemenkumham) has a public search interface but no clean public API. The demo uses
`data/entities/suppliers.json`, hand-built to mirror the shape of real records. No real
company is depicted.

The heuristics in `tools/entity.py` -- shared registered addresses, overlapping directors,
recent incorporation -- work unchanged against a real feed the day one exists. That is the
transferable part, and it is what to claim.

## Regulation text

Regulation (EU) 2023/1115 plus Commission guidance, FAQs, and the May 2026 simplification
package. Load into Bedrock Knowledge Bases for the Compliance Writer.

One consequence of the May 2026 package worth knowing: the DDS obligation now concentrates
on the **first operator** placing goods on the EU market, which pushes evidence demands
harder onto upstream suppliers rather than more softly.

## Adding a new demo supplier

1. Add the entity and the supplier entry to `data/entities/suppliers.json`.
2. Drop a WGS84 GeoJSON polygon in `data/polygons/{SUPPLIER_ID}.geojson`.
3. Add `data/cache/forest_change_{SUPPLIER_ID}.json` and `hotspots_{SUPPLIER_ID}.json`.
4. Run `python -m scripts.run_screening --supplier {SUPPLIER_ID}` and check the band.
