# Evidence

Reports a judge can open to check a claim. Raw run folders (`data/runs/`) stay gitignored because they
are large; commit the report JSON from each run below instead, then copy the headline numbers into
[docs/kpi.md](../kpi.md).

The agent graph first ran on live SAP AI Core models on 2026-10-13 (results below). The commands are
listed so the remaining runs take minutes, not an afternoon. Each needs the keys in `.env` (`GFW_API_KEY`, `FIRMS_MAP_KEY`, and
the `AICORE_*` values).

## 0. Preflight (before any live run)

```bash
uv run python -m terrasentry_core.agents.preflight
```

Keep the output. It pings both roles, probes structured output on the orchestrator (the verifier needs
it) and reports which Sonar name works. If `structured` fails, set `AICORE_MODEL_ORCHESTRATOR=gpt-5.4`
and run it again before spending time on the runs below.

## 1. The 50-record screening batch on real sources

```bash
pnpm rehearsal:prefetch --size 50 --as-of 2026-10-13 --concurrency 4
pnpm rehearsal:run --size 50 --as-of 2026-10-13 --report docs/evidence/screening-50-2026-10-13.json
```

Replays from cache, so it is fast and repeatable. Read which findings fired for the compliant-by-design
records before presenting the verdict mix: the last measurement was 1 compliant / 35 high-risk /
14 ambiguous against a design of 30/12/8.

## 2. One live agent run with a re-task

```bash
uv run python -m terrasentry_core.agents --scenario high_risk_live --model sap
```

Expect exit code 2 (held for review). The trace should show the supervisor re-tasking the legality and
geospatial specialists with its reason. In the cockpit, open the run, read the Agent brief and the
specialist reports, and record a decision. Note the run id and elapsed time.

## 3. The 10-record live agent batch

```bash
uv run python -m terrasentry_api.rehearsal run --size 10 --mode agent --model sap \
  --as-of 2026-10-13 --report docs/evidence/agent-10-2026-10-13.json
```

Record from the report: wall clock, average and p95 per record, `summary.metrics.token_usage`,
`states.failed` (any verifier or model failure), and `states.awaiting_review` (runs held for a person).
The failure count and the held count are the numbers that show whether the agents help or only add
cost over the screening batch.

| Run | Date | Model | Records | Wall clock | Avg / record | Tokens | Failed | Held | Report |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| _screening-50_ | | none | 50 | | | | | | |
| _high_risk_live_ | | | 1 | | | | | | |
| _agent-10_ | | | 10 | | | | | | |

## Live results, 2026-10-13 (SAP AI Core, Claude 4.6 Sonnet orchestrator, GPT-5.4 extraction)

Preflight: orchestrator ok (5-7 s), extraction ok (2.5 s), structured output ok (1.6 s).

| Run | Scenario | Result | Wall clock | Notes |
| --- | --- | --- | --- | --- |
| CLI | `high_risk_live` | held for review, `high_risk` score 100, DDS withheld, verifier accepted (`llm_reviewed`) | about 100 s | 83 trace steps, 2 re-tasks |
| API, clean process | `high_risk_live` | held for review (`high_risk`) | 98.9 s and 100.6 s | two parallel runs, 56 and 66 steps |
| API, clean process | `high_risk_live` | **failed**: verifier rejected the supervisor summary ("persistent and accelerating" while the by-year evidence shows loss falling after 2023) | about 140 s | the gate working as designed |
| API, clean process | `compliant_live` | **failed**: verifier raised a `missing_source` error because `data_gaps` was empty while the legality evidence is labelled synthetic | 115.0 s | the same synthetic labelling was only an info note in the CLI run |
| API, before the fixes | `high_risk_live` | failed on the 2048-token cap (three runs, one of them on a worker that had not re-read `.env`) | 99-108 s | fixed by `AGENT_MAX_TOKENS=8192` |

**Reading it.** The graph works on the committee's models: delegation, re-tasks, specialist reports,
41-44 verifier evidence lookups and the review hold all ran. What is not yet reliable is the LLM
verifier's severity: the same synthetic-data disclosure is an `info` note in one run and an `error`
that fails the run in another, and its prompt (`VERIFIER_PROMPT`) gives no guidance on what counts as an
error. So far 3 of 5 post-fix runs completed. Token usage was not captured. The 10-record batch and the
50-record screening report are still to be run.

