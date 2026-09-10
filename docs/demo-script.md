# Demo Day script

31 October 2026 · BINUS Alam Sutera

## The one moment that matters

Everything else is setup for this:

> Change detection finds 38.2 ha of loss. 31 ha sits mid-block in a regular pattern.
> **7.2 ha sits on the northern boundary**, touching another concession -- the geometry
> alone cannot attribute it.
> The orchestrator decides, on its own, to look up who owns that adjacent parcel.
> It is registered to a different company **at the same address as the supplier**.

That step is not in the plan. A dashboard cannot produce it. Slow down here -- this is the
thirty seconds the round is decided in.

## Running order (target 5 to 6 minutes)

| # | Beat | Time | Note |
|---|---|---|---|
| 1 | The deadline. 30 Dec 2026, fines from 4% of EU turnover. | 30s | One slide, no build-up. |
| 2 | **The supply base.** 23 suppliers screened, 4 need a decision. | 30s | Open on the portfolio, never on a dropdown. This answers the scale question before a judge asks it. |
| 3 | Click the worst row. **Live reasoning panel.** | 90s | The product. Let it breathe. |
| 4 | **The branch.** Boundary loss into adjacent parcel into shared address. | 60s | Name it as unplanned. |
| 5 | Scorecard, click through to raw evidence. | 45s | Show a hotspot id and a pixel count. |
| 6 | Gap list, not a rejection letter. | 30s | "What procurement can act on." |
| 7 | Joule query: share of volume with a valid DDS. | 30s | Where it lives in the workflow. |
| 8 | Replication: seven commodities, one regulation, many countries. | 30s | Close on the business. |

## Rules for the stage

- **Never process rasters live.** Everything geospatial reads from `data/cache/`. A
  progress bar in front of judges is a lost round.
- **Say which data is synthetic**, in one sentence, when the entity result appears. It
  reads as rigour, not as a caveat.
- **The distribution bar is the discrimination argument.** 11 GO / 8 CONDITIONAL / 2 ESCALATE
  / 1 NO-GO / 1 BLOCKED. A screener that flagged everything would be as useless as one that
  flagged nothing, and the bar shows at a glance that this one does neither.
- **Show the BLOCKED supplier if asked about bad data.** Transposed lon/lat, caught at the
  geometry gate, with a concrete request back to the supplier. Nobody expects a demo to
  handle its own bad input gracefully.
- **Have the clean supplier ready** (`SUP-002`, scores GO) for the contrast.
- **Rehearse the failure.** If a call hangs, cut to the cached run without apologising.

## Questions you will be asked

| Question | Answer |
|---|---|
| *What if the AI hallucinates?* | The score is not from the AI. `scoring.py` is deterministic; the Verifier drops claims with no artifact. Offer to show the file. |
| *Why an agent and not a script?* | Beat 4. The branch was not in the plan. |
| *Is the data real?* | Geospatial and fire, yes, verifiable right now. Entity data is synthetic, because no public API exists. |
| *Why Claude, or why Nova?* | Both are served through Amazon Bedrock. We route: cheap model for extraction, strong model for orchestration. Here are the traces from both. |
| *Who is the customer?* | Any operator or exporter with EU market exposure across the seven commodities. |
| *Does this scale to hundreds of suppliers?* | The rubric is free and runs in milliseconds, so the whole base is screened nightly. Only ambiguous cases reach the agent -- here 23 rubric runs, 4 agent runs. That ratio is what makes 500 affordable. |
| *Most of our suppliers are smallholders.* | 17 of 23 here, and 16 are under 4 ha -- which Article 9 treats with a GPS point, not a polygon. It is on the dashboard because it is the majority case in Indonesia, not a footnote. |
| *What happens after the hackathon?* | Continuous monitoring, then direct TRACES submission. See the roadmap in the proposal. |

## Pre-flight checklist

- [ ] `pytest tests -q` green
- [ ] Portfolio loads: 23 screened, 4 exceptions, five bands visible
- [ ] `python -m scripts.run_screening --supplier SUP-001` produces ESCALATE
- [ ] `python -m scripts.run_screening --supplier SUP-002` produces GO
- [ ] Cache files present for every supplier shown on stage
- [ ] Reasoning panel readable from the back of the room
- [ ] Laptop on mains, notifications off, one browser profile, no personal tabs
- [ ] **Pitch narrative numbers match the live output** -- re-check after any rubric change
