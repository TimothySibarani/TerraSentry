# Synthetic Seed Data

Everything in this directory is **generated and deterministic**; nothing here is real
except the geography. Regenerate at any time:

```bash
uv run python -m terrasentry_core.seed            # writes the JSON files below
uv run python -m terrasentry_core.seed --seed 42  # same structure, different draw
```

## Files

| File | Contents |
| --- | --- |
| `demo_polygons.json` | 8 hand-picked polygons for M1/M3: the two live scenarios plus 6 more |
| `legality.json` | 50 synthetic supplier/permit/beneficial-ownership records |
| `operator.json` | The single synthetic EU operator used on every DDS |
| `batch_50.json` | The full 50-record batch: polygon + legality + consignment + expected archetype |

## Disclosure

Disclosures are embedded in every file and repeated on the records:

- Polygons: *"Coordinates are synthetic but placed inside real forest regions of Sumatra
  and Kalimantan so Hansen GFC and NASA FIRMS return real data for them."*
- Legality: *"SYNTHETIC TEST DATA — companies, permits, people, and identifiers are
  invented for TerraSentry and do not describe any real organisation or person."*
- Consignments: *"SYNTHETIC TEST DATA — consignment quantities, products, and the EU
  operator are invented... Only the HS heading and product structure follow the real
  EUDR formats."*

The generator only composes invented names, and every trading name carries a `SYNTH-`
marker. The UI and DDS must surface the synthetic label wherever legality or
consignment data appears.

## Distribution (batch_50.json)

| Archetype | Count | Intent |
| --- | --- | --- |
| `compliant` | 30 | Varied regions and polygon sizes; clean permit history |
| `high_risk` | 12 | `expected_signal` cycles `deforestation` / `fire` / `legal` so all three detection paths are exercised (4 each) |
| `ambiguous` | 8 | `expected_ambiguity` cycles `borderline_area` / `old_fire_scar` / `permit_gap` (3/3/2) |

The scripted assignment here is a **design target**, not a verdict: M2's deterministic
rubric (`python -m terrasentry_core.assessment`) derives the actual outcome from the data,
and M6 compares the observed breakdown to this design with the calibration harness.

## Consignments and the EU operator

Each `BatchRecord` embeds one synthetic consignment shaped for the EUDR DDS:

| Field | Rule |
| --- | --- |
| Commodity | HGU-only permit → `oil_palm`; PBPH-only permit → `wood`; otherwise deterministic draw |
| HS heading | `1511` (crude palm oil) or `4703` (chemical wood pulp) |
| Net weight | deterministic tonnes/ha draw × concession area |
| Species | `Elaeis guineensis` or `Acacia mangium` |
| Production place | `Block NN — <region> (SYNTH)` |
| Harvest year | 2023–2025 |

`operator.json` holds the synthetic EU importer (EORI, Rotterdam address) declared as the
represented operator on every DDS. M2's DDS builder maps these records onto the EUDR
Information System V3 `SubmitDdsRequest` JSON/XML payload.

## Regions

Polygons are drawn from real forest/peat landscapes (`regions.py`):

- Riau peat forests (Siak) — demo bbox around the Giam Siak Kecil–Bukit Batu landscape
- Jambi lowland forest (Tebo) — demo bbox near Bukit Tigapuluh
- South Sumatra peat forest (Musi Banyuasin) — Sembilang/Dangku area
- Central Kalimantan forest (Katingan) — Sebangang/Katingan landscape
- East Kalimantan forest (Kutai Timur) — Kutai area
- West Kalimantan forest (Kapuas Hulu) — Danau Sentarum area

Each polygon is a 5–8 vertex irregular polygon, geometrically valid, 100–6000 ha (scaled
to the archetype), with a realistic centroid.

## Legality field formats

| Field | Format | Example |
| --- | --- | --- |
| NIB | 13 digits | `9260597875842` |
| NPWP | 15 digits formatted | `12.854.808.3-759.034` |
| HGU | `HGU No. n/HGU/BPN/yyyy` | `HGU No. 343/HGU/BPN/2020` |
| PBPH | `SK.n/MENLHK-PKTL/PBPH/yyyy` | `SK.4821/MENLHK-PKTL/PBPH/2018` |
| Permit status | `active` / `expired` / `suspended` / `none` | |

## Verifying against real APIs

The archetype labels are unverified until a live run. Day 1 (or as soon as keys land):

```bash
uv run python -m terrasentry_integrations.preflight --polygons data/seed/demo_polygons.json
uv run python -m terrasentry_core.reference --seed data/seed/demo_polygons.json
uv run python -m terrasentry_core.assessment --run data/runs/<run>.json --out data/dds
```

If a demo polygon returns no loss and no fire hotspots in a region where we expected
activity, regenerate with a different seed or adjust its region's demo bbox, then re-run.
Record the final numbers in `docs/milestones.md` M1 notes.

## Determinism

`generate_batch(rng_seed=...)` is stable: the same seed produces byte-identical JSON.
`python/core/tests/test_seed.py` asserts the distribution, validity, bounds, synthetic
labelling, consignment formats, and that the committed files match the generator exactly.
