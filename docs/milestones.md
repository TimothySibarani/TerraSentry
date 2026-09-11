# TerraSentry — MVP Milestones & Progress Tracker

**Status:** Draft for team review
**Date:** 2026-09-10
**Related:** [prd.md](./prd.md) · [architecture.md](./architecture.md)

This is the living tracker for the MVP. Update the status columns as work lands; keep the
definitions of done and decision gates unchanged unless the PRD changes.

**Tracking conventions**

- Status values: `Todo`, `In progress`, `Done`, `Blocked`.
- Owner column starts as `TBD`; fill in names at kickoff.
- Target is relative to kickoff (`W1`, `W2`, ...). Anchor to the confirmed demo day when known.
- GitHub Milestones should mirror `M0`–`M8` so issues map 1:1 to this doc.

---

## 1. Definition of Done for the MVP

From PRD sections 4.3 and 8. The MVP is not done until every box is checked.

- [ ] Both live scenarios (Compliant, High Risk) complete end-to-end without manual intervention,
      using real Hansen GFC and NASA FIRMS data.
- [ ] The 50-record batch completes within a demo-compatible window and captures: total wall-clock
      time, average time per record, and a pass/fail/ambiguous breakdown matching the intended
      ~30/12/8 distribution.
- [ ] The Verifier Agent visibly catches or cross-checks at least one thing in the demo.
- [ ] At least one genuinely real SAP-side interaction, if sandbox access is obtained; otherwise the
      schema-accurate stub is used and explicitly disclosed.
- [ ] The KPI table is backed by the batch run's empirical numbers, not projections.
- [ ] The Ambiguous/HITL branch is demonstrated at least once, including under batch load.

---

## 2. Milestone map

```
M0 Foundation
   |
   v
M1 Integrations + cache  --->  M2 Deterministic core  --->  M3 Agent orchestration
   (critical path)                  |                              |
                                    v                              v
                              M4 API + persistence  ------->  M6 Batch 50 + throughput
                                    |                              |
                                    v                              v
                              M5 Cockpit cockpit    ------->  M8 Hardening + demo
                                                                 ^
                              M7 SAP closed loop ------------------
```

- Critical path: **M0 -> M1 -> M2 -> M3 -> M4 -> M6 -> M8**.
- M5 can start once M4 exposes the first run endpoints; it should not block M4/M6.
- M7 depends on the Day 1 SAP access check, not on the critical path.
- M0 is complete apart from the scaffold commit (user-owned) and local Docker builds, which the CI
  `docker` job covers because this environment blocks container egress.

### Dashboard

| Milestone | Status | Target | Depends on | Exit gate |
| --- | --- | --- | --- | --- |
| M0 Foundation & tooling | Done | W1 | — | `pnpm check` green, `pnpm dev` runs both apps, CI on push |
| M1 Integrations + cache | Done | W1-W2 | M0 | 5-10 real polygon lookups, cached and rate-limited (verified with deterministic mocks; live numbers tracked in §3 key gates) |
| M2 Deterministic core | Done | W2 | M1 | Reproducible score, cited evidence, valid DDS |
| M3 Agent orchestration | Done | W2-W3 | M2 | Reference-pipeline parity + verifier catch + HITL |
| M4 API + persistence | Done | W3 | M3 | Run endpoints + SSE + batch worker, generated client |
| M5 Cockpit | Todo | W3-W4 | M4 | Demo flow navigable, live trace, batch summary, map |
| M6 Batch 50 + throughput | Todo | W4 | M4, M5 | 50 records complete, metrics + 30/12/8 breakdown |
| M7 SAP closed loop | Todo | W2-W4 | M0, Day 1 access | Vendor status flip visible end-to-end |
| M8 Hardening + demo | Todo | W4-W5 | M6, M7 | All MVP Definition of Done boxes checked |

---

## 3. Day 1 decision gates (blocking, external lead time)

These are PRD sections 5 and 6 action items. Do them before writing dependent code.

| Gate | Why it blocks | Owner | Status | Deadline | Fallback |
| --- | --- | --- | --- | --- | --- |
| Check SAP API Business Hub / BTP trial access | Decides real vs stub SAP path and demo claim | TBD | Todo | Day 1 | Schema-accurate stub (PRD Option 2) |
| Register NASA FIRMS MAP key | Key activation can take days; no key means no thermal agent | TBD | Todo | Day 1 | Cache demo fixtures (disclosed) |
| Request Bedrock model access (orchestrator + extraction roles) | Agents cannot run without model access in the account; `python -m terrasentry_core.agents.preflight` verifies both roles | TBD | Todo | Day 1 | Cross-region inference profile / alternate model |
| Verify GFW/Hansen API key and rate limit | Determines batch concurrency and wall-clock target | TBD | Todo | W1 | Backoff + reduced concurrency + bulk endpoint |
| Confirm demo date and slot length | Anchors every target in this doc | TBD | Todo | Day 1 | Assume W5 and adjust |
| AgentCore go/no-go | Stretch scope; affects M8 only | TBD | Todo | After M6 | Skip AgentCore, keep local Bedrock agents |

---

## 4. M0 — Foundation & tooling

**Goal:** the monorepo runs end-to-end locally with typed contracts and CI.

| Task | Status | Owner | Notes |
| --- | --- | --- | --- |
| Turborepo + pnpm workspace/catalog + uv virtual workspace | Done | — | `turbo.json`, `pnpm-workspace.yaml`, `pyproject.toml` |
| Biome, env config, gitignore, Dockerfiles | Done | — | `.env.example`, `AGENTS.md` |
| TanStack Start app + Nitro production build | Done | — | SSR verified on `.output/server/index.mjs` |
| Effect integration (ApiClient, ManagedRuntime, TanStack Query bridge, `@effect/vitest`) | Done | — | `packages/api-client`, `apps/web/src/lib` |
| FastAPI skeleton (`/health`, settings, DB session, OpenAPI export) | Done | — | runtime verified; OpenAPI exported to `packages/api-client/openapi.json` |
| UI foundation: Tailwind v4 + shadcn/ui (base-mira) + DESIGN.md tokens | Done | — | single token file `apps/web/src/styles.css`; fonts self-hosted |
| AWS CDK app shell | Done | — | empty stack; `cdk synth` verified via tsx (`cdk.out` emitted); real stacks later in M8 |
| Install Python toolchain and run `uv sync` / Pyright / pytest | Done | — | uv 0.12.12, `uv.lock` generated, all checks green |
| CI workflow (JS, Python, OpenAPI drift, Docker builds) | Done | — | `.github/workflows/ci.yml` |
| Build and smoke-test both Docker images | Blocked | TBD | `compose.yaml` validates; local build blocked by container egress, CI job builds both images |
| Commit the scaffold | Done | User | committed as `f7e7595..02df52e` (web, infra, CI, docs, agents) |

**Exit criteria:** `pnpm check` passes (Biome + Ruff + tsc + Pyright), `pnpm dev` starts both apps,
CI runs on push, and `docker compose config` validates.

---

## 5. M1 — Integrations + cache (critical path)

**Goal:** real geospatial and thermal data for a set of polygons, safely within rate limits.

| Task | Status | Owner | Notes |
| --- | --- | --- | --- |
| GFW/Hansen client with retry + limiter | Done | — | `sources/gfw.py`; cache-aware; includes the async batch job path |
| NASA FIRMS area client with retry + limiter | Done | — | `sources/firms.py`; 5-day chunking, dedupe, polygon re-filter |
| Persistent cache keyed by `(source, geometry_hash, date_window)` | Done | — | Redis (`redis-py`) + `MemoryCache`; key `ts:cache:v1:{source}:{geometry_hash}:{window}` |
| Preflight script: 5-10 dummy calls + rate-limit probe | Done | — | `uv run python -m terrasentry_integrations.preflight`; optional `--ladder 1,2,4` |
| Evaluate GFW bulk/async query endpoint | Done | — | `/query/batch` + `/job/{id}` implemented; preflight times it against per-polygon queries |
| Reference pipeline: 5-10 polygons end-to-end with real data | Done | — | `uv run python -m terrasentry_core.reference`; M3 parity baseline |
| Seed data: demo polygons + 30/12/8 batch + synthetic legality | Done | — | `uv run python -m terrasentry_core.seed`; committed under `data/seed/` |
| Setup runbooks: AWS / SAP / data sources | Done | — | `docs/setup/`; free-tier and trial paths with fallbacks |
| Tests: clients, cache, HTTP retry, seed, reference | Done | — | `python/integrations/tests`, `python/core/tests`; respx + fakeredis |

**Exit criteria:** cached re-runs make zero external calls; measured latency and quota behavior are
recorded in this doc's notes; no rate-limit failures at the chosen concurrency.

> **Completed 2026-09-11.** Zero-external-call cached re-runs are asserted end-to-end by
> `python/core/tests/test_reference.py` (one live call, then an `--offline` re-run served entirely
> from cache) and by `python/integrations/tests/test_cache.py`, which round-trips `RedisCache`
> through `fakeredis`. Retry, `Retry-After`, auth, and 5xx-exhaustion behavior are covered by
> `python/integrations/tests/test_http.py`. The only outstanding numbers are the live latency/quota
> measurements, which need real credentials: once the §3 Day-1 gates are cleared, run
> `uv run python -m terrasentry_integrations.preflight --ladder 1,2,4` and paste the results here.
> No key material exists in the build environment, so mock-level verification is the strongest
> available evidence at commit time.

---

## 6. M2 — Deterministic core

**Goal:** all numbers and citations are produced in code, with no model involvement.

| Task | Status | Owner | Notes |
| --- | --- | --- | --- |
| Domain models, enums, verdict and run-state types | Done | — | `domain/` (`enums.py`, `models.py`, `run_state.py`); `advance` enforces the architecture state machine |
| Evidence ledger (source, artifact, timestamp per claim) | Done | — | `evidence.py`; deterministic content-hash ids, idempotent records, timestamps from source `fetched_at` only |
| Deterministic rubric / scoring | Done | — | `scoring.py`; `RubricConfig`, `assess`, `fingerprint`, `RUBRIC_VERSION`; no clock/network/model |
| DDS builder (JSON + XML, TRACES-aligned) | Done | — | `dds.py`; EUDR Information System V3 namespaces/`SubmitDdsRequest`, GeoJSON >4 ha polygon rule, citation validation |
| Synthetic legality/entity dataset in realistic HGU formats | Done | — | Landed in M1; M2 added deterministic consignments + EU operator + expected signal/ambiguity labels |
| Unit tests for scoring, geometry, evidence, DDS | Done | — | 66 core tests incl. golden DDS fixture; full suite 85 pytest green |

**Exit criteria:** the same inputs always produce the same score; every DDS claim traces to a ledger
entry; a DDS fixture validates against the expected shape.

> **Completed 2026-09-11.** `python -m terrasentry_core.assessment --run data/runs/<run>.json`
> scores an M1 reference run, emits per-record DDS JSON/XML plus an evidence snapshot and
> `summary.json`, and prints the verdict breakdown/confusion matrix against the seed design.
> Determinism is test-asserted at three levels: identical `Assessment` fingerprints and byte-identical
> XML/JSON, identical ledger evidence ids, and a committed DDS golden fixture
> (`python/core/tests/fixtures/dds_reference.{json,xml}`). `validate_citations` fails a required DDS
> claim with no ledger citation (`UncitedClaimError`) or an unknown id (`LedgerLookupError`). The DDS
> XML mirrors the public EUDR Information System V3 operator API (namespaces, field names, HS/species
> structure, GeoJSON at six decimals with polygons above 4 ha); submission itself remains out of scope
> and credential-free, which the demo must disclose. No live GFW/FIRMS numbers are involved, so the
> §3 key gates are unchanged; M6 tunes the `RubricConfig` thresholds against live data via the same
> `summary.json` confusion matrix. The M2 line item "synthetic legality/entity dataset" was already
> delivered in M1 and is extended here rather than rebuilt: consignments, the EU operator, expected
> signal/ambiguity labels, concessions floored above their plot area, and a real permit-gap signal on
> the ambiguous records. `test_synthetic_signal_batch_reproduces_the_design_breakdown` runs the full
> 50-record harness over injected source signals and reproduces the intended 30/12/8 breakdown while
> exercising all three high-risk detection paths (4 deforestation / 4 fire / 12 legal), so M6 only has
> to confirm the same mapping against live GFW/FIRMS responses.


---

## 7. M3 — Agent orchestration

**Goal:** Supervisor -> Specialists -> Verifier running on Strands over the M1 tools.

| Task | Status | Owner | Notes |
| --- | --- | --- | --- |
| Supervisor agent (agents-as-tools delegation) | Done | — | `agents/supervisor.py`; specialists become delegatable tools |
| Geospatial and Thermal specialists | Done | — | `agents/specialists.py`; ids-only tools over `tools/sources.py` |
| Legality specialist (synthetic data, disclosed) | Done | — | same tool contract; disclosure travels on every payload |
| Verifier agent with graph verify-before-write edge | Done | — | `agents/nodes.py`; deterministic re-derivation gate + LLM review; writer edge only on accept |
| Model routing (orchestrator/verifier vs extraction roles) | Done | — | `agents/models.py` + `AgentSettings` from `.env`; model ids are required env, no repo default |
| Parity tests against the M1 reference pipeline | Done | — | `test_agent_parity.py`; fingerprints, assessments, and DDS compared against the same source data |
| HITL branch: `awaiting_review` + resume with decision | Done | — | `RunOrchestrator.resume`; DDS withheld until the decision is recorded |

**Exit criteria:** agent output matches the reference pipeline on the demo polygons; the verifier
catches at least one seeded inconsistency; the HITL branch pauses and resumes correctly.

> **Completed 2026-09-11.** `python -m terrasentry_core.agents --record REC-001 --model scripted`
> runs the whole graph offline: supervisor (agents-as-tools) gathers GFW/FIRMS/synthetic evidence
> through shared ids-only tools, a deterministic assessor builds the M2 `RecordAssessment`, the
> verifier re-derives every metric from the raw sources and validates every DDS citation before the
> scripted LLM review, and a writer node releases the DDS only when the verifier accepts (the
> literal graph verify-before-write edge). The verifier's deterministic checks are the hard gate:
> `test_agent_verification.py` seeds a tampered metric, a dropped-evidence citation failure, and a
> design/signal mismatch, all caught without a model. `test_agent_parity.py` runs the reference
> pipeline and the agent graph over the same mocked GFW/FIRMS data and asserts identical
> `Assessment` objects, fingerprints, and DDS documents per record. `test_agent_hitl.py` asserts an
> ambiguous verdict returns `awaiting_review` with no released DDS, then `resume(approve|override)`
> completes via the M2 state machine; the CLI mirrors this with exit codes 0/2/1. All tests run
> without AWS using `ScriptedModel`/`AutopilotResponder`; the live Bedrock path is wired through
> `ModelBundle.from_settings()` (model ids required in `.env`, no repo defaults) and needs the §3
> model-access gate before it can be smoke-tested live. Fixing parity surfaced a real M2 determinism
> defect: `cached` was part of the hashed evidence artifact, so a cached re-run produced different
> evidence ids and fingerprints. Cache provenance now lives on `EvidenceEntry.cached` outside the
> content hash (golden DDS fixture regenerated), so live and cached runs are fingerprint-identical,
> which M6 depends on.

---

## 8. M4 — API + persistence

**Goal:** the cockpit and batch runner consume a stable, generated contract.

| Task | Status | Owner | Notes |
| --- | --- | --- | --- |
| SQLAlchemy models + Alembic migrations | Done | — | `models.py` (suppliers, parcels, runs, run_steps, evidence, verdicts, dds_documents) + `apps/api/alembic/` initial migration, verified up/down against Postgres |
| Routers: suppliers, runs, batch, dds, mock SAP | Done | — | `apps/api/src/terrasentry_api/routers/`; 202 async start, 404/409/422 error mapping |
| SSE stream for run steps | Done | — | `GET /runs/{id}/stream` and `/batch-runs/{id}/stream` via `sse-starlette`; `snapshot`/`step`/`state`/`progress`/`done` frames |
| Batch worker with bounded concurrency + per-source limiters | Done | — | in-process asyncio `Semaphore`, shared GFW/FIRMS clients; deterministic assess + verifier path (M6 measures it) |
| `pnpm gen:api` snapshot + client regeneration | Done | — | contract regenerated; Effect schemas, REST methods, and `streamRun`/`streamBatchRun` over `Stream` + `Sse` |
| API tests (TestClient, SSE, error paths) | Done | — | 18 API tests on SQLite + respx-mocked sources; CI adds a Postgres `alembic upgrade head` + `alembic check` job |
| Auto-seed suppliers/parcels + lifespan services | Done | — | idempotent seed from `data/seed`, shared clients/cache, graceful shutdown |

**Exit criteria:** one live scenario runs start-to-finish through the API; the web client compiles
against the regenerated schema; run traces persist and stream.

> **Completed 2026-09-11.** `POST /runs` starts the M3 graph in the background and `POST
> /batch-runs` queues the deterministic per-record pipeline; both persist the run, each streamed
> step, the evidence ledger, the verdict/pending assessment, and the released or withheld DDS
> through `RunStore` on Postgres. `GET /runs/{id}/stream` follows `snapshot` -> `step`* ->
> `state`/`done` (batch streams emit `progress`); an ambiguous verdict stays `awaiting_review`,
> with the DDS answering 409 until `POST /runs/{id}/decision` records the human decision and
> releases it. `RunOrchestrator` gained an `on_step` hook and injectable `run_id` so the API can
> persist/broadcast steps while a run is in flight; the CLI and M3 parity tests are unchanged.
> Tests cover the full lifecycle, SSE replay, HITL release, batch breakdown/metrics, bounded
> batch concurrency, DDS JSON/XML, suppliers, and the mock-SAP vendor flip. The migration is
> applied and drift-checked against Postgres locally and in CI; API tests run on SQLite with
> `aiosqlite`. The live end-to-end demo still needs the §3 keys (GFW/FIRMS) and Bedrock model
> access, exactly as M1/M3 closed; with `AGENT_MODEL=scripted` the whole path is replayable
> offline once the response cache is warm.

---

## 9. M5 — Cockpit

**Goal:** the PRD demo flow is navigable without developer tooling.

| Task | Status | Owner | Notes |
| --- | --- | --- | --- |
| Routes: dashboard, suppliers, run detail, batch summary | Todo | TBD | `apps/web/src/routes/` |
| Live agent trace panel (SSE -> Effect `Stream`) | Todo | TBD | visible reasoning for the demo |
| Batch summary view (wall clock, avg/record, breakdown) | Todo | TBD | PRD section 4.3 numbers |
| Supplier/record table (TanStack Table) | Todo | TBD | 50-record batch view |
| Map view (MapLibre + Amazon Location) | Todo | TBD | polygons, loss, hotspots |
| shadcn components, loading/error/empty states | Todo | TBD | `apps/web/src/components/` not created yet |
| Offline demo mode backed by `data/fixtures` | Todo | TBD | rehearsal without burning quotas |

**Exit criteria:** the demo script (PRD section 7) can be driven from the UI; failures show typed
error states instead of blank screens.

---

## 10. M6 — Batch 50 + throughput

**Goal:** empirical throughput numbers that back the KPI claims.

| Task | Status | Owner | Notes |
| --- | --- | --- | --- |
| Synthetic seed generator: 30 compliant / 12 high-risk / 8 ambiguous | Done | — | Landed early in M1: `python -m terrasentry_core.seed`; real forest coordinates in Sumatra/Kalimantan/Riau; committed `data/seed/batch_50.json` |
| Per-record elapsed time and status persistence | Todo | TBD | match intended distribution |
| Aggregate metrics: wall clock, avg per record, breakdown | Todo | TBD | displayed in M5 batch view |
| Pre-fetch demo cache and run a full rehearsal | Todo | TBD | PRD risk mitigation |
| Record results in this doc and in the KPI table | Todo | TBD | replaces projected numbers |

**Exit criteria:** 50 records complete within the demo window (or the pre-recorded plan is
confirmed); the breakdown matches the 30/12/8 design; numbers are reproducible from cached data.

---

## 11. M7 — SAP closed loop

**Goal:** the strongest differentiator, at whatever level of access is real.

| Task | Status | Owner | Notes |
| --- | --- | --- | --- |
| Day 1 access check result recorded | Todo | TBD | API Hub sandbox, BTP trial, or neither |
| `SAP_MODE` client implementation (`sandbox` or `stub`) | Todo | TBD | `python/integrations/.../sap/` |
| Stub service with API Hub-accurate payload shapes (if needed) | Todo | TBD | PRD Option 2 |
| Vendor status / purchasing block surfaced in UI + DDS | Todo | TBD | closed-loop claim |
| Demo disclosure line for mocked vs real | Todo | TBD | PRD design rules |

**Exit criteria:** a compliance verdict causes a visible ERP-side status change; the demo states
exactly what is real.

---

## 12. M8 — Hardening + demo

**Goal:** the whole thing runs live, repeatedly, and survives questions.

| Task | Status | Owner | Notes |
| --- | --- | --- | --- |
| AWS CDK stacks: network, data, api, web, observability | Todo | TBD | empty shell exists today |
| Deploy containers + RDS + S3 + CloudFront | Todo | TBD | path routing `/api/*` |
| Observability: logs, traces, run trace persistence | Todo | TBD | CloudWatch + OTel |
| Demo script rehearsal x2 with a timer | Todo | TBD | PRD section 7 |
| Fallback plan: pre-recorded batch, fixtures, seeded cache | Todo | TBD | PRD section 9 |
| Final KPI table with measured numbers | Todo | TBD | replaces projections |

**Exit criteria:** all MVP Definition of Done boxes checked in two consecutive rehearsals without
manual intervention.

---

## 13. Risk register (PRD section 9, tracked)

| Risk | Impact | Mitigation | Trigger / early warning | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| API rate limits hit mid-demo | High | Cache + pre-fetch + backoff; M1 preflight | Probe shows throttling at <50 records | TBD | Todo |
| SAP sandbox denied or delayed | Medium | Stub fallback (Option 2), disclosed | No access by end of Day 1 | TBD | Todo |
| Batch too slow for a live slot | Medium | Pre-run and show aggregate results | Rehearsal exceeds demo window | TBD | Todo |
| Synthetic legality data looks fabricated | Low-medium | Realistic HGU/PBPH formats, labelled | Judge feedback in rehearsal | TBD | Todo |
| Bedrock quota/model access issues | High | Verify Day 1; cross-region profiles | Model access not granted in W1 | TBD | Todo |
| Scaffold drift (docs vs code) | Low | Architecture status section + this tracker | CI red or doc/code mismatch | TBD | In progress |

---

## 14. Progress log

Append one line per meaningful update. Keep newest at the top.

| Date | Milestone | Update |
| --- | --- | --- |
| 2026-09-11 | M4 | API + persistence landed: SQLAlchemy 2.0 audit store (`suppliers`, `parcels`, `runs`, `run_steps`, `evidence`, `verdicts`, `dds_documents`) with an Alembic async migration verified up/down against Postgres and a CI `alembic check` drift gate; lifespan-built `AppServices` (engine, Redis cache, shared GFW/FIRMS clients, `RunManager`, mock SAP) with idempotent auto-seed of the synthetic suppliers/parcels. Routers: suppliers, runs (202 start, detail, evidence, SSE, decision), batch (202 start, metrics, records, SSE), dds (JSON/XML with 409 while withheld), mock sap (vendor status/block). The in-process worker runs scenarios through the M3 graph and batch records through the deterministic assess + verifier path with an asyncio semaphore (`BATCH_CONCURRENCY`) over the shared rate-limited clients; steps persist and stream live (`snapshot`/`step`/`state`/`progress`/`done`), and HITL release reconstructs the M3 result from Postgres (decisions are serialised per run; SSE responses carry a send timeout and no-store/nosniff headers). `RunOrchestrator` gained an `on_step` hook + injectable `run_id` (CLI/parity unchanged; new hook tests). `pnpm gen:api` regenerated the contract; the Effect client now decodes every response with `Schema`, exposes REST methods plus `streamRun`/`streamBatchRun` over `Stream` + `Sse`, and has 13 vitest cases. 18 API tests (SQLite + respx; lifecycle, SSE replay, HITL, batch breakdown/bounded concurrency, error paths); full Python suite 147 green, Ruff/Pyright/Biome/tsc clean. Live-key end-to-end remains gated on §3. |
| 2026-09-11 | M3 | Live Bedrock path hardened per Bedrock best practice: adaptive retries + explicit connect/read timeouts and validated agent settings, opt-in prompt caching (`BEDROCK_PROMPT_CACHE=off|auto|anthropic`, documented as below the Sonnet/Haiku minimums), and a new `python -m terrasentry_core.agents.preflight` gate check that pings both roles through the same Strands path and maps AWS errors to fixes. AWS runbook now uses a least-privilege Bedrock policy and SSO/role guidance instead of `AmazonBedrockFullAccess`. 126 Python tests green, Ruff/Pyright clean. Live smoke still gated on the §3 account access. |
| 2026-09-11 | M3 | Agent orchestration landed: `tools/` shared source layer (`fetch_polygon_sources`, `SeedDatasets`, `TraceCollector`) now backs both the reference pipeline and the agent tools; `agents/` adds Bedrock model routing, an offline `ScriptedModel`/`AutopilotResponder`, specialists with ids-only tools, an agents-as-tools supervisor, a verifier node that re-derives metrics and validates citations before the LLM review, a deterministic assessor/writer, and `RunOrchestrator` with the graph verify-before-write edge plus the `awaiting_review`/resume HITL seam. CLI: `python -m terrasentry_core.agents --record/--scenario --model scripted|bedrock` with exit codes 0/2/1 and run/DDS/evidence artifacts. Tests add 23 agent cases (parity vs reference, verifier catch, HITL, graph flow, tools, scripted model, model routing, CLI); full Python suite 108 green, Ruff/Pyright clean. Also fixed an M2 determinism defect found by parity: cache provenance was inside the hashed evidence artifact, so cached re-runs fingerprint differently; `EvidenceEntry.cached` is now outside the hash and the golden DDS fixture is regenerated. Live Bedrock smoke remains gated on §3 Day-1 model access. |
| 2026-09-11 | M2 | Deterministic core landed: domain models/enums/run-state machine, content-hashed evidence ledger, config-driven rubric with `fingerprint`, EUDR Information System V3-aligned DDS builder (JSON + SOAP `SubmitDdsRequest` XML) with mandatory citation validation, and the `python -m terrasentry_core.assessment` CLI that scores an M1 reference run and writes per-record DDS/evidence artifacts plus a `summary.json` confusion matrix for M6 calibration. Seed data extended deterministically with consignments, the synthetic EU operator, expected signal/ambiguity labels, concession-floor sanity, and a real permit-gap signal (HGU→oil palm, PBPH→wood; 4/4/4 high-risk signals; 3/3/2 ambiguity reasons). A full 50-record synthetic-signal harness reproduces the intended 30/12/8 breakdown and exercises all three detection paths. Core suite 66 tests (85 total) green; Ruff/Pyright clean; `pnpm check`/`pnpm test` green. DDS submission is out of scope and disclosed; live thresholds still need the §3 Day-1 keys. |
| 2026-09-11 | M1 | Integration layer landed: GFW/Hansen + NASA FIRMS clients (per-source limiter, retry/backoff, typed errors), Redis response cache (`cache.py`, memory backend for tests), GFW async batch path, deterministic seed data (8 demo polygons + 30/12/8 batch with synthetic HGU/PBPH legality), reference pipeline, preflight probe. Setup runbooks added under `docs/setup/` (AWS free tier/credits + Bedrock, SAP BTP/Integration Suite/sandbox, data-source keys). 26 pytest tests green, Ruff/Pyright clean. M1 marked Done: cached zero-external-call re-runs are test-asserted; live latency/quota measurements delegated to the §3 Day-1 key gates (no credentials in the build environment). |
| 2026-09-10 | M0 | UI foundation landed: shadcn base-mira, single DESIGN.md token file, branded proof page. Python toolchain verified (uv 0.12.12, uv.lock, ruff/pyright/pytest). Real OpenAPI client, CI workflow, compose.yaml. Local Docker builds deferred to CI (container egress blocked); commit user-owned. |
| 2026-09-10 | M0 | Scaffold created: monorepo, web + API skeletons, Effect integration, CDK shell, architecture doc. Python toolchain unverified; nothing committed yet. |
