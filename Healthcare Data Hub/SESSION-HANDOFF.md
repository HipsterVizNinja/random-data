# Session handoff: Healthcare Data Hub

**Owner:** Sean Miller
**Built:** 2026-09-11
**Status:** Data model, generators, mart, and validation complete and passing.
No front end yet — that was deliberately out of scope for this session.

---

## 1. What this is

A synthetic multi-source healthcare dataset, built as a demo and teaching
asset to serve two audiences from one build: Concord client demos (IT and data
leaders) and hipstervizninja content (front-line analysts).

Healthcare is one of Concord's four depth verticals and there was no
healthcare demo asset anywhere in the workspace. GSK is pharma manufacturing;
everything else is retail, financial services, or Sigma partnership work. This
fills that gap.

Start with [README.md](README.md), then [docs/narrative.md](docs/narrative.md)
for the story and [docs/data-model.md](docs/data-model.md) for the schema.

## 2. What is in the box

Measured on the shipping build (scale `demo`, seed 20260911):

| | |
|---|---|
| Source tables | 38, 8,727,225 rows, 122 MB gzipped |
| Mart tables | 26, 9,367,745 rows, 194 MB |
| Members / encounters / claim lines | 48,000 / 566,577 / 1,135,368 |
| Referrals / appointments / roster months | 94,544 / 351,148 / 808,967 |
| Planted anomalies documented | 16 records covering A1–A12 |
| Validation | 25 of 25 hard assertions, 22 of 22 planted defects confirmed |
| Keys | 24 declared primary keys all unique, 0 business-key violations, 0 orphan foreign keys across 49 relationships |
| Determinism | `--verify` reproduces every file byte for byte |

Realism targets, all in band: commercial PMPM $545, MA PMPM $1,031,
commercial admits 57.5/1000, MA admits 257.6/1000, commercial ED 174/1000,
MA ED 464/1000, top-1% cost share 25.2%, top-5% 56.9%, ALOS 4.25 days,
median paid lag 22 days, every chronic prevalence within 0.14pp of benchmark,
P(diabetes | hypertension) 23.3%.

## 3. Run it

```sh
python Generators/build.py --scale demo    # ~2.5 min
python Build/build_mart.py                 # ~1.5 min
python Validation/validate.py              # exits non-zero on any ERROR
python Build/build_docs.py                 # regenerates dictionary + answer key
python Build/verify_keys.py                # verifies every PK, BK and FK
python Build/build_mart_manifest.py        # ERD + key manifest -> PDF
```

`Build/mart_keys.py` holds the key declarations, `Build/verify_keys.py` checks
them against the shipped data, and `Build/build_mart_manifest.py` renders
`Deliverables/data-mart-manifest.pdf` (17 pages: five landscape ERDs, a
per-table key reference, and the join hazards). The manifest reads the
verification JSON, so a key that stops being unique shows up in the document
rather than being quietly wrong.

The ERD layout is hand-placed, and `check_layout()` asserts that no box
overlaps another and no connector routes *through* a box that is not one of
its endpoints. That third check matters: boxes paint over lines, so a clipped
connector vanishes behind a box and the diagram silently asserts a
relationship that does not exist. It caught eight such cases.

Dependencies are `pandas`, `numpy`, `PyYAML`. Nothing else — no database, no
Parquet, no Faker.

## 4. Decisions made, so they are not re-litigated

**Provider-side, not payer-side.** Two framings were designed and compared. A
payer claims warehouse produces a correcting total; a provider-side
value-based-care hub produces a *rank inversion*, which is a far stronger demo
beat. The payer claims feed still lands as a source, so none of the
claims-modeling material was lost.

**Flat files, no engine.** Gzipped CSV. Both Tableau and Sigma read it
directly and it lifts to Snowflake via `SQL/`. The cost is that the modeling
logic runs in pandas rather than in inspectable SQL; `SQL/` holds the same
transforms for when this lands in a warehouse, and the two are maintained as
two expressions of one transform.

**HMO and Medicare Advantage only, never PPO.** Referrals are advisory in a
PPO and a healthcare audience will say so out loud, which collapses the
premise.

**NPIs deliberately fail their check digit.** A valid NPI resolves to a real
clinician in public NPPES. Validators will flag these; that is intended and
documented.

**CPT descriptors are written for this project.** The code numbers are
referenced for realism but AMA descriptor text is copyright and is not used.

**No behavioral health or substance use claims.** 42 CFR Part 2 handling is a
distraction and a risk in a demo asset, and the omission is a credibility
signal in itself.

**Only two type-2 dimensions** — provider and network contract. Type 2
everywhere is where synthetic data projects die.

## 5. Where the plan's numbers and the data's numbers differ

Every figure in `Deliverables/anomaly-manifest.json` and the two reports is
*measured from the shipped data*, not copied from the design. Where the design
target and the realized value differ, the realized value is what ships. Four
cases worth knowing about:

**Overlap double-count.** The design called for a 2.1% overall member-month
overstatement AND a 9% overstatement for the acquired employer group. Those
two are mutually inconsistent at a realistic 3.5% overlap rate — you cannot
get 2.1% overall from a defect that size. The group-level figure was kept
because it is the one carrying the "wrong unevenly" lesson; the overall
figure lands under 1%.

**Top-5% cost concentration.** The design band was 0.55–0.60. That reflects an
all-payer or Medicare-weighted book. This population is ~94% commercial, where
the published figure is nearer 0.50. The asserted band was widened to
0.50–0.62 rather than distorting the cost model to hit a number that is wrong
for the book being modeled. Noted in `expectations.yml` at the assertion.

**Recapturability.** The design expected capacity to bind — that much of the
leaked volume would have nowhere in network to go, making only part of it
winnable. Measured against realistic surgical rates it does not bind:
Northlake's in-network block time comfortably exceeds the leaked case volume
at this panel size. Rather than fabricate a constraint, the finding is left as
the data has it — nearly all of it is recapturable, which strengthens the
business case — and `docs/narrative.md` Q8 says so explicitly. The method
still ships, because at a larger panel or a thinner service line it binds.

**Runout percentages.** Designed retention per month is recorded in the
manifest and measured against each month's own natural volume. The *observed*
completeness in the trust report is measured differently and deliberately —
against the same calendar month in prior years, de-trended — because
comparing an incomplete month to an annual average measures seasonality and
calls it completeness. December alone carries a 1.45x elective factor. The two
numbers use different denominators on purpose and both are reported.

**Reversal netting error sizes.** The dominant naive error turned out to be
`WHERE paid_amount > 0` rather than `WHERE adjudication_seq = 1`. Both are
measured and reported; the manifest has the actual magnitudes.

There is also a global `ALLOWED_CALIBRATION` scalar in `config.py`. The cost
*model* — category distributions, contract factors, seasonality, concentration
— carries the realism; that single scalar lands the resulting PMPM inside the
benchmark band without distorting any of the structure. It is verified by the
PMPM assertions rather than taken on trust.

## 6. Realism targets

Asserted in `Validation/expectations.yml` and checked on every run:
commercial and MA PMPM, admissions per 1000, ED visits per 1000, ALOS, median
paid lag, top-1% and top-5% cost concentration, every chronic condition
prevalence within 0.5pp of benchmark, and P(diabetes | hypertension).

At `--scale dev` the distribution bands are advisory rather than asserted:
2,000 members is too small a sample to fail a PMPM band on, and failing on
sampling noise teaches nothing.

## 7. Open items

- **Front end.** Nothing built yet. That was the intended stopping point.
  `Mart/vw_claim_line_enriched.csv.gz` is the place to start — one row per
  claim line, no bridges, safe to sum.
- **Snowflake SQL is unexecuted.** `SQL/` was written against the schema but
  has not been run in a warehouse. Expect small fixes on first execution,
  particularly the `f_network_status_asof` UDF and the gaps-and-islands
  window logic in `50_fct.sql`.
- **Reference-table DDL is partial.** `10_snowflake_ddl.sql` has explicit DDL
  for the large tables; the smaller code sets are noted for
  `INFER_SCHEMA` rather than hand-written.
- **`large` scale is untested.** The flag exists and the generators chunk by
  service month, but it has not been run end to end.
- **Two key columns read back as floats** — `dim_provider.facility_id` and
  `fct_claim_header.drg_code` — because they contain nulls. A string
  comparison against an integer parent key then reports 100% orphans on a
  sound relationship. The manifest PDF documents this; the Snowflake DDL types
  them explicitly so it does not arise once loaded.
- **`docs/data-dictionary.md` and `Deliverables/anomaly-answer-key.md`** are
  generated by `Build/build_docs.py`. Re-run it after any rebuild.
- **`Deliverables/truth/`** holds the generator's internal truth columns
  (whether care actually occurred, whether a referral was genuinely out of
  network). It is the answer key for the referral analysis and is NOT part of
  the shippable source data. Do not hand it to a demo audience.

## 8. One thing to fix outside this project

`about-me/memory.md` still says in its decisions log that tasks live in
`TASKS.md` at the workspace root. The workspace `CLAUDE.md` says TASKS.md is
retired and tasks live in the Slack canvas "Morning Brief — Action Board"
(canvas `F0BDBKBN11P`). A future session reading memory first could act on the
stale entry. Worth correcting in `memory.md`.
