# Data Sources — Keys, Limits, and Verification

M1 talks to two real APIs and caches everything in Redis. Keys are free; the work is
understanding each API's shape and staying inside its quota.

| Source | What we use it for | Credential | Env vars |
| --- | --- | --- | --- |
| Global Forest Watch Data API (Hansen GFC) | Annual tree cover loss inside a polygon | API key (1-year expiry) | `GFW_API_KEY`, `GFW_API_ORIGIN` |
| NASA FIRMS | Near-real-time fire hotspots inside a polygon | MAP_KEY (emailed) | `FIRMS_MAP_KEY`, `FIRMS_SOURCE` |
| Redis | Response cache keyed by `(source, geometry_hash, date_window)` | none locally | `REDIS_URL`, `CACHE_BACKEND` |

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
- The client caches by `(gfw, geometry_hash, start-end year)`, so rehearsal re-runs make
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

## 3. Redis cache

Local Redis runs in `compose.yaml` with append-only persistence:

```bash
docker compose up -d redis
docker compose exec redis redis-cli ping        # PONG
```

- Key format: `{CACHE_PREFIX}:{source}:{geometry_hash}:{date_window}` (default prefix
  `ts:cache:v1`).
- TTL defaults to 90 days (`CACHE_TTL_SECONDS`).
- `CACHE_BACKEND=memory` gives an ephemeral in-process cache for a smoke test when Docker
  is unavailable — offline re-runs then only work within a single process.
- Inspect and clear:

```bash
docker compose exec redis redis-cli --scan --pattern 'ts:cache:gfw:*' | head
docker compose exec redis redis-cli --scan --pattern 'ts:cache:firms:*' | xargs -r docker compose exec -T redis redis-cli del
```

- Fixtures are intentionally **not committed**. Warm the cache with a live run, then use
  `--offline` for rehearsals; persist the Redis volume (`redisdata`) between runs.

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
