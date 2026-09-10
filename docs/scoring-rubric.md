# Scoring rubric

Implemented in `src/rimba/scoring.py`. **No language model touches it.**

## Direction and bands

Higher is better. A run starts at 100 and loses points as risk signals accumulate.

| Score | Recommendation |
|---|---|
| 80 and above | GO |
| 60 to 79 | CONDITIONAL |
| 30 to 59 | ESCALATE |
| below 30 | NO_GO |
| n/a | BLOCKED (geometry unusable, cannot assess) |

## Dimensions

| Dimension | Max penalty | Reaches maximum at |
|---|---|---|
| Deforestation | 40 | 5% of the plot lost since the cutoff |
| Fire | 25 | 50 weighted detections (high-confidence count double) |
| Legality | 20 | permit invalid or unverifiable |
| Entity structure | 15 | accumulated severity (high 12 / medium 7 / low 3) |

## Hard gates

Certain findings cap the maximum achievable score at **59** -- the top of the ESCALATE
band -- no matter how clean everything else is:

- post-2020 tree-cover loss inside the plot
- permit invalid or unverifiable
- any high-severity ownership anomaly

**Why gates rather than heavier weights.** EUDR does not let you average deforestation
away against a tidy permit file. A weighted sum alone would eventually let a large clean
plot with a small cleared corner reach GO. The gate makes that structurally impossible,
and it is easy to explain to a judge in one sentence.

## Unverified is not clean

Missing analysis costs points: forest change not run costs 50% of its weight, hotspots
not retrieved 40%, permit not checked 50%. An agent that skips work must not be able to
produce a better score than one that does the work and finds nothing.

## Current behaviour on the demo dataset

| Supplier | Score | Band |
|---|---|---|
| SUP-001 PT Rimba Lestari Jaya | 56.2 | ESCALATE |
| SUP-002 PT Hijau Nusantara Mandiri | 100.0 | GO |

Keep this table updated. **If you change a weight, the pitch narrative changes too** --
the proposal PDF quotes an illustrative score, and the two must agree by Demo Day.

## Tuning

Weights and thresholds are constants at the top of the module. Changing them changes
every historical assessment, so treat an edit like a schema migration: note it in the
commit message and re-run the tests.
