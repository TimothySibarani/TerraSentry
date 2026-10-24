# @terrasentry/web

The TerraSentry cockpit: TanStack Start (React 19, Vite, Nitro), Tailwind CSS v4, shadcn/ui on Base UI,
and an Effect client for the Python API.

```bash
pnpm dev          # from the repo root: web on :3000 and the API on :8000
pnpm --filter @terrasentry/web test
pnpm --filter @terrasentry/web typecheck   # also regenerates src/routeTree.gen.ts
```

## Screens

| Route | What it is for |
| --- | --- |
| `/` | Overview: needs-your-decision count, demo scenarios, latest batch KPIs |
| `/screen` | Screen one plot: draw or paste it, declare supplier, permit and lot |
| `/review` | The queue of ambiguous and high-risk runs waiting for a person; bulk approve or block |
| `/runs`, `/runs/$runId` | Every run with its live trace, agent brief, assessment, evidence, map and DDS |
| `/batch`, `/batch/$batchId` | Batch runs with throughput and verdict breakdown |
| `/suppliers`, `/suppliers/import` | Suppliers by data origin; import a CSV or GeoJSON portfolio |
| `/settings` | The company named on due diligence statements |

## Conventions

- Design tokens live in `src/styles.css` only; use semantic classes such as `bg-background`,
  `text-muted-foreground` and `text-status-risk`. The app is dark-only.
- Data access goes through the Effect `ApiClient` in `packages/api-client`; components never call `fetch`.
- Add shadcn components with `pnpm dlx shadcn@latest add <name>`, then point imports at `#/lib/utils`
  and drop the stray `cn` dependency the registry adds.
- Tests sit next to the code they cover (`*.test.ts(x)`, Vitest and happy-dom).
