# Synthetic Seed Data

Everything in this directory is **generated and deterministic**; nothing here is real
except the geography. Regenerate at any time:

```bash
uv run python -m terrasentry_core.seed            # writes the three JSON files below
uv run python -m terrasentry_core.seed --seed 42  # same structure, different draw
```

## Files

| File | Contents |
| --- | --- |
| `demo_polygons.json` | 8 hand-picked polygons for M1/M3: the two live scenarios plus 6 more |
| `legality.json` | 50 synthetic supplier/permit/beneficial-ownership records |
| `batch_50.json` | The full 50-record batch: polygon + legality + expected archetype |

## Disclosure

Two disclosures are embedded in every file and repeated on the records:

- Polygons: *"Coordinates are synthetic but placed inside real forest regions of Sumatra
  and Kalimantan so Hansen GFC and NASA FIRMS return real data for them."*
- Legality: *"SYNTHETIC TEST DATA — companies, permits, people, and identifiers are
  invented for TerraSentry and do not describe any real organisation or person."*

The generator only composes invented names, and every trading name carries a `SYNTH-`
marker. The UI and DDS must surface the synthetic label wherever legality data appears.

## Distribution (batch_50.json)

| Archetype | Count | Intent |
| --- | --- | --- |
| `compliant` | 30 | Varied regions and polygon sizes; clean permit history |
| `high_risk` | 12 | Mix of suspended/expired permits and logged sanctions |
| `ambiguous` | 8 | Conflicting signals (e.g. permit plus missing PBPH, borderline area) |

The scripted assignment here is a **design target**, not a verdict: M2's deterministic
rubric derives the actual outcome from the data, and M6 compares the observed breakdown to
this design.

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
```

If a demo polygon returns no loss and no fire hotspots in a region where we expected
activity, regenerate with a different seed or adjust its region's demo bbox, then re-run.
Record the final numbers in `docs/milestones.md` M1 notes.

## Determinism

`generate_batch(rng_seed=...)` is stable: the same seed produces byte-identical JSON.
Tests in `python/core/tests/test_seed.py` assert the distribution, validity, bounds, and
the synthetic labelling.
