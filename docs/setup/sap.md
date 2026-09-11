# SAP Setup — BTP Trial, Sandbox, and the Stub Fallback

TerraSentry's SAP component is M7: when a compliance verdict is reached, the supplier's
vendor status / purchasing block flips in an ERP. The PRD decision tree (section 6) ranks
the options from "real API" to "disclosed stub". This guide gets you as far up that ladder
as free access allows, and makes the fallback explicit so the demo never overclaims.

> SAP changes program names and trial entitlements regularly. Treat the steps as a map,
> not a contract, and record what actually worked in `docs/milestones.md` §3 on Day 1.

## 1. The decision tree

| Option | What it is | Cost | Demo claim | Effort |
| --- | --- | --- | --- | --- |
| **1a. Business Accelerator Hub sandbox** | Free SAP account calling sandbox endpoints at `sandbox.api.sap.com` with an `APIKey` header | Free | "Calls SAP's published API contract against SAP's own sandbox" | ~30 min |
| **1b. BTP trial + Integration Suite** | Real BTP tenant, 90-day trial; Integration Suite trial (30 days, shared tenant) can expose an OData/REST endpoint backed by integration flows | Free | "Real BTP tenant and integration runtime" | ~half day |
| **2. Schema-accurate stub** | Our FastAPI router serving API Hub-accurate payloads, selected by `SAP_MODE=stub` | Free | "Implemented against SAP's real API contract, backed by a stub because no live tenant was available" | Already scaffolded |
| **3. AWS-only status write** | Generic DynamoDB/Postgres status flip, no SAP shapes | Free | No SAP claim; no ERP-integration story | Small |

**Recommendation:** try 1a on Day 1. If sandbox APIs cover vendor status or purchasing
block, use `SAP_MODE=sandbox`. If BTP/Integration Suite access lands quickly, use 1b for
the strongest story. Otherwise ship Option 2 and say so in the demo.

## 2. Option 1a — Business Accelerator Hub sandbox (start here)

The Business Accelerator Hub (formerly SAP API Business Hub) publishes SAP APIs with
interactive "Try Out" sandboxes.

1. Register a free account at <https://api.sap.com/>.
2. Find candidate APIs. Search for:
   - **S/4HANA**: *Business Partner (A2X)* — supplier master data and `BusinessPartnerIsBlocked`
   - **Ariba**: *Supplier Data API with Pagination*, *Supplier Registration*, or
     supplier-qualification APIs under the Ariba category
3. Open an API → **Try Out**. Some APIs expose a **Sandbox** environment; the base URL is
   on `sandbox.api.sap.com` (for example `https://sandbox.api.sap.com/s4hanacloud/...`).
4. Get your sandbox API key from your Hub profile settings, then call with the `APIKey`
   header:

```bash
export SAP_SANDBOX_KEY="<your-hub-api-key>"

curl -sS "https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner?\$top=5" \
  -H "APIKey: $SAP_SANDBOX_KEY" \
  -H "Accept: application/json" | head -c 800
```

5. Record which API and endpoint actually responded. Set in `.env`:

```text
SAP_MODE=sandbox
SAP_BASE_URL=https://sandbox.api.sap.com/...
SAP_CLIENT_ID=
SAP_CLIENT_SECRET=
SAP_TOKEN_URL=
```

**Sandbox limits:** shared sample data, read-mostly, throttled, and not every published
API has a sandbox. Some APIs require client-credentials OAuth on a real tenant instead.
"Try Out" in the browser is the fastest way to check availability before writing code.

## 3. Option 1b — BTP trial and Integration Suite

Use this when you need a real tenant or OAuth-protected endpoints.

### 3.1 Create the trial account

1. Register at <https://www.sap.com/products/technology-platform/trial.html>. The trial
   lasts **90 days**, is suspended after 30 days of inactivity, and can be extended from
   the cockpit popup.
2. Choose a region that supports Integration Suite: **US East (VA) – AWS** or
   **Singapore – Azure**. Other regions may not offer the service.
3. Create a subaccount inside the trial global account.

### 3.2 Subscribe to Integration Suite

1. In the subaccount: **Services → Service Marketplace → Integration Suite → Create**
   (plan `trial`). Only one Integration Suite tenant per trial account.
2. If it is not visible, add the entitlement first:
   **Entitlements → Edit → Integration Suite → Add**.
3. **Security → Users → your user → Assign Role Collection → `Integration_Provisioner`**.
4. **Instances and Subscriptions → Integration Suite → Go to Application → Add
   Capabilities**, activate *Build Integration Scenarios* and *Extend Non-SAP
   Connectivity*, then assign the capability roles:

| Capability | Role collections |
| --- | --- |
| Cloud Integration | `PI_Administrator`, `PI_Business_Expert`, `PI_Integration_Developer` |
| API Management | `APIManagement.SelfService.Administrator` (name varies by release) |

### 3.3 Get credentials for our client

Create a service instance that our `sandbox`/`live` client can call:

1. **Services → Instances and Subscriptions → Create** → *SAP Process Integration
   Runtime* → plan `integration-flow` → Cloud Foundry → your space.
2. Open the instance → **Create Service Key**.
3. Copy `clientid`, `clientsecret`, `tokenurl`, and the runtime `url` into `.env`:

```text
SAP_MODE=sandbox
SAP_BASE_URL=<runtime url>
SAP_TOKEN_URL=<tokenurl>
SAP_CLIENT_ID=<clientid>
SAP_CLIENT_SECRET=<clientsecret>
```

4. Verify OAuth client credentials:

```bash
curl -sS -X POST "$SAP_TOKEN_URL" \
  -d "grant_type=client_credentials&client_id=$SAP_CLIENT_ID&client_secret=$SAP_CLIENT_SECRET" \
  | head -c 400
```

5. Build (or import) a small integration flow exposing a supplier/vendor status endpoint
   that our agents can call. Keep it read-through for the demo: the closed loop is proven
   by the visible status flip, not by writing production data.

## 4. Option 2 — the schema-accurate stub (our fallback)

The repo defines `SapGateway` (`python/integrations/.../sap/protocol.py`) with the
`stub`, `sandbox`, and `live` implementations selected by `SAP_MODE`. Verdicts reach it
through `SapActionService` (`apps/api/.../sap_actions.py`); the closed loop is enabled
for scenario runs, the 50-record batch, and HITL decisions.

When `sandbox` is unavailable, `SAP_MODE=stub` serves API-Hub-accurate field names and
status codes from the integration-layer `StubSapService`, exposed by the API's
`/mock-sap` router:

| Route | Meaning |
| --- | --- |
| `GET /mock-sap/A_Supplier('{id}')` | `A_Supplier` entity: `Supplier`, `PurchasingIsBlocked`, `PostingIsBlocked`, `PaymentIsBlockedForSupplier` |
| `PATCH /mock-sap/A_Supplier('{id}')` | OData update with the same PascalCase body |
| `GET /mock-sap/A_BusinessPartner('{id}')` | `A_BusinessPartner`: `BusinessPartner`, `BusinessPartnerIsBlocked` |
| `GET/PUT /mock-sap/vendors/{id}...` | TerraSentry convenience view over the same state |

Verify it without any credentials:

```bash
curl -sS "http://localhost:8000/mock-sap/A_Supplier('SUP-001')" | python -m json.tool
curl -sS -X PATCH "http://localhost:8000/mock-sap/A_Supplier('SUP-001')" \
  -H "Content-Type: application/json" -d '{"PurchasingIsBlocked": true}' | python -m json.tool
```

The demo states clearly:

> "This action is executed against a stub that mirrors SAP's published API contract;
> a live tenant was not available during the build."

This is materially stronger than a generic mock and is fully compliant with the
submission rules (AWS and/or SAP). Every action is persisted in `sap_actions` and
replayed into the stub at startup, and the released DDS carries an `erpAction`
extension block with `real: false`.

## 5. Team, secrets, and disclosure

- Trial accounts are **personal** and cannot be shared as logins. Nominate one account
  owner and put the API credentials in the team password manager; never commit them.
- `.env` is gitignored. `.env.example` contains the variable names only.
- Only one person needs to own the SAP trial; everyone else consumes the endpoint.
- Re-check access before the demo: trials suspend after 30 days of inactivity.

## 6. Day-1 checklist (record results in `docs/milestones.md` §3)

> **Result recorded 2026-09-11:** no API Hub or BTP credentials existed in the build
> environment, so the gate resolved to **Option 2, `SAP_MODE=stub`**. The `sandbox`
> (APIKey) and `live` (OAuth client-credentials) clients are implemented behind the same
> gateway and covered by respx tests; the live check below stays a post-access item.

- [ ] Business Accelerator Hub account created
- [ ] Found at least one sandbox API for vendor status / supplier master / purchasing block
- [ ] Sandbox call succeeded (paste the curl result in the milestone notes)
- [ ] BTP trial created (optional, only if sandbox is insufficient)
- [ ] Integration Suite subscribed and capabilities activated (optional)
- [x] Decision recorded: `SAP_MODE=stub` (no live tenant available during the build)
- [ ] Credentials stored in `.env` / password manager (not in git)

To promote to a live check later: set `SAP_MODE=sandbox`, `SAP_BASE_URL`, and
`SAP_API_KEY` (Hub sandbox) or the four OAuth values (BTP), restart the API, and run one
scenario through the cockpit. The action record flips to `real: true` and the DDS
`erpAction.real` becomes `true`; no code changes are needed.

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Integration Suite missing from marketplace | Entitlement or unsupported region | Add entitlement; use US East (VA) or Singapore |
| `403` in Integration Suite | Missing capability role collection | Assign `PI_*` roles and re-login |
| Sandbox `401` | Missing/incorrect `APIKey` header | Regenerate the key in your Hub profile |
| Every action recorded as `failed` with `MissingCredentialError` | `SAP_MODE` is `sandbox`/`live` but credentials are incomplete | Fill `.env` per §2/§3; the API logs a startup warning and the compliance runs still complete |
| Sandbox `404` on a path | API has no sandbox environment | Use "Try Out" in the browser to check first |
| OAuth `invalid_client` | Wrong token URL or service key | Recreate the service key; copy all four fields |
| Trial suspended | 30 days without login | Open the cockpit and choose *Extend Trial* |

## Links

- SAP Business Accelerator Hub: <https://api.sap.com/>
- SAP BTP trial: <https://www.sap.com/products/technology-platform/trial.html>
- Integration Suite trial: <https://www.sap.com/products/technology-platform/integration-suite/trial.html>
- Integration Suite trial setup tutorial: <https://developers.sap.com/tutorials/cp-starter-isuite-onboard-subscribe.html>
- S/4HANA Business Partner API: <https://api.sap.com/api/API_BUSINESS_PARTNER/overview>
