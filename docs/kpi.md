# TerraSentry — KPI table (M6 empirical numbers)

**Status:** Live numbers pending §3 Day-1 data-source keys
**Date:** 2026-09-11
**Related:** [prd.md](./prd.md) §4.3/§5 · [milestones.md](./milestones.md) M6 · [setup/rehearsal.md](./setup/rehearsal.md)

This is the single source of truth for the throughput claims. Every row has a definition, a
target, and the machine-readable field in a batch report produced by
`python -m terrasentry_api.rehearsal run`. Values in the table are **measured**, never projected.
The dashboard KPI table (`apps/web/src/routes/index.tsx` + `components/kpi-table.tsx`) mirrors the
same rows for the latest completed batch.

## How a row gets a number

1. `pnpm rehearsal:prefetch --as-of <date>` warms the source cache with real GFW/FIRMS data and
   exports fixtures (`docs/setup/rehearsal.md`).
2. `pnpm rehearsal:run --offline --report data/runs/batch-<date>.json` replays the 50-record batch
   from cache and writes the report.
3. Copy the report fields into the "Live rehearsal" column, then update `docs/milestones.md`.

Until step 1 has real credentials, the "Offline design-signal test" column is the strongest
available evidence: `apps/api/tests/test_batch_full.py` runs the production runner over all 50
seed records with the source signals each archetype is designed to exercise.

## KPI table

| KPI | Definition | Target | Report field | Offline design-signal test | Local CLI smoke (mock fixtures, 2026-09-11) | Live rehearsal |
| --- | --- | --- | --- | --- | --- | --- |
| Batch wall clock | Parent run `started_at` → `finished_at` for all 50 records | Demo slot; if longer, pre-run and show results (PRD §9) | `summary.wall_clock_seconds` | asserted ≥ 0 | 0.872 s | pending §3 |
| Average per supplier | Mean per-record elapsed time | < 2 min (PRD §5) | `summary.average_seconds_per_record` | asserted ≥ 0 | 0.022 s | pending §3 |
| Median per supplier | p50 per-record elapsed time | recorded baseline | `summary.median_seconds_per_record` | asserted present | 0.018 s | pending §3 |
| P95 per supplier | Nearest-rank p95 per-record elapsed time | recorded baseline | `summary.p95_seconds_per_record` | asserted ≥ median | 0.061 s | pending §3 |
| Throughput | `record_count / wall_clock_seconds` | recorded baseline | `summary.throughput_records_per_second` | asserted present | 57.34 rec/s | pending §3 |
| Design match | Expected archetype maps to its intended verdict (confusion diagonal) | 30 compliant / 12 high-risk / 8 ambiguous, exact | `summary.confusion`, `summary.verdict_breakdown` | 30/12/8 exact | 30/12/8 exact | pending §3 |
| HITL under load | Ambiguous records paused for human review in the same batch | 8 held (`awaiting_review`) | `summary.states.awaiting_review` | 8 | 8 | pending §3 |
| ERP gatekeeping | Vendor status actions applied by the batch (approved / blocked / failed) | 30 approved / 12 blocked / 0 failed for released verdicts | `summary.sap_actions` | 30/12/0 asserted | 30/12/0 | pending §3 |
| Verifier coverage | Records accepted by the deterministic verify-before-write checks | 100% | `summary.states.failed` | 0 failed | 0 failed | pending §3 |
| Offline replay | External calls on a re-run from primed fixtures | 0 misses | `summary.cache_stats.misses` / `offline_misses` | asserted 0 on replay | 0 misses, 100 hits | pending real fixtures |
| Cycle acceleration | Manual pre-screen time vs system time per supplier | 98% (PRD §5) | n/a | baseline not defined | baseline not defined | pending baseline |

Notes:

- The CLI smoke values come from deterministic **mock** fixtures and a local Postgres/Redis; they
  validate the operational path and metric plumbing, not real API latency. Live rows remain
  pending the §3 GFW/FIRMS keys and are the only numbers suitable for demo claims.
- `total_record_seconds` (sum of worker time) is also recorded in the report for the
  concurrency-efficiency story: 1.081 s of worker time compressed into 0.872 s wall clock at
  `batch_concurrency = 4`.
- Cycle acceleration needs a documented manual baseline (minutes per supplier today). Do not
  publish a percentage until that baseline is agreed; the row stays "pending baseline".
- ERP gatekeeping runs through `SapActionService` (M7). Until SAP access lands, `SAP_MODE=stub`
  and every action carries `real: false` in `sap_actions` and the DDS `erpAction` extension;
  the count is real, the endpoint is a disclosed schema-accurate stub.

## Reproduce

```bash
# Full 50-record design-signal verification (no credentials): SQLite + respx
uv run pytest apps/api/tests/test_batch_full.py -q

# Live rehearsal (needs GFW_API_KEY/FIRMS_MAP_KEY)
pnpm rehearsal:prefetch --size 50 --as-of 2026-09-11 --concurrency 4
pnpm rehearsal:run --size 50 --as-of 2026-09-11 --report data/runs/batch-2026-09-11.json
```

Reports are gitignored (`data/runs/**`); the committed evidence is this table, the test suite,
and the progress log in `docs/milestones.md`.
