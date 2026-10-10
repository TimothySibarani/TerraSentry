# SAP-AWS Hackathon 2026: Shared Resources & Integration

**Target:** Using the official hackathon SAP BTP and SAP AI Core infrastructure  
**Upstream repo:** [SAP-AWS-ID-Hackathon-2026/SAP_AWS_Hackathon_ID_2026](https://github.com/SAP-AWS-ID-Hackathon-2026/SAP_AWS_Hackathon_ID_2026) (the `BTP_Instructions/README.md` file is the source for everything below)  
**Our team slug:** `startorch`  
**Status:** Phase 2 (`--model sap`) and Phase 3 (adverse media) are implemented; Phase 4 (Joule) is a proposal.

---

## 1. Why

Local AWS accounts hit quota limits for frontier models on Bedrock. The committee provides hosted
models on **SAP AI Core (Generative AI Hub)** plus Cloud Foundry and Joule. A third model mode,
`--model sap`, runs the existing agent graph on those models with no AWS quota involved. `scripted`
and `bedrock` are unchanged.

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
2. Verify both roles:
   `uv run python -m terrasentry_core.agents.preflight --provider sap`
3. Run the graph: `uv run python -m terrasentry_core.agents --scenario high_risk_live --model sap`
4. In the cockpit, the model picker enables **SAP AI Core (live)** once `/health` reports
   `aicore_configured: true`. Set `AGENT_MODEL=sap` to make it the default.

Code map: `agents/settings.py` (fields, `missing_aicore`), `agents/models.py` (`build_aicore_model`,
`ModelBundle.from_aicore`, `cap_max_tokens`), `agents/factory.py` (`MODEL_MODES`),
`agents/preflight.py` (`--provider`).

**Known limits.** LiteLLM's metadata does not list these new model ids, so it reports no
function-calling or response-schema support for them. The orchestration provider does accept `tools`,
so tool calls and Strands structured output (which falls back to tool calling) should work. The
preflight only pings a one-word reply, so confirm with a full `--model sap` run. LiteLLM's `sap`
provider lists `tools`, `tool_choice` and `response_format` as supported parameters. If Claude's tool
calls misbehave on a full run, set `AICORE_MODEL_ORCHESTRATOR=gpt-5.4` (configuration only, no code).

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
- Check it with `uv run python -m terrasentry_core.agents.preflight --provider sap`: the `media` line
  reports findings and whether citations were passed through. It is informational and never fails the
  run.

Code map: `python/integrations/.../sources/media.py` (client, stub, parser), `agents/media.py`
(`build_media_client`), `tools/agent_tools.py` (`search_adverse_media`, `ToolContext.media`),
`agents/specialists.py`, `apps/web/src/features/runs/adverse-media-card.tsx`.

### Phase 4: Joule via A2A (proposal)

Expose TerraSentry as a Joule capability using `a2a-sdk[http-server]`, modelled on
`joule_a2a/project/Python-LangGraph/solution/` upstream (`server.py`, `manifest.yml`, `joule/`).

- Joule's `agent-request` is **synchronous with a 60 second limit**. A live run takes longer, so
  answer deterministic screening within the limit and start live runs with a status link.
- Joule reaches the CF app through a **BTP Destination** (cockpit, Connectivity, Destinations; type
  HTTP, NoAuthentication) referenced by `system_aliases` in `capability.sapdas.yaml`.
- On Cloud Foundry, keep non-secret values in `manifest.yml` and set secrets with
  `cf set-env <app> NAME '<value>'` (single quotes). Add `.env` to `.cfignore`.

---

## 6. Security and submission rules

> [!WARNING]
> - Never commit service keys, client secrets or tokens. `.env` is gitignored; keep the raw key in
>   `~/.config/terrasentry/`.
> - Redact client ids, URLs and secrets before posting to the hackathon issue tracker.
> - If a secret leaks, rotate it in BTP immediately.
