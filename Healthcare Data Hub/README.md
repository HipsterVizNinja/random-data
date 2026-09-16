# Healthcare Data Hub

A synthetic, multi-source healthcare dataset built as a demonstration and
teaching asset. Five source systems, deliberately imperfect identity
resolution, and twelve planted data-quality defects that a careful analyst can
find and control for.

> **Synthetic data.** Every record here is wholly fabricated. No row
> corresponds to any real person, provider, facility, or payer. Because the
> data is fabricated rather than de-identified, HIPAA de-identification
> standards (Safe Harbor, Expert Determination) do not apply and are not
> claimed. This dataset is **not** "HIPAA compliant" — that concept does not
> apply to invented records.

## What it is for

The point of this dataset is the *hub*. Any single source answers a narrow
question; the interesting material is what happens when you stitch five of
them together — conformed dimensions, cross-source identity resolution, grain
mismatches, and lineage. A single-subject mart would defeat the purpose.

It serves two audiences from one build. For a technical or executive audience,
it demonstrates why conformed dimensions and as-of joins are accountability
mechanisms rather than modeling preferences. For practitioners, it is a set of
join traps with the technique for each one attached.

## The scenario

**Northlake Health Partners** is a fictional integrated delivery network: four
hospitals, twelve ambulatory clinic groups, roughly 48,000 attributed lives
under two risk contracts with **Meridian Health Plan** (one Medicare
Advantage, one commercial HMO).

Northlake is financially accountable for a patient panel whose care it can see
about 60% of. The EHR knows every referral placed and nothing about whether it
landed. The payer file knows every dollar but arrives 90 days late under a
different member identifier. The attribution roster that decides whose cost
counts is restated retroactively every month.

Contracts are HMO and Medicare Advantage, never PPO — referrals are advisory
in a PPO, and a healthcare audience will say so out loud.

Full narrative, personas, and the question ladder: [docs/narrative.md](docs/narrative.md).
Schema and modeling decisions: [docs/data-model.md](docs/data-model.md).

## Quick start

```sh
python Generators/build.py --scale demo     # ~2.5 min, writes Source Data/
python Build/build_mart.py                  # conformed + dimensional layer
python Validation/validate.py               # exits non-zero on any ERROR
python Build/build_docs.py                  # data dictionary + anomaly answer key
python Build/verify_keys.py                 # verify every PK, BK and FK
python Build/build_mart_manifest.py         # the ERD + key manifest, as a PDF
```

Then point Tableau or Sigma at `Mart/vw_claim_line_enriched.csv.gz` — one row
per claim line, no bridges, safe to sum.

For the value-based-care questions there is a second entry point. The roster
ships as six monthly versions with a two-directional restatement history, the
contract ships with its actual terms (minimum savings rate, shared savings
split, quality gate, high-cost truncation), and claims completeness is
*derived* by chain ladder in `fct_claims_lag_triangle` rather than asserted.
Those four tables are what let a settlement number arrive with an as-of date,
a denominator and a completeness treatment attached instead of on its own.

For the schema itself, read
[Deliverables/data-mart-manifest.pdf](Deliverables/data-mart-manifest.pdf):
five ERDs plus grain, primary key, business key and foreign keys for every
table, with the join hazards named. Every figure in it is measured, not
transcribed.

### Scales

| Scale | Members | Rows | Build | Use |
|---|---|---|---|---|
| `dev` | 2,000 | ~420k | ~7s | Iterating. Distribution bands are advisory at this size |
| `demo` | 48,000 | 8.7M source + 9.4M mart | ~2.5 min + ~1.8 min | The default. Everything asserts |
| `large` | 240,000 | ~44M | ~13 min | The one "does it scale" moment. Untested end to end |

### Useful flags

```sh
python Generators/build.py --scale demo --no-anomalies   # the CLEAN TWIN
python Generators/build.py --scale demo --verify         # byte-identical check
```

`--no-anomalies` is the best teaching device in the project. Run the same
analysis against both datasets; the delta *is* the trap.

## Requirements

Python 3.11+, `pandas`, `numpy`, and `PyYAML`. That is the whole list — no
database engine, no Parquet, no Faker. The manifest PDF is rendered through
headless Chrome, which ships on the machine; without it the generator still
writes the HTML. Output is gzipped CSV, which both
Tableau and Sigma read directly and which lifts into Snowflake via the SQL in
[SQL/](SQL/).

Faker is deliberately not used. It wraps its own RNG, its locale data changes
between versions (which would silently break byte-identical regeneration), and
the identity-matching anomalies need *correlated* names — households sharing
surnames, twins, Jr/Sr pairs — which it cannot produce.

## Layout

```
Generators/     source-system generators, one module per system
Build/          build_mart.py - the conformed and dimensional layer
Source Data/    the five landed source systems, gzipped CSV
Mart/           conformed dimensions, facts, and the wide serving view
SQL/            the Snowflake lift: DDL, COPY INTO, and the same transforms
Validation/     validate.py plus expectations.yml
Deliverables/   the trust report, the answer key, the mart manifest PDF,
                and generated manifests
docs/           narrative, data model, data dictionary
```

## Reproducibility

One `MASTER_SEED` in `Generators/config.py`. Each module draws from its own
spawned RNG child, so adding a draw in `claims.py` cannot shift a byte in
`clinical.py`. `--verify` re-hashes every file against
`Deliverables/manifest.sha256`.

Hashes are taken over the *uncompressed* CSV bytes so they are stable across
gzip implementations, and gzip headers are written with `mtime=0` so the
archive depends only on the data.

## Code systems and licensing

- ICD-10-CM titles, MS-DRG titles, HCPCS Level II, UB-04 revenue codes and POS
  codes are public domain and used as published.
- **CPT descriptors are AMA copyright.** The CPT code *numbers* here are
  referenced for realism, but every descriptor string was written for this
  project and is not the AMA descriptor.
- **NPIs deliberately fail their check digit.** A valid NPI resolves to a real
  clinician in the public NPPES registry, which synthetic data must never do.
  Validators will flag these numbers; that is intended.
- No SSNs, real or fabricated. Identity matching uses name, date of birth,
  postal code, and a synthetic subscriber ID.

## Deliberately out of scope

Named so the omissions read as decisions rather than gaps: NDC-level pharmacy
and adherence, HL7/FHIR message parsing, a HEDIS measure engine, DRG grouper
logic, clinical notes and NLP, SDOH enrichment, and any geospatial model
beyond one precomputed drive-time attribute.

**No behavioral health or substance use claims at all.** 42 CFR Part 2
handling is a distraction and a risk in a demonstration asset, and the
omission is itself a credibility signal.
