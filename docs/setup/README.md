# TerraSentry — Setup Runbooks

Operational guides for getting every external dependency working without spending money.

| Doc | Covers | Needed by |
| --- | --- | --- |
| [data-sources.md](./data-sources.md) | GFW/Hansen key, NASA FIRMS MAP_KEY, Redis cache | M1 |
| [aws.md](./aws.md) | Optional: AWS hosting, only if the API must leave your laptop (nothing uses AWS today) | M8 (if at all) |
| [sap.md](./sap.md) | BTP trial, Integration Suite, Business Accelerator Hub sandbox, stub fallback | M7 |
| [sap-hackathon-resources.md](../sap-hackathon-resources.md) | Hackathon BTP, AI Core models (Claude 4.6, GPT-5.4, Sonar), Joule A2A | M3, M7, M8 |
| [mcp.md](./mcp.md) | Use TerraSentry from Claude Code: tools, the `erp` modes and the human gate | M8 |
| [rehearsal.md](./rehearsal.md) | M6 batch prefetch, offline re-run, KPI report | M6, M8 |
| [../../data/seed/README.md](../../data/seed/README.md) | Synthetic seed datasets and how to regenerate them | M1, M2, M6 |

## Day-1 checklist

Work top to bottom; record each result in `docs/milestones.md` §3.

- [ ] Fetch the SAP AI Core key from the keybroker and set `AICORE_*` and the two `AICORE_MODEL_*`
      names in `.env` — `/health` reports `aicore_configured` and the cockpit keeps "SAP AI Core
      (live)" disabled until they are set —
      [sap-hackathon-resources.md](../sap-hackathon-resources.md)
- [ ] Run `uv run python -m terrasentry_core.agents.preflight` and keep its output (it checks both
      roles, structured output and the Sonar name)
- [ ] Register GFW API key (Resource Watch → JWT → `POST /auth/apikey`) — [data-sources.md](./data-sources.md)
- [ ] Request NASA FIRMS MAP_KEY (emailed) — [data-sources.md](./data-sources.md)
- [ ] Check SAP Business Accelerator Hub sandbox and BTP trial access — [sap.md](./sap.md)
- [ ] Copy `.env.example` to `.env` and fill in the keys
- [ ] Start Redis (`docker compose up -d redis`) or set `CACHE_BACKEND=memory` for a smoke run
- [ ] Run the preflight probe and paste the numbers into the M1 notes:

```bash
uv run python -m terrasentry_integrations.preflight --polygons data/seed/demo_polygons.json
```

## Local quick start

```bash
corepack enable && pnpm install
uv sync --all-packages
cp .env.example .env            # fill in GFW_API_KEY and FIRMS_MAP_KEY
docker compose up -d redis      # cache (CI uses fakeredis instead)

uv run python -m terrasentry_integrations.preflight   # live probe, needs keys
uv run python -m terrasentry_core.reference            # live reference run, then cached
uv run python -m terrasentry_core.reference --offline  # zero external calls
uv run python -m terrasentry_core.agents.preflight     # SAP AI Core check, needs AICORE_* and model names
```

## API + database (M4)

```bash
pnpm db:up                            # postgres + redis containers (or a Neon DATABASE_URL)
pnpm db:upgrade                       # alembic upgrade head
pnpm dev                              # API :8000 + web :3000; AUTO_SEED fills suppliers/parcels
# Smoke the run API (scripted model, warm the cache first for --offline-style speed):
curl -s localhost:8000/runs -H 'content-type: application/json' \
  -d '{"record_id": "REC-001", "model": "scripted"}'
curl -sN localhost:8000/runs/<run_id>/stream          # snapshot/step/state/done SSE

pnpm db:check                         # alembic check: fail on model/migration drift
uv run pytest apps/api/tests          # SQLite + mocked sources, no Docker needed
```

Set `AGENT_MODEL=sap` (with `AICORE_*` from [sap-hackathon-resources.md](../sap-hackathon-resources.md))
to run the live agent path; the screening batch is deterministic and needs no model access.

### Real plot intake (S1)

`/screen` draws, pastes, uploads, or point-enters a plot, fills supplier/legality/consignment, then
posts a submitted record and starts its run; `POST /records` and `POST /records/import`
(CSV/GeoJSON, ≤5 MB / 500 rows) are the API equivalents. Submitted records persist in the `records`
table and register into the record registry at startup, so runs resolve after a restart; seed data
stays a clearly labelled demo set. Write endpoints accept a shared bearer token:
set `API_TOKEN` — and `VITE_API_TOKEN` for the cockpit — before exposing the API beyond localhost;
`/health.auth_enabled` reports whether the guard is on. The live SAP AI Core run needs the
AI Core credentials and the two model names (the UI disables it otherwise); scripted runs still call
real GFW and FIRMS.

## The free-stuff strategy in one paragraph

Everything runs on free or committee-provided resources. The hackathon provides the models (SAP AI
Core), Cloud Foundry and Joule, so there is no model quota to chase and no cloud bill. All M1 work
runs locally with Redis in Docker. SAP also has a free 90-day BTP trial with a limited Integration
Suite, and the Business Accelerator Hub offers free sandbox endpoints; if neither works we ship the
schema-accurate stub and disclose it. AWS is optional and only matters if the API has to be hosted
publicly ([aws.md](./aws.md) ends with a teardown and cost-guardrail section for that case).
