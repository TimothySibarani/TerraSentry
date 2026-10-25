# M6 batch rehearsal runbook

How to produce the empirical throughput numbers behind `docs/kpi.md` and the cockpit KPI table.
The whole procedure is two commands: a live **prefetch** that warms the source cache and exports
fixtures, then an **offline run** that replays the batch from those fixtures with zero external
calls — so demo-day throughput is decoupled from GFW/FIRMS rate limits.

## Prerequisites

- `GFW_API_KEY` and `FIRMS_MAP_KEY` in `.env` (see [data-sources.md](./data-sources.md)).
- SQLite audit schema initialized (no database servers needed):

```bash
pnpm db:upgrade
```

- `CACHE_BACKEND=sqlite` (the default), with `CACHE_SQLITE_PATH=data/sqlite/cache.db`.
- Stop the API before `rehearsal:run` on the same audit file. Each run manager's startup recovery
  assumes exclusive ownership of active runs. Restart the API after the CLI exits to view results.

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
- The command runs the real `RunManager` against SQLite, so the batch is also visible in the
  cockpit and via `GET /batch-runs`.
- The JSON report contains the parent summary (`wall_clock_seconds`,
  `average/median/p95_seconds_per_record`, `throughput_records_per_second`, `verdict_breakdown`,
  `confusion`, `cache_stats`), per-record status/elapsed rows, and the host/concurrency settings.

## 3. Verify and record

Check the printed report for:

- `state=complete`; record the measured verdict breakdown (30/12/8 is the injected design,
  not a promised distribution for live context layers);
- `confusion` records live drift from seed expectations; submitted records are unlabelled;
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
with zero external calls. The real-source prefetch and offline replay now have measured
numbers in `docs/kpi.md`; live SAP AI Core agent-batch timing remains a separate S3 gate.

## S2 fixture refresh

S2 fetches seven context layers in addition to loss/FIRMS for ID plots. Refresh all fixtures
with the current code and the same `--as-of` date before replaying; S1 fixtures are insufficient.
The repair version uses `geometry-v2` exact query identity and `clip-2` strict raster values.
Re-prefetch rather than reusing fixtures created under the old rounded identity/revision.
A configured operator is read at run acceptance and snapshotted on each child. Changes in
`/settings` affect subsequent runs, including offline runs, without changing pending reviews.
Production country is required for submitted records/import rows; use
[`data/templates/portfolio.csv`](../../data/templates/portfolio.csv) as the CSV header example.
Legacy submissions without country require resubmission. Run `pnpm db:upgrade` first.

Unsupported unsplit dateline polygons and dateline/polar point buffers require supported
split polygons. Annual loss beyond the verified release is an explicit data gap; the current
release ends in 2025. A clean 2027 assessment cannot treat missing 2026 coverage as compliant.
The historical live-source prefetch and PostgreSQL replay are recorded in `docs/kpi.md`;
live SAP AI Core agent-batch throughput remains a separate S3 verification gate.

## S3 agent-mode batches

`run` takes `--mode screening|agent` (default `screening`) and, for agent mode,
`--model scripted|sap` (default `AGENT_MODEL`). Agent mode runs the full graph per record
under `BATCH_AGENT_CONCURRENCY` (default 4, separate from `BATCH_CONCURRENCY`) and the report
records mode, model, concurrency actually used, per-record timings and graph-level token usage.

```bash
uv run python -m terrasentry_api.rehearsal run --size 10 --mode agent --model sap \
  --as-of 2026-09-11 --report data/runs/agent-batch.json
```

**Cost note:** every agent record is several model calls (three specialists, re-tasks on
signals, then the verifier). Record a bounded 10-record SAP AI Core batch first; only run 50
records live after checking the timing (the shared hackathon deployments have no published quota). Scripted agent batches make no model calls and
measure plumbing only.
