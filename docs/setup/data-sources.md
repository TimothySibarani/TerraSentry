# Data Sources — Keys, Limits, and Verification

M1 talks to two real APIs and caches responses in SQLite. Keys are free; the work is
understanding each API's shape and staying inside its quota.

| Source | What we use it for | Credential | Env vars |
| --- | --- | --- | --- |
| Global Forest Watch Data API (Hansen GFC) | Annual loss and seven context layers inside a polygon | API key (1-year expiry) | `GFW_API_KEY`, `GFW_API_ORIGIN` |
| NASA FIRMS | Near-real-time fire hotspots inside a polygon | MAP_KEY (emailed) | `FIRMS_MAP_KEY`, `FIRMS_SOURCE` |
| SQLite | Response cache keyed by `(namespace, source, geometry_hash, date_window)` | none | `CACHE_SQLITE_PATH`, `CACHE_BACKEND` |

## 1. Global Forest Watch (GFW / Hansen GFC)

We query the `umd_tree_cover_loss` dataset (30 m annual Hansen tree cover loss), pinned to
`GFW_TCL_VERSION=v1.13`. The API base is `https://data-api.globalforestwatch.org`.

### Create the key

1. Create a Resource Watch account: <https://api.resourcewatch.org/auth/sign-up>
2. Get a JWT access token (the response contains `data.access_token`):

```bash
curl -sS -X POST "https://data-api.globalforestwatch.org/auth/token" \
  --data-urlencode "username=<you@example.com>" \
  --data-urlencode "password=<password>" | head -c 400
```

3. Exchange the JWT for an API key. List the domains you will call from plus `localhost`
   (domains are matched against the request's `Origin` header; root and `www` differ, and
   ports must be omitted):

```bash
curl -sS -X POST "https://data-api.globalforestwatch.org/auth/apikey" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT>" \
  -d '{
    "alias": "terrasentry-dev",
    "email": "<you@example.com>",
    "organization": "TerraSentry",
    "domains": ["localhost"]
  }'
```

4. Put the returned key in `.env` as `GFW_API_KEY`. Local requests send
   `Origin: http://localhost` (configurable via `GFW_API_ORIGIN`).

> Keys with no domains default to the **lowest rate-limit tier**. Allowlisting domains and
> sending a matching `Origin` is how you get a higher tier. The preflight probe reports the
> observed behaviour either way.

### Verify

```bash
curl -sS -X POST \
  "https://data-api.globalforestwatch.org/dataset/umd_tree_cover_loss/v1.13/query/json" \
  -H "x-api-key: $GFW_API_KEY" \
  -H "Origin: http://localhost" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "SELECT umd_tree_cover_loss__year, SUM(area__ha) AS loss_ha FROM results GROUP BY umd_tree_cover_loss__year ORDER BY umd_tree_cover_loss__year",
    "geometry": {
      "type": "Polygon",
      "coordinates": [[[101.0,0.0],[101.01,0.0],[101.01,0.01],[101.0,0.01],[101.0,0.0]]]
    }
  }' | head -c 600
```

A successful response contains `data` rows of `{umd_tree_cover_loss__year, loss_ha}`.

### Notes

- Raster datasets require a polygon geometry on every query.
- Large geometries are slow; the async batch endpoint (`/query/batch`) is the scale path:
  submit a FeatureCollection, poll `GET /job/{job_id}`, then download the result.
- Attribution: cite *Hansen et al., 2013* and Global Forest Watch in the dossier.
- The loss client caches by `(gfw, geometry_hash, dataset:version:loss-1:start-end year)`, so rehearsal re-runs make
  zero calls.

## 2. NASA FIRMS

We use the area API: `https://firms.modaps.eosdis.nasa.gov/api` with the default source
`VIIRS_SNPP_NRT` (375 m, near-real-time).

### Get the MAP_KEY

1. Request a free key at <https://firms.modaps.eosdis.nasa.gov/api/map_key/>; it arrives by
   email, usually quickly but occasionally taking days — request it on Day 1.
2. Put it in `.env` as `FIRMS_MAP_KEY`.

### Verify

```bash
curl -sS "https://firms.modaps.eosdis.nasa.gov/api/area/csv/$FIRMS_MAP_KEY/VIIRS_SNPP_NRT/101.0,-0.5,101.5,0.5/2" \
  | head -5
```

A header row (and possibly detection rows) means the key works.

### Limits and shape

- **5000 transactions per 10-minute interval** per key; larger requests count as multiple
  transactions. Our limiter defaults to 300 per 10 minutes (`FIRMS_RATE_LIMIT_PER_10MIN`).
- `DAY_RANGE` is **1–5 days**, so the client chunks longer windows (30 days = six calls)
  and de-duplicates.
- Area queries take a **bounding box**, not a polygon. The client computes the polygon's
  bbox and then filters detections back to the polygon, so evidence never includes fires
  outside the concession.
- Sources: `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `MODIS_NRT`, and `*_SP` archives. NRT is
  fresher; SP is science-quality but lags. Use NRT for the demo (`FIRMS_SOURCE`).
- Attribution: include NASA FIRMS in the evidence footnote.

## 3. SQLite cache

`CACHE_BACKEND=sqlite` is the default. `CACHE_SQLITE_PATH=data/sqlite/cache.db` stores responses
separately from `DATABASE_URL=sqlite+aiosqlite:///data/sqlite/audit.db`, which holds the audit trail.
Relative paths resolve from the repository root. The cache creates its parent directory and table
on first use; it does not require API migrations, so the reference, preflight and fixture CLIs work
independently. `CACHE_BACKEND=memory` remains an ephemeral option for tests.

- Each row contains the full serialized `CacheEntry` and an optional expiration timestamp.
- `CACHE_PREFIX` (default `ts:cache:v1`) isolates namespaces. Source/geometry/window identities stay unchanged.
- TTL defaults to 90 days (`CACHE_TTL_SECONDS`) from the time an entry is written or a fixture is
  primed. Zero/negative disables expiration. Expired entries are misses, including in offline mode.
- `CACHE_OFFLINE=true` rejects cache misses without attempting external requests.
- WAL and a 30-second busy timeout support bounded local concurrency. One API process owns
  `audit.db`; stop the API before running the rehearsal CLI against it. Use a persistent local disk,
  not a shared network filesystem or an ephemeral container layer.

Export and restore responses across processes:

```bash
uv run python -m terrasentry_integrations.fixtures export --dir data/fixtures
uv run python -m terrasentry_integrations.fixtures prime --dir data/fixtures
```

Inspect with an optional local SQLite CLI (not a runtime dependency):

```bash
sqlite3 data/sqlite/cache.db 'SELECT namespace, source, count(*) FROM cache_entries GROUP BY namespace, source;'
```

To reset the disposable cache, stop its users and remove only `data/sqlite/cache.db` and its
`-wal`/`-shm` sidecars, then prime exported fixtures or fetch responses again. Do not delete
`audit.db` to clear cached responses. An audit reset is a separate, explicit demo reset and loses
submitted records, settings and run history.

Both files are ignored by Git and excluded from Docker image context. Compose mounts them in the
`sqlite-data` volume; container replacement preserves data, while `docker compose down -v` removes
it. For a file backup, stop all writers first and copy the directory after connections close;
do not copy only the main file from a live WAL database.

Existing `.env`: replace the old database URL and cache backend with the values above and remove
`REDIS_URL`. PostgreSQL/Redis data are not imported, and their old volumes are not deleted.

## 4. How rate limits are handled in code

1. Per-source `aiolimiter` caps concurrency and rate (`GFW_RATE_LIMIT_PER_MIN`,
   `FIRMS_RATE_LIMIT_PER_10MIN`).
2. `tenacity` retries timeouts, transport errors, 429s, and 5xx with exponential backoff +
   jitter, honouring `Retry-After`.
3. Every success is cached, so the same geometry/window never costs two calls.
4. The preflight probe measures real latency and quota behaviour before the batch commits
   to a concurrency level.

## 5. Secret hygiene

- Never commit `.env`, keys, or service keys. `.env` is gitignored; `.env.example` lists
  variable names only.
- Rotate GFW keys when a teammate leaves; they expire after a year regardless.
- Do not log query URLs for FIRMS — the MAP_KEY is in the path. The HTTP layer never logs
  URLs.

## 6. S2 context and cutoff contract (2026-10-02)

Screening always checks loss from **2021** through the last completed year covered by
Hansen `v1.13` (**2025**), even when a legacy caller supplies a rolling window.
Unknown loss releases are a source gap until their annual coverage is verified.
Coverage reference: [UMD/GLAD Hansen 2025 v1.13 release](https://storage.googleapis.com/earthenginepartners-hansen/GFC-2025-v1.13/download.html).

| Signal | Pinned dataset/version | Applicability |
| --- | --- | --- |
| Protected areas | `wdpa_protected_areas/v202512` | Global |
| Forest moratorium | `idn_forest_moratorium/v20200923` | ID |
| Oil-palm concessions | `gfw_oil_palm/v2025` | ID |
| Wood-fiber concessions | `gfw_wood_fiber/v2025` | ID |
| Logging concessions | `gfw_logging/v202106` | ID |
| Peat | `gfw_peatlands/v20230315` | ID; broader coverage unverified |
| Forest baseline | `jrc_global_forest_cover/v2020.3` | Global; context only, no scoring credit |

Vector queries return full feature geometry, not clipped hectares. The client intersects
it locally, measures WGS84 geodesic area with holes subtracted, ignores boundary-only
contact, and unions footprints before totaling each layer. Evidence retains feature IDs,
names/designations/companies, geometry, per-feature area, dataset/version, query revision,
and retrieval time. Pages are 100 rows, bounded at 1,000 features and 10 MiB; exceeding a
bound or receiving malformed geometry produces an explicit unavailable result.

`success` with zero overlap, `unavailable`, and `not_applicable` are separate states.
A failed applicable layer prevents a compliant verdict; successful siblings stay cached
and only failures are retried. These historical context layers and declared permits are
**not current legal-registry verification**. Non-ID records skip the five ID-only queries;
missing HGU/PBPH is not applicable outside ID, while expired declared permits and sanctions
still matter. Missing expiry remains disclosed as unknown.

Context cache keys use source `gfw_layers`, the `geometry-v2` exact query-geometry hash and
`dataset:version:clip-2`.
`GFW_CONTEXT_RELEASES` accepts a JSON mapping, e.g.
`{"protected_areas":"wdpa_protected_areas/v202512"}`. Only explicit versions are allowed;
verify the new release's fields and geographic coverage before configuring it. Changing
release or query revision invalidates the corresponding cache identity. Old S1 loss-only
fixtures must be prefetched again before an S2 offline rehearsal.

For an ephemeral source smoke (no persistent cache):

```bash
CACHE_BACKEND=memory uv run python -m terrasentry_integrations.preflight \
  --polygons data/seed/demo_polygons.json --limit 3 --no-batch
```

The report includes full applicable-layer results and cold/warm timings. At the default
60 GFW requests/minute, 50 cold ID plots require at least 400 GFW queries plus FIRMS;
prefetch for demos rather than promising a two-minute cold batch.
