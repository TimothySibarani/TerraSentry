# TerraSentry — Setup Runbooks

Operational guides for getting every external dependency working without spending money.

| Doc | Covers | Needed by |
| --- | --- | --- |
| [data-sources.md](./data-sources.md) | GFW/Hansen key, NASA FIRMS MAP_KEY, Redis cache | M1 |
| [aws.md](./aws.md) | AWS account, free credits, IAM, Bedrock model access, later services | M3 (Bedrock), M8 (deploy) |
| [sap.md](./sap.md) | BTP trial, Integration Suite, Business Accelerator Hub sandbox, stub fallback | M7 |
| [rehearsal.md](./rehearsal.md) | M6 batch prefetch, offline re-run, KPI report | M6, M8 |
| [../../data/seed/README.md](../../data/seed/README.md) | Synthetic seed datasets and how to regenerate them | M1, M2, M6 |

## Day-1 checklist

Work top to bottom; record each result in `docs/milestones.md` §3.

- [ ] Create AWS account (Free plan) + MFA + budget alert — [aws.md](./aws.md)
- [ ] Submit the Bedrock model-provider use-case form **once** (inherited by the org) — [aws.md](./aws.md)
- [ ] Set `BEDROCK_MODEL_*` in `.env` and verify both roles — [aws.md](./aws.md)
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
uv run python -m terrasentry_core.agents.preflight     # Bedrock gate check, needs model ids
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

Set `AGENT_MODEL=bedrock` (with `BEDROCK_MODEL_*` from [aws.md](./aws.md)) to run the live agent
path; the batch worker is deterministic and needs no model access.

## The free-stuff strategy in one paragraph

Use a normal AWS account on the Free plan ($100 on sign-up plus up to $100 for completing
five console activities, including a Bedrock prompt), and rely on Always Free services for
storage and CDN later. All M1 work runs locally with Redis in Docker, so nothing in this
milestone needs cloud spend. SAP has a free 90-day BTP trial with a limited Integration
Suite, and the Business Accelerator Hub offers free sandbox endpoints; if neither works we
ship the schema-accurate stub and disclose it. Both cloud guides end with a teardown and
cost-guardrail section so a demo never turns into a surprise bill.
