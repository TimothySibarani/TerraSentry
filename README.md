# TerraSentry

Evidence-assembly agents for agricultural supply-chain compliance. TerraSentry checks supplier
parcels against real satellite and geospatial sources (Hansen GFC, NASA FIRMS), computes risk with a
deterministic rubric, and produces explainable, audit-ready due-diligence verdicts with a full agent
trace.

**The idea in one line:** agents investigate and brief, a fixed rubric decides, a person approves
anything uncertain or high-risk, and SAP enforces it.

**Status:** screening a real plot works end to end (draw, paste, upload or enter a point, then supplier,
legality and consignment), and so does importing a supplier portfolio. Compliant results release on
their own; ambiguous and high-risk results wait in a review queue, and nothing changes in SAP until a
person decides. The same tools are available to Claude Code through an MCP server. What is measured and
what is still open (live agent batches on SAP AI Core, deploying the Joule proxy, a live SAP tenant) is tracked in
[docs/milestones.md](./docs/milestones.md) and [docs/kpi.md](./docs/kpi.md).

## Stack

- **Web:** TanStack Start (React 19, Vite 8, Nitro), TanStack Query/Table, Tailwind CSS v4,
  shadcn/ui on Base UI, Effect 4 for the domain layer.
- **API:** Python 3.13, FastAPI, SQLAlchemy 2.0 + Alembic, SQLite audit store and response cache.
- **Agents:** Strands Agents SDK on SAP AI Core (`--model sap`, or the offline `scripted` replay); deterministic scoring stays in code.
- **Hosting:** SAP BTP Cloud Foundry for the Joule A2A proxy; the rest runs locally (SQLite files; Docker is optional). AWS is optional and unused today. Docker, GitHub Actions.
- **Tooling:** Turborepo + pnpm (JS), uv workspaces (Python), Biome, Ruff, Pyright, Vitest, pytest.

## Repository layout

```
apps/web             TanStack Start cockpit
apps/api             FastAPI service (uv workspace member)
apps/a2a             Joule A2A proxy for SAP BTP (screen, investigate, status)
apps/mcp             MCP server for Claude Code and other agents
packages/api-client  Effect client + generated OpenAPI types
packages/config      shared TypeScript config
python/core          agent runtime, domain logic, scoring
python/integrations  GFW/Hansen, NASA FIRMS, SAP gateway
infra/cdk            empty AWS CDK shell (unused)
docs/                PRD, architecture, milestones
data/                seed batch and cached fixtures
```

## Getting started

Prerequisites: Node >= 22 with corepack and [uv](https://docs.astral.sh/uv/). Database
servers and Docker are not needed for local development.

```bash
corepack enable
pnpm install
uv sync --all-packages
cp .env.example .env
pnpm db:upgrade # create/migrate the SQLite audit schema (`pnpm db:up` is an alias)

pnpm dev        # web on :3000 and API on :8000; applies migrations automatically
```

SQLite files live in `data/sqlite/`: `audit.db` preserves runs and submitted records;
`cache.db` holds source responses with a 90-day TTL. Relative paths resolve from the repo root.
For an existing `.env`, change `DATABASE_URL=sqlite+aiosqlite:///data/sqlite/audit.db`,
set `CACHE_BACKEND=sqlite` and `CACHE_SQLITE_PATH=data/sqlite/cache.db`, and remove `REDIS_URL`.
This starts fresh from the committed seed; old server data/volumes are left untouched.

Run one API process. Stop it before running `pnpm rehearsal:run` against the same audit file:
startup recovery assumes it owns queued/running work. Stop writers before copying SQLite files
for backup; do not copy only a live WAL database's main file. See the [storage runbook](docs/setup/data-sources.md#3-sqlite-cache).

Data-source keys (GFW, FIRMS) and cloud access are covered in
[docs/setup/README.md](./docs/setup/README.md). Once keys are in `.env`:

```bash
uv run python -m terrasentry_integrations.preflight   # live credential/latency/quota probe
uv run python -m terrasentry_core.reference            # live run, then cached
uv run python -m terrasentry_core.reference --offline  # zero external calls
pnpm rehearsal:prefetch                                # live 50-record cache prefetch + fixtures
pnpm rehearsal:run                                     # offline replay -> KPI report in data/runs/
```

The rehearsal procedure, including `--as-of` window pinning for stable fixtures, is in
[docs/setup/rehearsal.md](./docs/setup/rehearsal.md); measured numbers live in
[docs/kpi.md](./docs/kpi.md).

Quality gates:

```bash
pnpm check      # Biome + Ruff + tsc + Pyright
pnpm test       # Vitest (@effect/vitest) + pytest
pnpm build      # web bundle + cdk synth
pnpm gen:api    # regenerate packages/api-client from the FastAPI schema
```

Containers:

```bash
docker compose up --build   # API + web; SQLite files persist in the sqlite-data volume
```

Container replacement retains the named volume. `docker compose down -v` deletes it and resets both stores.

## Documentation

- [docs/architecture.md](./docs/architecture.md) — decisions, runtime architecture, stack rationale
- [docs/prd.md](./docs/prd.md) — MVP scope and acceptance criteria
- [docs/milestones.md](./docs/milestones.md) — milestone tracker and gates
- [docs/kpi.md](./docs/kpi.md) — empirical KPI table and how to reproduce it
- [docs/setup/mcp.md](./docs/setup/mcp.md) — use TerraSentry from Claude Code
- [docs/setup/README.md](./docs/setup/README.md) — API keys, SAP AI Core and the committee's resources,
  SAP sandbox, batch rehearsal
- [DESIGN.md](./DESIGN.md) — design tokens and visual language
- [AGENTS.md](./AGENTS.md) — coding standards and agent instructions
