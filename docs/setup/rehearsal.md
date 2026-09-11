# M6 batch rehearsal runbook

How to produce the empirical throughput numbers behind `docs/kpi.md` and the cockpit KPI table.
The whole procedure is two commands: a live **prefetch** that warms the source cache and exports
fixtures, then an **offline run** that replays the batch from those fixtures with zero external
calls — so demo-day throughput is decoupled from GFW/FIRMS rate limits.

## Prerequisites

- `GFW_API_KEY` and `FIRMS_MAP_KEY` in `.env` (see [data-sources.md](./data-sources.md)).
- Postgres and Redis up and migrated:

```bash
pnpm db:up
pnpm db:upgrade
```

- `CACHE_BACKEND=redis` (the default) so the offline run primes the same cache the API uses.

## 1. Prefetch the cache (live, ~10 min at default limits)

```bash
pnpm rehearsal:prefetch --size 50 --as-of 2026-09-11 --concurrency 4
# or, directly:
uv run python -m terrasentry_api.rehearsal prefetch --size 50 --as-of 2026-09-11
```

- `--as-of` pins the FIRMS end date and the GFW year window for **both** the prefetch and the
  offline run. FIRMS cache keys are date-relative, so without a pin the fixtures expire at
  midnight; with a pin they stay valid across days.
- The prefetch respects the per-source limiters (`GFW_RATE_LIMIT_PER_MIN`,
  `FIRMS_RATE_LIMIT_PER_10MIN`). A 30-day FIRMS window is fetched in ≤5-day chunks, so 50 records
  is ~50 GFW + ~300 FIRMS requests.
- Fixtures are written to `data/fixtures/` automatically. Output is a JSON report with per-record
  wall time and any per-source errors; exit code is `1` if any record had a source error.
- Dry-run the plan first with `--dry-run` (no credentials or network needed).

## 2. Run the recorded batch offline (fast)

```bash
pnpm rehearsal:run --size 50 --as-of 2026-09-11 --report data/runs/batch-2026-09-11.json
# or, directly:
uv run python -m terrasentry_api.rehearsal run --offline --fixtures-dir data/fixtures \
  --as-of 2026-09-11 --report data/runs/batch-2026-09-11.json
```

- `--offline` makes a cache miss fail fast instead of calling a source; with the fixtures primed,
  `cache_stats.offline_misses` must be `0` on the report.
- The command runs the real `RunManager` against Postgres, so the batch is also visible in the
  cockpit and via `GET /batch-runs`.
- The JSON report contains the parent summary (`wall_clock_seconds`,
  `average/median/p95_seconds_per_record`, `throughput_records_per_second`, `verdict_breakdown`,
  `confusion`, `cache_stats`), per-record status/elapsed rows, and the host/concurrency settings.

## 3. Verify and record

Check the printed report for:

- `state=complete` and `breakdown {compliant: 30, high_risk: 12, ambiguous: 8}`;
- `confusion` diagonal = 30/12/8 (no expected archetype maps to a different verdict);
- `cache offline_misses=0` and `hits` equal to the number of prefetched source calls;
- wall clock within the demo window. If it is not, the batch is still demo-safe: trigger the
  offline run before the slot and show the persisted results (PRD section 9 fallback).

Copy the measured numbers into `docs/kpi.md` and append a progress-log line in
`docs/milestones.md`.

## Demo day with the live cockpit

```bash
CACHE_OFFLINE=true CACHE_FIXTURES_DIR=data/fixtures \
  REHEARSAL_AS_OF=2026-09-11 AGENT_MODEL=scripted pnpm dev
```

Set `REHEARSAL_AS_OF` to the same date used for the prefetch: the API then resolves identical
FIRMS/GFW windows for **both** scenario runs and batch records, so every source lookup is a cache
hit. The API primes fixtures at startup and reports `{ offline: true, fixtures_loaded: N }` on
`GET /health`; the cockpit shows the rehearsal badge. Queue the batch (and the two scenarios) from
the dashboard as usual. A cache miss under `CACHE_OFFLINE=true` fails fast instead of calling a
source, which surfaces a stale fixture set immediately.

## Without credentials

The full-50 path is test-verified offline: `apps/api/tests/test_batch_full.py` injects the design
signals and asserts the 30/12/8 breakdown, per-record persistence, and an offline fixture replay
with zero external calls. Live numbers in `docs/kpi.md` stay marked as pending the §3 Day-1 keys
until this runbook has been executed once with real credentials.
