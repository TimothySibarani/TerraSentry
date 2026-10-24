# SAP-AWS Hackathon 2026: Shared Resources & Integration

**Target:** Using the official hackathon SAP BTP and SAP AI Core infrastructure  
**Upstream repo:** [SAP-AWS-ID-Hackathon-2026/SAP_AWS_Hackathon_ID_2026](https://github.com/SAP-AWS-ID-Hackathon-2026/SAP_AWS_Hackathon_ID_2026) (the `BTP_Instructions/README.md` file is the source for everything below)  
**Our team slug:** `startorch`  
**Status:** SAP AI Core is the only live model provider (Bedrock was removed 2026-10-13). Phase 2 (`--model sap`) and Phase 3 (adverse media) are implemented; Phase 4 (Joule A2A proxy) is implemented and tested locally; deploying it needs your CF and BTP logins. The live models were verified on 2026-10-13 (§4.1 and `docs/evidence/README.md`).

---

## 1. Why

Local AWS accounts hit quota limits for frontier models on Bedrock. The committee provides hosted
models on **SAP AI Core (Generative AI Hub)** plus Cloud Foundry and Joule, so TerraSentry dropped
Bedrock: the model modes are now `scripted` (offline, no credentials) and `sap` (the committee's
models through LiteLLM). Nothing in the repo calls AWS.

---

## 2. What the committee provided

### 2.1 Pre-deployed models (resource group `default`)

| Model | Deployment ID | Use in TerraSentry |
| :--- | :--- | :--- |
| `anthropic--claude-4.6-sonnet` | `dc9594f579d3e4c1` | Orchestrator / verifier role (`AICORE_MODEL_ORCHESTRATOR`) |
| `gpt-5.4` | `d1a82575de60e02a` | Extraction role (`AICORE_MODEL_EXTRACTION`) |
| `sonar` (`sonar-pro` is used by the upstream sample) | `d01c3468af3ad67a` | Phase 3: adverse media and legality context with citations |
| `gemini-3.1-flash-image` | `d5fad5cf7622af7f` | Unproven: an image model; image-input analysis of maps/certificates is untested |
| `sap-rpt-1.6` | `d76cf689a05d504f` | Tabular prediction (see the scoring caveat below) |
| `tabpfn-3.5-plus` | `da450ba3ea929a74` | Tabular prediction (same caveat) |
| `text-embedding-3-large` | `d5c542b69551fce3` | Embeddings for regulatory text search, if we need them |
| `orchestration` | `d8c092efb8980093` | **The routing layer LiteLLM uses for every `sap/` chat model**, plus templating, filtering and grounding |

> [!IMPORTANT]
> Scoring and status derivation stay deterministic in code. RPT-1 / TabPFN output may only appear as
> an advisory signal next to the rubric score. It must never feed the verdict.

### 2.2 Credentials (keybroker)

Our slug is `startorch`. Fetch to a private file and never print or paste the contents:

```bash
umask 077; mkdir -p ~/.config/terrasentry
curl -sf https://hackathon-keybroker.cfapps.ap10.hana.ondemand.com/ai-core/startorch-key \
  > ~/.config/terrasentry/aicore-key.json
jq -r 'keys | join(",")' ~/.config/terrasentry/aicore-key.json     # key names only

curl -s https://hackathon-keybroker.cfapps.ap10.hana.ondemand.com/joule/startorch-key   # Joule / DAS key
curl -s https://hackathon-keybroker.cfapps.ap10.hana.ondemand.com/group/startorch       # IAS group UUID
```

The AI Core response carries `clientid`, `clientsecret`, `url` and `serviceurls.AI_API_URL`.

### 2.3 Cloud Foundry and Joule

| Item | Value |
| :--- | :--- |
| CF API | `https://api.cf.ap10.hana.ondemand.com` (`cf login --sso`, origin key `auisywroy-platform`) |
| Org / space | `SEAIO_aws-sap-hackathon-si4ykj9d` / `hackathon-startorch` |
| Joule login | `joule login --no-app-tid --authurl … --apiurl … -c <uaa.clientid> -s <uaa.clientsecret>`; **do not use `--sso`** (redirect_uri mismatch) |
| Deploy a capability | `joule deploy --compile .`, then `joule list` / `joule launch <name>` |
| Help | Issue tracker of the upstream repo, template `Error Report`. Redact all secrets first |

---

## 3. Phase 1: connectivity check

Run these yourself (in Claude Code prefix with `!`); they print status only.

```bash
K=~/.config/terrasentry/aicore-key.json
TOKEN=$(curl -s -X POST "$(jq -r .url $K)/oauth/token" \
  -u "$(jq -r .clientid $K):$(jq -r .clientsecret $K)" -d grant_type=client_credentials | jq -r .access_token)
AI_API_URL=$(jq -r .serviceurls.AI_API_URL $K); echo "token length: ${#TOKEN}"

# GPT-5.4: the route upstream documents
curl -s "$AI_API_URL/v2/inference/deployments/d1a82575de60e02a/chat/completions?api-version=2024-12-01-preview" \
  -H "Authorization: Bearer $TOKEN" -H "AI-Resource-Group: default" -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Reply with ok"}],"max_completion_tokens":50}' \
  | jq '.choices[0].message.content // .'
```

Upstream only documents `chat/completions` for GPT-5.4. Anthropic deployments on AI Core usually
use a Bedrock-style route instead of the OpenAI one (**unverified here**). Do not rely on a direct
call for Claude; the supported path is LiteLLM through the orchestration deployment, which §4
exercises with `preflight`.

---

## 4. Phase 2: `--model sap` (implemented)

The agent roles run through `strands.models.litellm.LiteLLMModel` with model ids of the form
`sap/<deployment model name>`. Credentials are passed per call as the service key, so nothing is
exported to `os.environ`. LiteLLM normalises the `/oauth/token` and `/v2` suffixes itself.

1. Put the key in the gitignored `.env` as a single line, plus the two model names:

   ```bash
   AICORE_SERVICE_KEY='{"clientid":"…","clientsecret":"…","url":"…","serviceurls":{"AI_API_URL":"…"}}'
   AICORE_MODEL_ORCHESTRATOR=anthropic--claude-4.6-sonnet
   AICORE_MODEL_EXTRACTION=gpt-5.4
   ```

   (Or set `AICORE_CLIENT_ID`, `AICORE_CLIENT_SECRET`, `AICORE_AUTH_URL`, `AICORE_BASE_URL` and
   `AICORE_RESOURCE_GROUP` individually, as Cloud Foundry env vars do.)
2. Verify the roles, structured output and the Sonar name:
   `uv run python -m terrasentry_core.agents.preflight`
3. Run the graph: `uv run python -m terrasentry_core.agents --scenario high_risk_live --model sap`
4. In the cockpit, the model picker enables **SAP AI Core (live)** once `/health` reports
   `aicore_configured: true`. Set `AGENT_MODEL=sap` to make it the default.

Code map: `agents/settings.py` (fields, `missing_aicore`), `agents/models.py` (`build_aicore_model`,
`ModelBundle.from_aicore`, `cap_max_tokens`), `agents/factory.py` (`MODEL_MODES`),
`agents/preflight.py`, and `python/integrations/.../sap_ai_core.py` (the resolution cache).

**Known limits.** LiteLLM's metadata does not list these new model ids, so it reports no
function-calling or response-schema support for them. The orchestration provider does accept `tools`,
so tool calls and Strands structured output go through the tool route. LiteLLM **drops
`tool_choice`**, so that route cannot be forced; the preflight probes it (§4.1). If Claude's tool
calls misbehave on a full run, set `AICORE_MODEL_ORCHESTRATOR=gpt-5.4` (configuration only, no code).

### 4.1 Checked against the committee repo (2026-10-13)

Compared with `SAP_AWS_Hackathon_ID_2026` (`BTP_Instructions`, and the `joule_a2a` Python and
JavaScript solutions), and replayed offline against a fake AI Core server (no real key was used).

**Matches.** Deployment ids and model names (§2.1). The route is the one the committee's own reference
code uses (`sap/gpt-5.4` through LiteLLM). `apps/a2a` follows the reference layout: schema 3.28.0,
`agent-request` with `agent_type: remote`, the `artifacts[0].parts[0].text` reply path, the same
Python buildpack, `/health` check and `PORT` command. Offline, `--model sap` completes the documented
flow: token, `GET /v2/lm/deployments`, configuration check, then `POST …/v2/completion` on the
orchestration deployment, with the tools, the model name and `AI-Resource-Group: default`.

**Verified live (2026-10-13).** The key is configured and `preflight` passes all three checks:
Claude 4.6 Sonnet answers in about 5-7 s, GPT-5.4 in about 2.5 s, and structured output arrives through
the tool route on the Claude orchestrator (so the `tool_choice` risk did not bite). Two real problems
showed up only against the live service, and both are fixed:

1. **Streamed tool calls crashed** with `'MockValSer' object is not an instance of 'SchemaSerializer'`.
   Plain pings and non-streaming tool calls worked on both models, but Strands streams every call and
   a streamed tool call returns OpenAI SDK usage and logprobs objects that pydantic never built.
   `terrasentry_integrations.sap_ai_core.prepare_litellm` builds them up front (36 classes, about
   60 ms). `tests/test_sap_ai_core.py` replays the captured wire format in a fresh interpreter and fails
   without the fix.
2. **`AGENT_MAX_TOKENS=2048` was too small.** Claude's verifier review was cut off mid-report
   ("maximum token limit"). The default is now 8192. A running `pnpm dev` does not re-read `.env`, so
   restart it after changing `.env`.

Put the key in without printing it (fetch it as in §2.2 first):

```bash
printf "AICORE_SERVICE_KEY='%s'\n" "$(jq -c . ~/.config/terrasentry/aicore-key.json)" >> .env
printf 'AICORE_MODEL_ORCHESTRATOR=anthropic--claude-4.6-sonnet\nAICORE_MODEL_EXTRACTION=gpt-5.4\n' >> .env
```

If the secret contains a backslash, dotenv rewrites it inside single quotes; use the individual
`AICORE_CLIENT_*` fields instead. Then run the preflight and the `high_risk_live` scenario above. The `tool_choice` row below is now confirmed fine on the Claude orchestrator; keep the fallback for other models.

**What the replay found, and what was done about it.**

| Topic | What the replay and the code show | What was done | What to check live |
| :--- | :--- | :--- | :--- |
| `tool_choice` | LiteLLM's SAP provider lists it as supported but **drops it** in `transform_request` (confirmed by the replay). Strands' forced structured-output retry cannot force a tool call, so the verifier depends on the model using the structured-output tool unprompted. | `preflight` now probes exactly that on the orchestrator and, if the model ignores the tool, tells you to set `AICORE_MODEL_ORCHESTRATOR=gpt-5.4`. The cause itself is in LiteLLM and is not patched. | The `structured` line of the preflight, then a `high_risk_live` run. |
| Request overhead | Every model call repeated 3 OAuth token requests, the deployment listing and the configuration lookup before the completion (6 requests per call, measured). | Fixed: `terrasentry_integrations.sap_ai_core` resolves the token creator and the orchestration deployment once per process (a short token refresh buffer, so one-hour tokens still work). Tested against a fake AI Core server: **24 requests for 4 calls became 7**. If LiteLLM's internals change it stays off and logs a warning. | The `--model sap` timing in `docs/evidence/README.md`; watch for 429 on the shared token endpoint. |
| `sonar` or `sonar-pro` | The table lists `sonar`; the committee's sample code calls `sonar-pro`. | The preflight tries the other name when the configured one fails and prints `AICORE_MODEL_MEDIA=<the one that works>`. | The `media` line of the preflight. |
| Joule login URL | `BTP_Instructions` uses `https://auisywroy.authentication.ap10.hana.ondemand.com`; the exercise `joule.env.example` uses `https://aws-sap-hackathon-si4ykj9d.authentication.ap10.hana.ondemand.com`. | Documented in the runbook (§5, step 4) and in `apps/a2a/joule/joule.env.example`: use the `uaa.url` from your own key. | `joule login` and `joule status`. |
| BTP Destination | `BTP_Instructions` says participants have read-only subaccount access, while the exercise tells you to create a Destination in the cockpit. | Fallback written into the runbook (§5, step 3): an issue template for the mentors. | Whether Save works in Connectivity, Destinations. |
| Unused models | RPT-1.6, TabPFN, embeddings and the image model are not wired in. RPT/TabPFN may only ever be advisory, never a verdict input. | Nothing needed. | n/a |

---

## 5. Phases 3 and 4

### Phase 3: Sonar adverse media (implemented, context only)

`ADVERSE_MEDIA_MODE=off|stub|live` (default `off`) adds a `search_adverse_media` tool to the legality
analyst. `live` calls `sap/<AICORE_MODEL_MEDIA>` (set it to `sonar`; the upstream sample uses
`sonar-pro`) with the same AI Core credentials as `--model sap`. The model must reply with cited JSON;
findings without an http(s) URL are dropped, and provider citations (`citations` / `search_results`)
enrich titles and dates when the orchestration route passes them through.

- It is **not** a scoring input: the report stays out of the evidence ledger, findings, DDS and
  fingerprint, so parity and the verifier are unaffected. It is persisted as the payload of the
  `search_adverse_media` trace step and rendered as a "Context only, not scored" card.
- `stub` returns a deterministic, labelled-simulated result (no network) for offline demos.
- Results are cached under source `adverse_media`, so `--offline` rehearsals replay them.
- Check it with `uv run python -m terrasentry_core.agents.preflight`: the `media` line
  reports findings and whether citations were passed through. It is informational and never fails the
  run.

Code map: `python/integrations/.../sources/media.py` (client, stub, parser), `agents/media.py`
(`build_media_client`), `tools/agent_tools.py` (`search_adverse_media`, `ToolContext.media`),
`agents/specialists.py`, `apps/web/src/features/runs/adverse-media-card.tsx`.

### Phase 4: Joule via A2A (implemented, deploy it yourself)

`apps/a2a` is a small A2A server (`a2a-sdk[http-server]==0.3.25`, no dependency on `terrasentry_core`)
that lets Joule talk to the TerraSentry API over HTTP. It is a **thin proxy**: the API, database and
cockpit stay where they are, and replies link back to the cockpit.

| Joule says | Skill | What happens |
| :--- | :--- | :--- |
| `screen PT Sumber Sejahtera Sriwijaya` (or `SUP-001`, `REC-001`) | screen | `POST /batch-runs {mode:"screening"}` (deterministic, no model), waits up to `A2A_REPLY_BUDGET_SECONDS`, replies with verdict, score, top findings and a cockpit link. If it is not done in time it says so and links the run. |
| `investigate SUP-001` | investigate | `POST /runs` on `A2A_AGENT_MODEL` (default `sap`) and replies at once with the cockpit trace link. Capped at `A2A_MAX_AGENT_RUNS_PER_HOUR` because the Cloud Foundry route is public. |
| `status run-1a2b3c4d5e6f` / `status batch-…` | status | Summarises the run or batch. |

Names are matched deterministically (legal and trading names, legal forms ignored); ambiguous names
get a "which supplier did you mean?" list. Supplier ids map to record ids by their shared suffix
(`SUP-001` → `REC-001`, `SUP-U-ab12` → `REC-U-ab12`). Joule's `agent-request` is synchronous with a
60 s limit, which is why nothing in the proxy waits longer than the reply budget.

Code map: `apps/a2a/src/terrasentry_a2a/` (`server.py` executor and agent card, `skills.py`,
`intent.py`, `client.py`, `settings.py`), Joule files in `apps/a2a/joule/`, Cloud Foundry files
`manifest.yml`, `.cfignore`, `runtime.txt`, `requirements.txt` (regenerate with
`pnpm --filter @terrasentry/a2a export-reqs` after changing dependencies).

Check it locally first (the API must be running):

```bash
# the dev script runs from the repo root, so put the apps/a2a/.env.example values in the root .env
pnpm --filter @terrasentry/a2a dev          # serves on :8080
curl -s localhost:8080/.well-known/agent-card.json | jq '.skills[].id'
curl -s -X POST localhost:8080/ -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":"1",
  "method":"message/send","params":{"message":{"kind":"message","role":"user","messageId":"m1",
  "parts":[{"kind":"text","text":"screen SUP-001"}]}}}' | jq -r '.result.artifacts[0].parts[0].text'
```

Deploy runbook (you run these; they need your logins and never print a secret):

1. **Reach the API from Cloud Foundry.** The API runs on your machine, so expose it with a tunnel such
   as `cloudflared tunnel --url http://localhost:8000`. Set `API_TOKEN` on the API first, because the
   tunnel is public and the proxy sends it as a bearer token for the write endpoints.
2. **Push the app.** `cf login --sso` (origin `auisywroy-platform`), then
   `cf target -o SEAIO_aws-sap-hackathon-si4ykj9d -s hackathon-startorch`, then from `apps/a2a`:
   `cf push`. Then set the deployment values (single quotes, nothing is stored in `manifest.yml`):

   ```bash
   cf set-env terrasentry-a2a-startorch TERRASENTRY_API_URL 'https://<tunnel host>'
   cf set-env terrasentry-a2a-startorch TERRASENTRY_API_TOKEN '<API_TOKEN>'
   cf set-env terrasentry-a2a-startorch COCKPIT_BASE_URL 'https://<cockpit host>'
   cf restage terrasentry-a2a-startorch
   ```

   `curl https://<app route>/health` should answer `{"status":"ok"}`.
3. **Create the BTP Destination** `TERRASENTRY_AGENT_STARTORCH` (BTP cockpit, Connectivity,
   Destinations): type HTTP, URL = the app route, proxy type Internet, authentication
   NoAuthentication. `BTP_Instructions` says participants have read-only subaccount access, so this
   may be refused. If Save is disabled, open an `Error Report` issue on the committee repo, titled
   `[Team startorch] BTP Destination: cannot save in Connectivity > Destinations`, with the team
   name, the Destination name and URL above, and the exact message (no secrets).
4. **Deploy the Joule capability.** `joule login --no-app-tid` (never `--sso`) with the values from
   `…/joule/startorch-key`; take `--authurl` from that response's `uaa.url`, because the committee's
   two guides print different tenant URLs. Then from `apps/a2a/joule`: `joule deploy --compile .`, `joule list`,
   `joule launch terrasentry_assistant`, and ask it to `screen SUP-001`.

> [!NOTE]
> The proxy trusts whatever reaches its public route, so it only exposes seed and submitted records
> already in your API, applies the agent-run cap above, and never takes a model, URL or geometry from
> the caller. If you want the route closed, put a Cloud Foundry route restriction or an API-key
> destination in front of it.

---

## 6. Security and submission rules

> [!WARNING]
> - Never commit service keys, client secrets or tokens. `.env` is gitignored; keep the raw key in
>   `~/.config/terrasentry/`.
> - Redact client ids, URLs and secrets before posting to the hackathon issue tracker.
> - If a secret leaks, rotate it in BTP immediately.
