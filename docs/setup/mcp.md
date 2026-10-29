# MCP server: use TerraSentry from Claude Code

`apps/mcp` exposes TerraSentry to any MCP client (Claude Code, Claude Desktop, Cursor). It is a thin
client of the running API, so everything an agent starts through it also shows up in the cockpit, and
the verdict is still the deterministic rubric's, never a model's.

## Run it

```bash
pnpm db:up && pnpm db:upgrade
pnpm dev                       # API on :8000, cockpit on :3000
```

Claude Code picks up the repo's `.mcp.json` automatically (it asks you to approve the server once).
To add it by hand, or from another directory:

```bash
claude mcp add terrasentry -s user \
  -e TERRASENTRY_API_URL=http://localhost:8000 \
  -- uv run --directory /path/to/TerraSentry python -m terrasentry_mcp
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `TERRASENTRY_API_URL` | `http://localhost:8000` | The running API |
| `TERRASENTRY_API_TOKEN` | empty | Bearer token; set it whenever the API sets `API_TOKEN` |
| `COCKPIT_BASE_URL` | `http://localhost:3000` | Base for the links in results |
| `MCP_WAIT_SECONDS` | `40` | How long `screen_plot` waits for a verdict before returning the run id |
| `MCP_TRANSPORT` | `stdio` | `streamable-http` serves on `MCP_HOST:MCP_PORT` (default `127.0.0.1:8090`) |

## Tools

| Tool | What it does | Changes anything? |
| --- | --- | --- |
| `screen_plot` | Registers a plot and screens it; returns verdict, score, findings, ERP status, next step | Creates a record and a run |
| `import_records` | Imports a CSV or GeoJSON portfolio; rejected rows come back with the reason | Creates records |
| `start_batch` / `get_batch` | Screens many records; follows progress | Creates runs |
| `get_run`, `list_runs`, `list_suppliers` | Reads runs (filter `awaiting_review` for what needs a decision) and suppliers | No |
| `get_evidence` | The cited evidence ledger behind a verdict, filterable by claim prefix | No |
| `get_dds` | The released due diligence statement as JSON or XML | No |
| `cancel_run` | Stops a run or batch that is executing | Marks it failed |
| `record_review_decision` | Approve or block a held supplier | **Asks the user first** |
| `confirm_erp_action` | Applies a pending SAP change | **Asks the user first** |

The statement is also available as the resource `terrasentry://runs/{run_id}/dds`.

## What an agent can and cannot do to SAP

Screening has an ERP side effect, so every screening tool takes an `erp` mode:

- **`off` (the default).** SAP is never touched. The agent gets a verdict and a statement.
- **`confirm`.** The run computes the SAP change and waits. `confirm_erp_action` applies it after the
  user answers a prompt in the client.
- **`auto`.** The change is applied as soon as it is planned: right away for a compliant result, or
  after a review decision for a held one. This is the fully automated path; choose it on purpose.

Ambiguous and high-risk results are always held for a person, whatever the mode.

## The human gate

`record_review_decision` and `confirm_erp_action` do not act on the agent's say-so. Each one asks the
user through MCP elicitation, and the prompt states the rubric verdict and the SAP effect, for example:

> Block supplier SUP-U-27B270EFC6 (REC-U-27B270EFC6)? Rubric verdict: high_risk. SAP stays unchanged
> until the change is confirmed; then the vendor is blocked. Note: confirmed on the permit register

If the user declines, nothing happens. If the client cannot ask (it did not declare the form
elicitation capability), the call is refused with a protocol error and nothing happens either; decide
in the cockpit at `/review` instead. Approving a `high_risk` supplier also needs a note, which the
tool checks before the user is even asked.

## Limits

- Legality fields (permits, holders) are what the supplier declared. They are not checked against a
  government registry, and every result says so.
- There is no tool that returns raw evidence for a geometry without registering a record; `screen_plot`
  with `erp: off` is the closest.
- Agent mode (`mode: agent`) takes about a minute and needs a configured model (`AGENT_MODEL`).

## Test it

```bash
uv run pytest apps/mcp/tests          # in-process client with a scripted human
```

The tests cover every tool, the readable error path, and the two human gates, including a client that
cannot answer. A real session over stdio against a running API was also run while building this.
