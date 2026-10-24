# TerraSentry — KPI table (M6 empirical numbers)

**Status:** S2 live source controls and 50-record fixture replay measured; no SAP AI Core agent number yet
**Date:** 2026-10-02
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

The 2026-10-02 live prefetch and offline replay of its real source fixtures are measured below.
Replay timings exclude network acquisition and LLM calls. The "Offline design-signal test" column
records controlled calibration evidence: `apps/api/tests/test_batch_full.py` runs the production runner over all 50
seed records with the source signals each archetype is designed to exercise.

## Reading this table after the review-flow change (2026-10-13)

High-risk verdicts are now held for a person instead of releasing and blocking the vendor on their own.
The "Local CLI smoke" and "Live rehearsal" columns were recorded before that change, so their
high-risk rows (state and ERP counts) describe the old behaviour; the verdicts, timings and cache
numbers are unaffected. The "Offline design-signal test" column is current: re-run it with
`uv run pytest apps/api/tests/test_batch_full.py -q`. Re-record the live columns with the commands
under "Reproduce" to refresh them. The raw reports from the 2026-10-02 rehearsal were written to
temporary folders that no longer exist, so the live column cannot be re-derived from the repository
until the rehearsal is run again; keep the report this time by passing `--report docs/evidence/<name>.json`.

## KPI table

| KPI | Definition | Target | Report field | Offline design-signal test | Local CLI smoke (mock fixtures, 2026-09-11) | Live rehearsal |
| --- | --- | --- | --- | --- | --- | --- |
| Batch wall clock | Parent run `started_at` → `finished_at` for all 50 records | Demo slot; if longer, pre-run and show results (PRD §9) | `summary.wall_clock_seconds` | asserted ≥ 0 | 0.872 s | 6.617 s replay |
| Average per supplier | Mean per-record elapsed time | < 2 min (PRD §5) | `summary.average_seconds_per_record` | asserted ≥ 0 | 0.022 s | 0.155 s replay |
| Median per supplier | p50 per-record elapsed time | recorded baseline | `summary.median_seconds_per_record` | asserted present | 0.018 s | 0.052 s replay |
| P95 per supplier | Nearest-rank p95 per-record elapsed time | recorded baseline | `summary.p95_seconds_per_record` | asserted ≥ median | 0.061 s | 0.854 s replay |
| Throughput | `record_count / wall_clock_seconds` | recorded baseline | `summary.throughput_records_per_second` | asserted present | 57.34 rec/s | 7.556 rec/s replay |
| Design match | Expected archetype maps to its intended verdict (confusion diagonal) | Injected design 30/12/8; measure actual live drift | `summary.confusion`, `summary.verdict_breakdown` | 30/12/8 exact | 30/12/8 exact | Real fixtures: 1 compliant / 35 high-risk / 14 ambiguous |
| Held for review under load | Ambiguous **and high-risk** records paused for a person in the same batch (high-risk was auto-released before 2026-10-13) | 20 held on the injected 30/12/8 design (8 ambiguous + 12 high-risk) | `summary.states.awaiting_review` | 20 | 20 | 14 held on the 2026-10-02 replay (that run predates the high-risk hold; it would be 49 of 50 today) |
| ERP gatekeeping | Vendor status actions applied by the batch (approved / blocked / failed). Only compliant verdicts act on their own; held runs act after a decision | 30 approved / 0 blocked / 0 failed (compliant only; 20 held) | `summary.sap_actions` | 30/0/0 asserted | 30/12/0 (before the hold) | 1 approved / 35 blocked / 0 failed (stub; before the hold) |
| Verifier coverage | Records accepted by the deterministic verify-before-write checks. In screening mode no model runs, so this passes by construction; it is only a meaningful measure in agent mode, where the coverage check can reject a run | 100% | `summary.states.failed` | 0 failed | 0 failed | 0 failed (screening) |
| Offline replay | External calls on a re-run from primed fixtures | 0 misses | `summary.cache_stats.misses` / `offline_misses` | asserted 0 on replay | 0 misses, 100 hits | 0 misses / 450 hits |
| Cycle acceleration | Manual pre-screen time vs system time per supplier | 98% (PRD §5) | n/a | baseline not defined | baseline not defined | pending baseline |

Notes:

- The CLI smoke values come from deterministic **mock** fixtures and a local Postgres/Redis; they
  validate the operational path and metric plumbing, not real API latency. Current live
  rehearsal rows measure replay of actual GFW/FIRMS fixtures; acquisition is separately
  reported below. They are not live agent-batch throughput.
- `total_record_seconds` (sum of worker time) is also recorded in the report for the
  concurrency-efficiency story: 1.081 s of worker time compressed into 0.872 s wall clock at
  `batch_concurrency = 4`.
- Cycle acceleration needs a documented manual baseline (minutes per supplier today). Do not
  publish a percentage until that baseline is agreed; the row stays "pending baseline".
- ERP gatekeeping runs through `SapActionService` (M7). Until SAP access lands, `SAP_MODE=stub`
  and every action carries `real: false` in `sap_actions` and the DDS `erpAction` extension;
  the count is real, the endpoint is a disclosed schema-accurate stub.

## Batch modes (S3)

Every batch is labelled with the mode it actually ran, and KPI rows must say which:

| Mode | What runs | Concurrency | Report fields |
| --- | --- | --- | --- |
| `screening` | Rubric + deterministic verifier, no LLM (all rows above) | `BATCH_CONCURRENCY` | `summary.mode = screening`, `summary.model = null` |
| `agent` | Full agent graph per record (screening, re-tasked deep dives, coverage-checked verifier) | `BATCH_AGENT_CONCURRENCY` | `summary.mode = agent`, `summary.model`, `summary.metrics.token_usage` (graph-level only) |

`summary.unlabelled_count` counts submitted records without a design label; the confusion
matrix and design match use labelled records only. No agent-mode live number is recorded yet (the runbook and a table to fill in are in [evidence/README.md](./evidence/README.md)):
the bounded 10-record SAP AI Core rehearsal is an open S3 gate, and scripted agent batches only
validate plumbing, not model latency or cost.

## Reproduce

```bash
# Full 50-record design-signal verification (no credentials): SQLite + respx
uv run pytest apps/api/tests/test_batch_full.py -q

# Live rehearsal (needs GFW_API_KEY/FIRMS_MAP_KEY)
pnpm rehearsal:prefetch --size 50 --as-of 2026-09-11 --concurrency 4
pnpm rehearsal:run --size 50 --as-of 2026-09-11 --report data/runs/batch-2026-09-11.json

# Agent mode (scripted validates plumbing; sap is the live measurement)
uv run python -m terrasentry_api.rehearsal run --size 10 --mode agent --model sap \
  --as-of 2026-09-11 --report data/runs/agent-batch.json
```

Reports are gitignored (`data/runs/**`); the committed evidence is this table, the test suite,
and the progress log in `docs/milestones.md`.

## S2 live probe evidence (2026-10-02)

All seven context layers, full-cutoff loss and FIRMS passed preflight on two overlap plots
and an ID urban control. Layer-only cold timings were 5.648 / 4.477 / 7.565 s; each warm
replay took 0.001 s. Loss p50/p95 was 2.92/2.93 s, FIRMS 0.76/1.47 s (three samples).
These are small-sample probes, not 50-record throughput measurements.

The production scripted API with live sources and configured operator returned:

| Public test plot | Verdict | Key overlap | API elapsed |
| --- | --- | --- | --- |
| Tanjung Puting WDPA | High risk | WDPA 30.73017 ha; moratorium 30.73017 ha | 10.424 s |
| Identified moratorium feature | High risk | Moratorium 4.91762 ha; WDPA 0 ha | 9.809 s |
| Jakarta urban control (ID) | Compliant | WDPA/moratorium 0 ha | 9.299 s |
| São Paulo urban control (BR) | Compliant | WDPA 0 ha; ID-only checks not applicable | 6.234 s |

Both high-risk plots had **zero observed 2021–2025 loss and zero fire detections**;
legality context alone caused the critical verdict. Cold timings include network/retry
variation. The injected 50-record harness still produces 30/12/8 with rubric 1.1.0 and
explicit clear context fixtures. Earlier loss/FIRMS-only fixture numbers above are historical
S1 measurements; the current full-source rehearsal is recorded below.

A warm production API replay took **0.465 s**, with all 12 GFW/FIRMS/context evidence
entries marked cached and no source requests on the cache-hit branches. A live BR point
control was compliant; original point/declared area and derived query-buffer provenance
remained distinct through DDS export.

## S2 repair closeout rehearsal (2026-10-02)

Live 50-record prefetch at concurrency 4 took **347.462 s**, averaging **26.917 s** of
source acquisition per record, with **450 fixtures**, **zero source errors**, and **72 MiB**
of fixture files. Records use the accepted `2026-10-02` date and 2021–2025 loss coverage.
The migrated PostgreSQL 17 / memory-cache screening replay (`batch-de3bbbf2a49d`) completed
in **6.617 s**, with **450 hits / zero misses / zero writes**, 36 released results and 14
held for review. Actual verdicts are **1 compliant / 35 high-risk / 14 ambiguous**. That is
measured drift from seeded expectations; the injected 30/12/8 test remains unchanged.

Confusion rows (actual compliant / high-risk / ambiguous): expected compliant **1/18/11**;
expected high-risk **0/12/0**; expected ambiguous **0/5/3**. Source acquisition and cached
screening timings must be presented separately. No live LLM was used in this batch.

Fresh source preflight passed all three positive/control plots. The production scripted
API repeated expected WDPA/moratorium high-risk and ID/BR compliant outcomes in
**9.940 / 10.339 / 9.823 / 12.342 s**, with matching operator/country in DDS JSON/XML.
The BR point control preserved point/declaration versus derived query provenance and
equal cold/warm fingerprints, at **12.944 / 0.371 s**. Actual WDPA context serialization
shrank from **358,727 to 3,143 bytes** for the model while full geometry remains in evidence.

Working artifacts: `/tmp/ts-s2-repair-prefetch-50.log`, `/tmp/ts-s2-repair-fixtures`,
`/tmp/ts-s2-repair-offline-50.json`, `/tmp/ts-s2-repair-preflight/`,
`/tmp/ts-s2-repair-api-smoke.log`, `/tmp/ts-s2-repair-point.json`. Fixture identity is
`geometry-v2` and context query revision is `clip-2`; refresh old fixtures before replay.

**Historical (measured on Amazon Bedrock, which was removed on 2026-10-13; these say nothing
about SAP AI Core timing).** After fresh AWS login, both Bedrock preflight roles passed. Final-code
production runs with the then-configured default Bedrock model completed with accepted verification and configured-operator
DDS: WDPA **43.659 s / 23 steps / high-risk** (`run-0647f39f0be5`); clean ID control
**45.626 s / 21 steps / compliant** (`run-3cd3c56a43e6`). These are single-record live
agent timings, not S3 agent-batch throughput. Artifacts:
`/tmp/ts-s2-closeout-bedrock-results.json` and `/tmp/ts-s2-closeout-bedrock-*.json`.
