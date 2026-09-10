# TerraSentry

Evidence-assembly agents for agricultural supply-chain compliance. TerraSentry checks supplier
parcels against real satellite and geospatial sources (Hansen GFC, NASA FIRMS), computes risk with a
deterministic rubric, and produces explainable, audit-ready due-diligence verdicts with a full agent
trace.

**Status:** M0 scaffold — see [docs/milestones.md](./docs/milestones.md) for progress.

## Stack

- **Web:** TanStack Start (React 19, Vite 8, Nitro), TanStack Query/Table, Tailwind CSS v4,
  shadcn/ui on Base UI, Effect 4 for the domain layer.
- **API:** Python 3.13, FastAPI, SQLAlchemy 2.0 + Alembic, PostgreSQL.
- **Agents:** Strands Agents SDK on Amazon Bedrock; deterministic scoring stays in code.
- **Infra:** AWS CDK (TypeScript), Docker, GitHub Actions.
- **Tooling:** Turborepo + pnpm (JS), uv workspaces (Python), Biome, Ruff, Pyright, Vitest, pytest.

## Repository layout

```
apps/web             TanStack Start cockpit
apps/api             FastAPI service (uv workspace member)
packages/api-client  Effect client + generated OpenAPI types
packages/config      shared TypeScript config
python/core          agent runtime, domain logic, scoring
python/integrations  GFW/Hansen, NASA FIRMS, SAP gateway
infra/cdk            AWS CDK app
docs/                PRD, architecture, milestones
data/                seed batch and cached fixtures
```

## Getting started

Prerequisites: Node >= 22 with corepack, [uv](https://docs.astral.sh/uv/), and a Postgres
connection string (Neon free tier, Docker, or a local install all work).

```bash
corepack enable
pnpm install
uv sync --all-packages
cp .env.example .env

pnpm dev        # web on :3000 and API on :8000
```

Quality gates:

```bash
pnpm check      # Biome + Ruff + tsc + Pyright
pnpm test       # Vitest (@effect/vitest) + pytest
pnpm build      # web bundle + cdk synth
pnpm gen:api    # regenerate packages/api-client from the FastAPI schema
```

Containers:

```bash
docker compose up --build   # Postgres + API + web
```

## Documentation

- [docs/architecture.md](./docs/architecture.md) — decisions, runtime architecture, stack rationale
- [docs/prd.md](./docs/prd.md) — MVP scope and acceptance criteria
- [docs/milestones.md](./docs/milestones.md) — milestone tracker and gates
- [DESIGN.md](./DESIGN.md) — design tokens and visual language
- [AGENTS.md](./AGENTS.md) — coding standards and agent instructions
