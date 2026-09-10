# TerraSentry MVP — Product Requirements Document

**Scope statement (as given):** Demo processes 2 live scenarios end-to-end plus a batch of 50 synthetic supplier records to demonstrate throughput. Agents run against real Hansen GFC / NASA FIRMS data; SAP actions execute via BTP Integration Suite sandbox mocks.

---

## 1. Goal

Prove, live, that the Supervisor→Specialist→Verifier agent pattern can (a) reach a correct, explainable compliance verdict on real geospatial/thermal data for two hand-picked cases, and (b) sustain that reasoning at a 50-record batch scale without degrading into a lookup table. The batch run exists to answer the judge question "does this scale, or is it a demo of one lucky example?" — throughput and consistency are what it needs to prove, not depth on every record.

## 2. In scope

| Component | Status in MVP |
| --- | --- |
| Geospatial Analyst Agent | Real — GFW/Hansen GFC API, live polygon analysis |
| Thermal & Anomaly Agent | Real — NASA FIRMS API, live hotspot query |
| Independent Verifier Agent | Real — LLM-based cross-check, no external dependency |
| Legality & Entity Agent | Mocked — curated synthetic legality dataset, disclosed as such |
| Supervisor Orchestrator | Real — tool-calling orchestration (Bedrock AgentCore or direct Claude tool-use) |
| Compliance & DDS Writer | Real — generates structured JSON/XML DDS payload from agent outputs |
| SAP Ariba / S/4HANA / Joule actions | Mocked — via BTP Integration Suite sandbox, or real if sandbox access is granted (see Risks) |
| 2 live scenarios (Compliant, High Risk) | Full agent trace shown, narrated live |
| 50-record synthetic batch | Automated run, aggregate results only — not individually narrated |

## 3. Out of scope (explicitly, to protect build time)

- Real-time HGU/PBPH registry integration (no public API exists for this — synthetic dataset only)
- Real SAP Ariba/S/4HANA writes unless sandbox credentials are confirmed before build starts
- UI polish beyond a functional cockpit/dashboard — a clean table + status view is sufficient
- Handling of edge cases outside the 2 scenario archetypes (e.g., partial/ambiguous polygons) beyond what's needed to demonstrate the Ambiguous/HITL branch once

## 4. The 50-record synthetic batch — design requirements

This is the part most likely to be under-specified if you don't design it deliberately, so treat it as its own mini-spec:

**4.1 Composition.** Don't make all 50 "boring pass" cases — that proves nothing. Recommended distribution:
- ~30 records: clean/compliant (varied geography, varied polygon sizes, to prove the pipeline isn't hardcoded to one location)
- ~12 records: high-risk (mix of deforestation-flag, fire-cluster-flag, and legal-overlap-flag cases, so all three detection paths get exercised at scale, not just one)
- ~8 records: ambiguous (conflicting signals — e.g., old fire scar with no recent loss, or borderline area under the >4ha threshold) to prove the HITL branch also functions under load, not just as a manually staged single case

**4.2 Real vs. synthetic split within each record.** For the batch to be honest and still hit real APIs at scale:
- Polygon coordinates: can be synthetic (generated within real forest/plantation regions in Sumatra/Kalimantan/Riau so they return real, meaningful Hansen GFC / FIRMS data — don't use fabricated coordinates in the ocean or non-forest areas, or the "real data" claim rings hollow)
- Hansen GFC canopy-loss and FIRMS hotspot responses: real API calls, real data, for every one of the 50 records
- Legality/entity fields (company name, HGU number, beneficial ownership): synthetic, generated to match realistic Indonesian concession-permit formats

**4.3 What "throughput" needs to show.** Capture and display three numbers coming out of the batch run: total wall-clock time for 50 records, average time per record, and a pass/fail/ambiguous breakdown that matches your intended distribution. This turns the batch from "we ran a loop" into "here is a measured throughput claim," which is what actually supports your Section 5 KPI numbers (<2 min per supplier, 98% cycle acceleration) — right now those numbers are asserted; the batch run is your only chance to have empirical data backing them by demo day.

## 5. API and rate-limit constraints (must resolve before build day, not during)

| API | Constraint to check | Mitigation |
| --- | --- | --- |
| Global Forest Watch (Hansen GFC) | Public API has request-rate limits; batch of 50 concurrent polygon queries can throttle | Add small delay/backoff between calls, or batch via GFW's bulk/async query endpoint if available; test rate limit with 5 dummy calls before committing to 50 |
| NASA FIRMS | Free-tier API keys have daily transaction caps | Register API key early (takes a few days sometimes to activate); cache results per polygon+date-range so re-runs during rehearsal don't burn quota |
| Bedrock AgentCore / Claude tool-use | Token/request throughput on your account tier | Run the 50-record batch as a rehearsal at least once *before* demo day to confirm it completes without hitting quota mid-run live in front of judges |

**Action item:** run a small-scale test (5-10 records) as early as possible in the build to validate the whole pipeline works end-to-end before committing engineering time to scaling it to 50 — this de-risks the most schedule-sensitive part of the MVP.

## 6. SAP access — decision tree

Note: the submission rules require AWS **and/or** SAP, so an AWS-only build is compliant even without any SAP component. The options below are ordered by preference, given that SAP-integrated closed-loop gatekeeping is currently TerraSentry's strongest differentiator and its clearest tie to sponsor (APP Group) relevance.

**Option 1 — Self-service SAP access (try first, no organizer approval needed).**
- **SAP BTP Trial**: free, self-service signup, gives a real BTP tenant including Integration Suite trial capacity.
- **SAP API Business Hub** (api.sap.com): publishes sandbox/mock endpoints for many real APIs, including S/4HANA and Ariba, callable with a free developer account — no procurement or sponsor relationship required.
- **Action item (day 1):** spend 15 minutes checking both before assuming SAP access is blocked. If either works, agents call real SAP endpoints/schemas directly — replace the "mock" row in Section 2 with a real API action (e.g., one real vendor-status field flip).

**Option 2 — Schema-accurate self-built stub (fallback if Option 1 doesn't pan out).**
- Build a small REST service that exposes endpoints matching real SAP API payload structures, using field names, status codes, and JSON/OData shapes pulled from SAP API Business Hub's public documentation (e.g., Ariba SLP vendor status updates, S/4HANA MM purchasing block).
- Agents call this service exactly as they would call the real SAP API.
- This is a materially stronger claim than a generic mock: "implemented against SAP's real API contract, backed by a stub service since a live tenant wasn't available" — honest about the boundary while preserving the SAP-integration narrative.

**Option 3 — Drop SAP, go AWS-only (fallback of last resort).**
- Fully compliant with submission rules.
- ERP action becomes a generic status write (e.g., a DynamoDB table + simple UI showing vendor blocked/approved) instead of anything SAP-shaped.
- Lowest effort and lowest misrepresentation risk, but weakens the sponsor-relevance angle, since "closed-loop ERP gatekeeping" is presently framed around APP Group's SAP-based procurement stack.

**Recommendation:** attempt Option 1 on day 1; if it fails or access is too slow to arrive, move to Option 2 rather than Option 3 — it keeps the strongest differentiator intact without misrepresenting what's real.

## 7. Demo script (suggested flow, ~5-7 min)

1. **Compliant scenario (live):** Submit polygon → show Geospatial + Anomaly agents querying real APIs on screen → Verifier confirms → SAP status flip (real or mock, stated explicitly) → DDS JSON generated.
2. **High-risk scenario (live):** Same flow, but narrate the Supervisor's mid-investigation decision to re-task the Legality Agent — this is your best "agentic, not scripted" moment; give it 20-30 seconds of explicit narration.
3. **Batch run (pre-recorded or live-triggered, results shown):** Trigger the 50-record batch (or show a pre-run result if live execution is too slow for a demo slot), display the throughput numbers and pass/fail/ambiguous breakdown from Section 4.3.
4. **Close on the KPI table**, now backed by the batch run's empirical numbers rather than only projected estimates.

## 8. Success criteria for the MVP itself

- Both live scenarios complete end-to-end without manual intervention, using real Hansen GFC and FIRMS data
- Batch of 50 completes within a demo-compatible time window (test this — if it takes 10+ minutes, plan to trigger it before your slot and show results, not the live run)
- At least one genuinely real SAP-side interaction, if sandbox access is obtained
- Verifier Agent visibly catches or cross-checks at least one thing in the demo (even if scripted into the high-risk case) — this is your proof that verification is a real step, not decoration

## 9. Key risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| API rate limits hit mid-demo | High — public failure in front of judges | Rehearse full batch run beforehand; cache/pre-fetch where safe |
| SAP sandbox access denied or delayed | Medium — falls back to mocks, still acceptable if disclosed | Ask organizers on day 1, not day 2 |
| 50-record batch takes too long for a live demo slot | Medium | Pre-run and show recorded/aggregated results; keep only the 2 live scenarios interactive |
| Synthetic legality data looks fabricated/unrealistic to judges | Low-medium | Base formats on real Indonesian HGU/PBPH permit structures, and label clearly as synthetic test data |