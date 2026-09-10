# RIMBA

**Agentic AI Co-pilot for Supplier Due Diligence and EUDR Compliance in Land-Based Commodity Supply Chains**

AI Agentic Hackathon 2026 · Track: Intelligence Supply Chain · BINUS × SOKRATES × AWS × SAP

---

## What this is

From **30 December 2026**, companies placing seven land-based commodities (palm oil, timber, rubber,
coffee, cocoa, soy, cattle) on the EU market must prove the goods are deforestation-free since
**31 December 2020**, legal in the country of origin, and backed by a plot-level geolocated
**Due Diligence Statement (DDS)** filed through EU TRACES.

RIMBA turns *"a company name and a patch of land"* into **an evidence dossier that holds up in front of
an auditor**.

It is not a prediction problem. Every input already exists in public data — satellite imagery, fire
hotspots, land-cover baselines, corporate registries. The hard part is **evidence assembly**: the data
is scattered across incompatible formats, supplier input quality varies wildly, and somewhere in the
middle a judgement call is required about whether the evidence is *sufficient to sign a legal
statement*. That last part is why this is an agent and not a script.

## The one thing that makes this agentic

A fixed pipeline cannot handle this branch:

> Change detection finds 38 ha of tree-cover loss. 31 ha sits mid-block in a regular pattern.
> 7 ha sits on the northern boundary, touching a neighbouring concession — **ambiguous**.
> The orchestrator independently decides to look up who owns that adjacent parcel.
> *That step was not in the original plan.*

Everything else in this repo exists to make that moment possible and defensible.

## Non-negotiable design rules

1. **The LLM never invents the score.** Code computes the score from a deterministic rubric
   (`src/rimba/scoring.py`). The model writes the narrative that explains it. This makes results
   reproducible and gives a straight answer to *"what if the AI hallucinates?"* — the number isn't
   from the AI.
2. **Every claim carries a citation.** Anything entering the dossier passes through
   `src/rimba/evidence.py` with a source, an artifact, and a retrieval timestamp. The Verifier step
   drops claims that cannot be traced.
3. **No-Go is never automatic.** The agent assembles the file; a human signs it.
4. **Simulated data is labelled as simulated.** Geospatial and fire data are real and independently
   verifiable. Corporate entity data is synthetic (see `docs/data-sources.md`). Never blur this line —
   on stage it *adds* credibility.

## Repo layout

```
docs/                    Architecture, scoring rubric, data sources, demo script
data/polygons/           Demo supplier concession polygons (GeoJSON, WGS84)
data/entities/           Synthetic corporate registry for entity-anomaly demo
data/cache/              Pre-computed analysis results for Demo Day (do not process live on stage)
src/rimba/pipeline.py    Screening pipeline, emits steps (shared by CLI and web panel)
src/rimba/tools/         Agent tools: geometry, FIRMS hotspots, forest change, entity lookup
src/rimba/scoring.py     Deterministic risk rubric  <- NOT an LLM
src/rimba/dds.py         TRACES-aligned Due Diligence Statement builder
src/rimba/evidence.py    Evidence ledger with citations
src/rimba/agent/         Bedrock orchestration loop, tool specs, prompts
web/index.html           Local web panel (map, reasoning stream, scorecard, evidence, DDS)
web/map.js               Evidence map renderer -- no Leaflet, no CDN, works offline
scripts/                 CLI + local server entrypoints
tests/                   Unit tests for the deterministic parts
```

## Setup

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env                                     # then fill in the keys
```

Required keys (all free to obtain — see `docs/data-sources.md`):

| Variable | Where to get it |
|---|---|
| `FIRMS_MAP_KEY` | https://firms.modaps.eosdis.nasa.gov/api/map_key/ |
| `AWS_REGION`, AWS credentials | Hackathon AWS account (finalists) |
| `GFW_API_KEY` | Optional — https://data-api.globalforestwatch.org/ |

### Try it — web panel

```bash
python -m scripts.serve
```

Opens http://localhost:8765. Pick a supplier, hit **Run screening**, and the reasoning
stream fills in step by step, with the scorecard, evidence ledger and DDS output on the
right. Standard library only — no Flask, nothing extra to install.

The pipeline finishes in about 10 ms, which is too fast to read, so the panel paces the
display (toggle it off with the *paced* checkbox). The steps and their payloads are real
and unmodified; each shows its true elapsed time. Never describe the pacing as
processing time.

### Satellite imagery for the map

```bash
python -m scripts.fetch_imagery --supplier SUP-001 --search-only
```

Lists real Sentinel-2 scenes over the plot from the AWS Registry of Open Data, via the
Earth-search STAC API — no key, no cost. Drop `--search-only` to render before/after PNGs
into `data/cache/imagery/`, which the map picks up automatically (needs `pip install rasterio numpy`).

**Not Google Maps, on purpose.** Google discards old imagery once new imagery arrives,
stores no acquisition date, and its terms forbid storing and re-serving the images —
which is exactly what an evidence pack must do. Sentinel-2 is dated, archived to 2017,
free, and lives on AWS.

### Try it — command line

```bash
python -m scripts.run_screening --supplier SUP-001
```

```bash
python -m scripts.run_screening --list
```

Both entrypoints call the same `rimba.pipeline.run()`. If they ever disagree, that is a bug.

## Build order (recommended)

The deterministic core comes first. The agent is thin — it decides *which* tool to call, and the
tools do the real work. Build the tools first or the agent has nothing to orchestrate.

1. `tools/geometry.py` — polygon validation, area, the EUDR 4 ha rule → **this gates everything else**
2. `tools/firms.py` — hotspot history (easiest real data win, working client included)
3. `scoring.py` + `evidence.py` — deterministic rubric and the citation ledger
4. `tools/forest_change.py` — tree-cover loss against the 2020 baseline → **the real technical core**
5. `dds.py` — TRACES-aligned output
6. `agent/orchestrator.py` — the Bedrock loop that ties it together
7. UI / demo panel

## Team split (3 people, October build window)

| Role | Owns |
|---|---|
| Geospatial | `tools/geometry.py`, `tools/forest_change.py`, polygon and raster data prep |
| Agent | `agent/`, `scoring.py`, `evidence.py`, `dds.py` |
| Demo | UI, `data/cache/` preparation, demo script, pitch narrative |

## Hard-won warnings

- **Do not process satellite rasters live on stage.** Pre-compute into `data/cache/`. What the judges
  want to watch is the agent reasoning, not a progress bar.
- **Do not build authentication.** Not scored, eats a week.
- **Do not build a real SAP Ariba integration.** Mock the interface; show where it plugs in.
- **Pick one commodity and one province.** Breadth is not scored; a working depth demo is.
- **Kill the old server before starting a new one.** Python sets `SO_REUSEADDR`, and on
  Windows that lets a second process bind a port the first is already on. Both answer,
  and the stale one shadows your fixes. `scripts/serve.py` now refuses to start rather
  than shadow — but if you launch it another way, check the port.
- FIRMS `day_range` is capped at **5 days per request** — history requires windowed calls. Already
  handled in `tools/firms.py`, but budget for the transaction limit (5000 per 10 minutes).

## Licence

TBD before the repo goes public. Note the hackathon rule: submissions must be original work created
during the hackathon period.
