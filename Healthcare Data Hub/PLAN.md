# Healthcare Data Hub — synthetic dataset and data model

## Context

`Projects/Healthcare Data Hub/` was created today and is empty. Nothing about it
exists in `about-me/memory.md`, so this is a genuine greenfield start. Healthcare
is one of Concord's four depth verticals and there is currently no healthcare demo
asset in the workspace — GSK is pharma manufacturing, and every other project
folder is retail, financial services, or Sigma partnership work. This fills that gap.

The asset is a **demo / reference build**, not a client engagement. It has to serve
two audiences from one build: Concord client demos (IT and data leaders) and
hipstervizninja teaching content (front-line analysts). The whole point is the
*hub* — several healthcare source systems stitched together, so the material worth
teaching is conformed dimensions, cross-source identity resolution, grain
mismatches, and lineage. A single-subject mart would defeat the purpose.

Decisions already made:

- **Domain:** mixed hub spanning multiple healthcare sources.
- **Data:** 100% synthetic, generated in Python. No PHI, fully shareable.
- **Target:** local, **flat files only** — no database engine. Generators write
  gzipped CSV that Tableau and Sigma both read directly, and that lifts into
  Snowflake later via `COPY INTO`.
- **Scale:** demo-scale — ~48k members, ~2.4M claim lines, ~11M rows total.
- **Scope of this session:** narrative spec, schema design, generated data,
  reference load SQL, validation. Stop before any front-end build.

Local tooling confirmed: Python 3.13.7, pandas 2.3.2, numpy 2.3.2. No `pyarrow`,
so Parquet is unavailable without an install — gzipped CSV is the primary format
and Parquet is an optional later add-on. Validation runs in pandas. No Faker;
names come from committed seed lists (needed anyway, because the identity-matching
anomalies require *correlated* names that Faker can't produce).

House pattern to follow is `Projects/Q4 Mill Performance Use Case/`: `Generators/`,
`SQL/`, `Source Data/`, `Deliverables/`, plus `SESSION-HANDOFF.md` and
`data-trust-validation.md`. That project planted deliberate data-quality traps and
treated "found and controlled for them" as part of the deliverable. Same here.

### One design call worth stating

The two candidate framings were a payer-side claims warehouse and a provider-side
value-based-care hub. Going with **provider-side**, because it produces an aha
moment that reverses a ranking rather than merely correcting a total, and because
"data hub" is the language integrated delivery networks actually use. The payer
claims feed still lands as a source, so none of the claims-modeling material is lost.

---

## The demo in one paragraph

**Northlake Health Partners** is a fictional integrated delivery network: four
hospitals, twelve ambulatory clinic groups, ~48k attributed lives under two
risk contracts with **Meridian Health Plan** (one Medicare Advantage, one
commercial HMO). Northlake is financially accountable for a patient panel whose
care it can see about 60% of, and the invisible 40% is where the money goes. The
EHR knows every referral placed and nothing about whether it landed. The payer
file knows every dollar and arrives 90 days late under a different member ID. The
attribution roster that decides whose cost counts gets restated retroactively
every month.

Contracts are **HMO and MA, never PPO** — referrals are advisory in a PPO and a
healthcare audience will say so out loud, which collapses the premise.

### The aha moment

Naive, single-source, and wrong: North Ridge Orthopedics is the best-performing
clinic group on referral management — 96% closure, 4% open rate, EHR-derived
out-of-network referral rate of 6% against a 19% system average. Best of twelve.
The obvious recommendation is to roll out North Ridge's workflow everywhere.

Joined answer: North Ridge closes referrals because a scheduling rule turned on
2024-07-01 auto-sets status to *Closed — Complete* at day 30 whether or not any
care happened. Only 38% of their "completed" referrals have a confirming encounter
against a 72% system average. Their true out-of-network rate is **54%, worst of
twelve**, costing ~$2.7M against benchmark over 24 months on a 4,800-life panel.
**The ranking inverts from 1 of 12 to 12 of 12.** The workflow everyone was about
to copy is the thing generating the leakage.

Four things make it discoverable rather than lucky: a visible step change in the
monthly trend at July 2024; `days_to_closure` stored as a column, so the
time-to-closure histogram is one drag away; `closure_actor_type` and a workflow
config row that confirm the mechanism once suspected; and **two independent
confirmation paths** (no completed appointment *and* no professional claim), so the
first skeptic in the room can't kill the finding by blaming the match rate.

A second finding keeps the demo honest: of the $2.7M leaked, ~41% is procedures
Northlake has no credentialed surgeon or capacity for and ~12% is drive-time
geography, so recapturable is **~$1.1M, not $2.7M**. That beat is what makes it
read as consulting rather than a vendor pitch.

---

## Source systems

Five sources plus a reference feed. Each earns its place by contributing something
no other source can.

| Landing | System | Owns | Only it contributes |
|---|---|---|---|
| `raw_ehr` | CareLine EHR | encounter, encounter-diagnosis, referral order, lab result, problem list, provider directory | Clinical intent and a second patient identity space (MRN). Care that generated no claim. |
| `raw_clm` | Meridian claims extract (837/835-shaped) | claim header, claim line, remit | Money, adjudication state, reversals, POS, DRG, revenue codes, paid-date lag. |
| `raw_elig` | Meridian enrollment | coverage span, plan, group | Denominators. No rate, no PMPM, no per-1000 without it. |
| `raw_pm` | PracticeOne PM / scheduling | appointment, authorization, referral workflow config | Whether care was actually scheduled and attended — the second confirmation path, and the row that explains the aha. |
| `raw_vbc` | Northlake ACO attribution feed | attribution month, restatement, benchmark | Who counts against the contract, and the retroactive restatement history. |
| `raw_ref` | Terminology / MDM | ICD-10-CM + CCSR, CPT/HCPCS, MS-DRG, revenue codes, POS, LOINC, NPI registry, network contract, service-line crosswalk, facility crosswalk | Code sets and the SCD2 network contract. |

Deliberately cut: NDC-level pharmacy and adherence (Rx stays a spend category — a
second dataset with its own model), HL7/FHIR message layer, HEDIS measure engine,
DRG grouper logic, clinical notes and NLP, SDOH enrichment, geospatial modeling
(one precomputed `drive_time_minutes` column serves the 12% geography finding).

**No behavioral health or substance use claims at all.** 42 CFR Part 2 handling is
a distraction and a risk. Say so in the README; the omission is itself a
credibility signal.

### Three identity spaces, deliberately

Patients arrive as `member_id` (eligibility/claims), `mrn` (EHR), and
`subscriber_id` + two-digit person code (attribution feed) — which *looks*
joinable to `member_id` and is not. Providers arrive as credentialed `npi`, EHR
internal `provider_id`, and claim billing NPI with dirty values. This is the hub's
center of gravity, and the EHR→claims join is structurally a three-hop through the
crosswalk that loses 3.1%.

---

## Layers and file layout

Without a local engine, the layer boundary moves into the file tree rather than
into schemas. Generators emit **source-system-shaped raw files** — the shippable
artifact, dirty, typed as strings where a real source would emit strings. A
separate build step produces the **conformed mart files** in pandas. `SQL/` holds
the equivalent Snowflake SQL as the lift artifact.

This is a real compromise and worth naming: the modeling logic would be more
credible executed in inspectable SQL, and it will be once this lands in Snowflake
or DuckDB. For now the Python build and the reference SQL are maintained as two
expressions of the same transform, and validation asserts the Python output meets
the stated expectations.

```
Healthcare Data Hub/
  PLAN.md                     this plan, copied into the project
  README.md                    synthetic-data notice, seed, exclusions, how to build
  docs/
    narrative.md               personas, question ladder, aha spec, two cuts
    data-model.md              ERD, conformed dimensions, source-of-truth by attribute
    data-dictionary.md         generated from the schema registry
  Generators/
    config.py                  seeds, scale, date windows, rng_for()
    names.py                   surname/given-name seed lists by sex and birth decade
    ids.py                     id minting, surrogate sequences, malformed-id injectors
    reference.py               code sets, dim_date, crosswalk seeds
    population.py              members, households, latent risk, conditions
    providers.py               provider master, SCD2 affiliation and network status
    eligibility.py             coverage spans including the overlaps
    clinical.py                encounters, diagnoses, labs, referrals
    scheduling.py              appointments, authorizations, workflow config
    claims.py                  header/line split, adjudication, reversals, paid lag
    attribution.py             roster months plus restatement history
    crosswalk.py               identity resolution, under-match and over-match
    anomalies.py               applies every planted defect as a logged mutation
    write.py                   gzipped CSV writers, sort order, manifest
    build.py                   CLI: --scale --seed --only --no-anomalies --verify
  Build/
    build_mart.py              conformed + dimensional transforms in pandas
  Source Data/                 raw_ehr/ raw_clm/ raw_elig/ raw_pm/ raw_vbc/ raw_ref/
  Mart/                        dim_*.csv.gz, fct_*.csv.gz, br_*.csv.gz, xwalk_*.csv.gz
  SQL/
    10_snowflake_ddl.sql       generated from the schema registry
    11_snowflake_copy.sql      COPY INTO per table
    20_stg.sql                 typing, trimming, code normalization
    30_xwalk.sql               identity resolution
    40_dim.sql                 dimensions including both SCD2 builds
    50_fct.sql                 facts, including fct_member_month gaps-and-islands
    60_audit.sql               the validation queries as SQL
    90_demo_query_pack.sql     naive vs correct query pairs, side by side
  Validation/
    validate.py                pandas validation runner
    expectations.yml           every assertion with its expected magnitude
  Deliverables/
    data-trust-validation.md   client-facing: defects found and controlled
    anomaly-answer-key.md      teaching artifact with solutions — not for the room
    anomaly-manifest.json      generated, so documented figures can't drift
    manifest.sha256            per-file hashes for reproducibility
  SESSION-HANDOFF.md
```

Naming: `dim_*`, `fct_*`, `br_*` (bridge), `xwalk_*`. `<entity>_key` is a surrogate
BIGINT, `<entity>_id` is the natural key with its source prefix retained.
Degenerate dimensions keep source names (`claim_number`, `claim_line_number`). All
identifiers lowercase so Snowflake's uppercase folding never forces quoted
identifiers in Sigma.

`anomaly-answer-key.md` stays separate from `data-trust-validation.md`. The latter
proves the defects were found and controlled; the former gives away the solutions.
Don't hand the answer key to a demo audience before the reveal.

---

## The model

Window: source data 2023-01-01 → 2025-12-31, analysis window trailing 24 months
2024-01 → 2025-12, claims paid-through 2026-02-28 so runout is real.

### Conformed dimensions

| Table | Grain | Rows | Notes |
|---|---|---|---|
| `dim_date` | 1 day, 2022-01-01→2026-12-31 | 1,826 | service / incurred / paid roles, `claims_completeness_factor` by incurred month, `is_holiday` |
| `dim_master_person` | 1 resolved person | 49,600 | `source_system_count`, `has_claims`, `has_ehr`, `is_multi_source`, `resolution_confidence` |
| `dim_member` | **SCD2**, 1 row per tracked change | 62,000 | Type 2 on plan product, county, attributed PCP, risk band. Type 1 on birth date, sex |
| `dim_provider` | **SCD2** | 7,400 | role-played four ways: referring / performing / billing / attributed PCP. NPI → TIN → org hierarchy |
| `dim_facility` | 1 site of care | 52 | 4 hospital / 12 clinic group / 8 urgent care / 10 ASC / 2 SNF / 16 other. Carries `tin`, `ccn` |
| `dim_coverage_plan` | 1 payer × product × plan × benefit year | 24 | MA and commercial HMO only. `line_of_business`, `funding_type`, `deductible_amount` |
| `dim_service_line` | 1 service line | 28 | crosswalked from claim taxonomy, EHR department, and contract category — deliberately imperfect |
| `dim_diagnosis` | 1 ICD-10-CM code | 1,400 | `ccsr_category`, `chronic_condition_flag`, `hcc_code` |
| `dim_procedure` | 1 code, all systems | 1,800 | `code_system` as discriminator ('CPT'/'HCPCS'/'ICD10PCS') |
| `dim_service_place` | 1 POS code | 30 | |
| `dim_drg` | 1 MS-DRG | 340 | inpatient only |
| `dim_claim_status` | 1 status | 14 | `is_paid`, `is_denied`, `is_reversal`, `is_adjustment` |

Two calls carried over from the modeling design, both worth keeping. **Payer
collapses into plan** — a four-row `dim_payer` is a snowflake for no gain, since
every attribute analysts slice by lives at plan grain. **One procedure dimension
with `code_system` as a discriminator** — splitting CPT from ICD-10-PCS is purer
and practically hostile, because "spend by procedure" then needs two joins and a
UNION every time.

**Every dimension gets a `-1 Unknown` and `-2 Not Applicable` row.** Facts resolve
unmatched keys to `-1` and carry a companion `<entity>_resolution_status` column
('MATCHED' / 'ORPHAN_SOURCE_VALUE' / 'SOURCE_NULL'). The mart stays inner-joinable
*and* the defect stays countable. The trap becomes "the analyst ignored the `-1`
bucket," which is the realistic failure mode anyway.

Only two dimensions are SCD2: provider (network status and affiliation) and the
attribution roster. Everything else Type 1. Type 2 everywhere is where synthetic
data projects die.

### Facts and bridges

| Table | Grain (one row =) | Rows |
|---|---|---|
| `fct_claim_line` | claim × line × adjudication version | 2,400,000 |
| `fct_claim_header` | claim × adjudication version | 520,000 |
| `br_claim_diagnosis` | claim header × diagnosis position 1–12 | 1,750,000 |
| `fct_encounter` | one EHR encounter | 650,000 |
| `br_encounter_diagnosis` | encounter × diagnosis × position | 2,100,000 |
| `fct_lab_result` | one resulted lab component | 700,000 |
| `fct_referral` | one referral order | 114,000 |
| `fct_referral_outcome` | one referral × confirming-event candidate | 114,000 |
| `fct_appointment` | one scheduled appointment | 700,000 |
| `fct_member_month` | member × year-month with coverage | 1,250,000 |
| `fct_eligibility_span` | member × plan × contiguous span | 75,000 |
| `vbc_attribution_month` | member × month, current version | 1,180,000 |
| `vbc_attribution_restatement` | only rows whose attribution changed | 85,000 |
| `br_provider_affiliation` | provider × facility × effective span | 9,200 |
| `xwalk_patient` | (source_system, source_patient_id) | 103,000 |
| `xwalk_provider` | (source_system, source_provider_id) | 14,000 |

Total ≈ 11.7M rows, roughly 250MB gzipped. Regenerates in about two minutes.

Storing the roster as a current table plus a **restatement delta table** rather
than a fully versioned history keeps it at 1.27M rows instead of ~3.8M while still
supporting "show me the original and the restated view."

`fct_claim_line` carries `DECIMAL(12,2)` money columns — never float — plus
`adjudication_seq`, `original_claim_number`, `is_current_version`, `net_sign`, and
`source_load_batch_id`. Both `member_key` (point-in-time-correct SCD2 row) and
`member_durable_key` (= `master_person_id`) sit on every fact. That dual key is
what serves both audiences: the Concord cut shows the type-2 mechanics, the ninja
cut joins the durable key against `dim_member_current`.

**The 837 diagnosis structure, modeled literally.** Diagnoses live at header grain
in `br_claim_diagnosis` at positions 1–12; claim lines carry four small integer
pointers into that list. That's how an 837P actually works, it avoids a third
diagnosis bridge, and the unpivot-and-resolve exercise is genuinely instructive.

**`fct_member_month` is the only sanctioned PMPM denominator**, built from
de-duplicated spans and carrying RAF so raw and risk-adjusted PMPM diverge. State
the rule plainly: never compute member-months from `fct_eligibility_span`.

**`fct_referral_outcome` is a real bridge, not ad-hoc SQL** — referral to
confirming event within a 90-day window, carrying `match_rule_version`,
`confirm_source` ('claim' / 'appointment' / 'both' / 'none'), and `confidence`.
Making confirmation rate a first-class modeled metric is the whole point.

### Identity resolution

`xwalk_patient` carries `source_system`, `source_patient_id`, `master_person_id`,
`match_method` ∈ {EXACT, DETERMINISTIC_NAME_DOB_ZIP, PROBABILISTIC,
MANUAL_OVERRIDE, UNMATCHED}, `match_score`, `match_run_date`, `is_active`.

Tiers: exact 82%, deterministic 13%, probabilistic 1.9% (scores 0.72–0.94),
unmatched 3.1%. Imperfect in **both** directions — under-match *and* 40 pairs that
over-match two genuinely distinct people. Over-matching is the more interesting
failure and is almost never demoed.

No SSNs, real or fabricated. Matching uses name + DOB + ZIP + a synthetic
subscriber ID; if a last-4 is needed for the deterministic tier, store a hash.

---

## Planted anomalies

Twelve, consolidated from both designs. Every one maps to a story beat, and
`anomalies.py` applies each as a named, logged mutation writing its expected naive
error to `anomaly-manifest.json`. Magnitude principle throughout: big enough to
move a headline KPI detectably, small enough to sit inside the range a real data
quality report produces. Nothing at 50%, nothing at 0.01%.

| # | Anomaly | Naive error | Detect / control |
|---|---|---|---|
| A1 | Auto-close rule at 1 of 12 sites, onset 2024-07-01 | 63% of closures at day 30 ±1 post-rule vs 4% pre; confirmation 38% vs 72% | Plot time-to-status before trusting any status field |
| A2 | North Ridge apparent vs true leakage | apparent 6% vs true 54%; rank 1→12; $2.7M | Confirm against claims *and* appointments independently |
| A3 | Stale EHR pick-list vs terminated TIN | Summit Point ASC terminated 2024-10-01, directory 14 months stale, ~$1.9M | As-of-service-date join against SCD2 network contract |
| A4 | Non-random crosswalk loss | 3.1% unmatched, skewed 2.4× toward North Ridge patients — so a naive inner join *understates* the finding | Profile unmatched against matched on several attributes |
| A5 | Crosswalk over-match | 40 pairs collapse two people; artificial super-utilizers contaminate the top-1% cost figure | Count distinct DOB/sex within `master_person_id`; the sex-mismatch query finds most in one line |
| A6 | Retro-termination of high-cost members | 340 members retro-termed in months containing a non-affiliated inpatient stay; 3.4 of the 8.4% PMPM "improvement" | Cohort-holding vs open-panel; compare roster versions |
| A7 | Claims runout | Oct 2025 78% / Nov 54% / Dec 31% complete; 2 more points of that 8.4% | Lag triangle; `claims_completeness_factor`; paid-date trends are complete, service-date trends are not |
| A8 | Overlapping eligibility spans | 3.5% of members; naive span-sum over-counts member-months 2.1%, concentrated in one acquired employer group whose PMPM then looks 9% better | De-dup priority `is_primary_coverage DESC, span_start DESC` |
| A9 | Duplicates both ways | 2,840 real dupes from a re-run extract inflate one month $1.1M *and* pass a surrogate-key uniqueness test; ~9,400 legitimate bilateral/repeat lines look like dupes and deduping them understates $780k | Grain uniqueness on the business key, never the surrogate; modifiers are part of line identity |
| A10 | Reversals, including 118 orphans | Three distinct wrong answers: `seq = 1` overstates 3.1%, `paid > 0` overstates 3.6%, naive inclusion drives one month negative | Two netting formulas must tie exactly; flag `is_orphan_reversal` and disclose |
| A11 | Same concept, different encoding | Encounter type `'AMB'` unmapped at one clinic (3.1% of ambulatory volume → UNKNOWN); sex as M/F/U vs HL7 1/2/9; one hospital renumbered mid-2024 so it splits in two | Distinct-value profiling by source **and by month** — the month cut makes the renumbering a visible step change |
| A12 | Provider and grain hygiene | 22% of providers hold 2+ concurrent affiliations, so a bridge fan-out overstates facility totals 31.6%; 1,312 orphan servicing providers concentrated 68% at one staffing-agency site, and inner-joining drops $2.9M; `COUNT(*)` understates services 11% vs `SUM(units)` | Anti-join count before every provider join; span predicates plus `allocation_pct` |

One inpatient stay emits one institutional claim plus three to eight professional
claims, all carrying the same `encounter_key` (nullable — 24% of claims have no
encounter because that care happened elsewhere). Counting claims as admissions
inflates volume five to eightfold. That's the best hazard in the set and it needs
no planting; it's just correct modeling.

---

## Realism method

**One latent risk variable drives everything.** Each member gets
`r ~ Lognormal(0, 0.85)`, age-adjusted `r_adj = r · exp(0.028·(age−40))`,
normalized to mean 1.0. Condition onset, encounter counts, fill counts, and cost
intensity all derive from it, so realistic correlation emerges rather than being
retrofitted by correlating a dozen marginals. This is the decision that matters
most — get it right and everything downstream looks plausible.

Households: draw subscribers and assign dependents over a family-size
distribution, so surnames, addresses, and group IDs **cluster into households**.
That's what makes A5's over-match plausible rather than arbitrary.

Conditions: 14 at benchmark prevalence (hypertension 32%, diabetes 10.5%, CHF
2.2%, active cancer 1.4%, and so on), assigned by a logistic model on age, sex,
and `log(r_adj)`, with intercepts calibrated by bisection until realized
prevalence hits target within 0.3pp. Comorbidity falls out of the shared risk term
— P(diabetes | hypertension) lands around 22% against a 10.5% marginal, close to
real. Explicit odds-ratio boosts for three pairs the latent variable
under-produces: DM→CKD 3.2, CHF→AFib 4.1, COPD→CAD 2.1.

Utilization uses Negative Binomial, not Poisson — healthcare counts are
overdispersed. Costs use a two-part lognormal per service category, multiplied by
facility contract factor and network factor (out-of-network billed 2.8× allowed,
paid at 60%).

**Assert the concentration curve, don't hope for it.** Top 1% of members = 22–30%
of spend, top 5% = 55–60%, bottom 50% = 3%. Plus a catastrophic cohort of about a
dozen members at $400k–$1.9M each. Normally distributed member costs kill the demo
on slide one; the concentration curve is the single most recognizable realism check
a healthcare audience applies.

Seasonality in three layers: respiratory (Jan 1.22 down to Jul 0.86), deductible
exhaustion on elective outpatient surgery (Nov 1.18, Dec 1.45), and benefit-year
reset in the liability mix (deductible share of member liability 62% in January
down to 11% in December). That third layer is nearly absent from synthetic
healthcare data and it's what makes someone who has done payer work sit up.

Code frequencies follow Zipf, never uniform: `p(rank) ∝ rank^(−1.1)`, so
99213+99214 land around 19% of professional lines and the top 50 CPT codes around
62%. Diagnosis draws are conditioned on the member's assigned conditions.

Magnitudes to hold: commercial PMPM $480–620, MA PMPM $900–1,150; commercial
admits/1000 55–70, MA 200–260; ALOS 3.9–4.6 days; readmissions 8–10% commercial,
14–17% MA. Paid-lag median 23 days, p90 64, p99 210.

Hard clinical constraints: no pregnancy outside female age 12–52, no
prostate procedures for female sex, no pediatric-only codes over 18, no TKA at POS
11. Enforced as an assertion that the filter removed **zero** rows at member grain
— which stays green, while the same assertion at master-person grain returns 40 and
catches A5.

### Credibility guardrails

- **NPIs deliberately fail the check digit**, and that choice is documented. Valid
  NPIs resolve to real clinicians in public NPPES, which is a genuine problem.
- **CPT descriptors are AMA copyright.** Store code numbers with short descriptors
  written for this project and say so in the README. ICD-10-CM, MS-DRG titles, and
  HCPCS Level II are public domain and usable as-is.
- Revenue codes on facility lines. A CPT on an inpatient facility line with no
  revenue code is an instant tell.
- Denials use real CARC/RARC semantics (CO-197 no auth, CO-97 bundled, PR-1
  deductible). **CO-45 is a contractual write-off, not a denial** — treating it as
  one is the fastest way to lose a revenue-cycle person in the room.
- Authorization stays distinct from referral. Conflating them is another tell.
- Attribution is plurality-of-primary-care-visits, retrospective, monthly
  restatement, minimum one qualifying visit in the lookback.
- Invented payer, health system, facility, and provider names. Plausible metro ZIPs
  not tied to any real facility address.

### Synthetic labeling, belt and suspenders

Schema `healthcare_data_hub_synth`, table prefix `hdh_`, a
`data_classification = 'SYNTHETIC'` column on every fact and dimension, a
single-row `_synthetic_data_notice` table that surfaces in any catalog picker, and
a constant field available to dashboards reading *"Synthetic data — Concord
demonstration asset. Not derived from real patient records."* It appears on every
screenshot and every video frame, both cuts, no exceptions.

State plainly that the data is wholly fabricated, so HIPAA de-identification
standards do not apply and are not claimed. **Never write "HIPAA compliant."**

### Reproducibility

One `MASTER_SEED` in `config.py`. Never `np.random.seed()` — use
`np.random.default_rng(SeedSequence(MASTER_SEED).spawn(...))` with one spawned
child per module, so adding a draw in `claims.py` cannot shift a byte in
`clinical.py`. Derive each child via `spawn_key=(zlib.crc32(module_name),)`, not
Python's builtin `hash()`, which is per-process salted and will silently break
reproducibility across runs.

Every output sorted by business key before write. `build.py --verify` writes
SHA-256 per file to `manifest.sha256` and re-compares on rerun, with the manifest
header recording Python and library versions.

`anomalies.py` runs as a **separate final stage**, not inline. Three payoffs: the
answer key is generated so documented figures can't drift from the data;
`--no-anomalies` yields a **clean twin dataset**, which is the best teaching device
in the project ("same analysis, clean data, the delta is the trap"); and each
defect is independently tunable.

Write claim-line generation as a loop over the 36 service months with per-chunk
writes from day one, even though demo scale doesn't need it — otherwise a larger
scale is a rewrite rather than a flag.

---

## Validation

`Validation/validate.py` driven by `expectations.yml`, writing
`Deliverables/validation_results.json` and rendering `data-trust-validation.md` in
the same shape as the Q4 Mill document: verdict table up front, dollar impact per
finding, corrected versus claimed figures.

**The design point that makes this work: planted anomalies assert as `EXPECTED`
with a specific magnitude, not as failures.** A suite that goes red on purpose
teaches nothing. One that reads *"orphan servicing providers: expected 1,312,
actual 1,312, $2.9M exposure — CONTROLLED"* is the artifact that wins a room of
data leaders. Severities: ERROR / WARN / INFO / EXPECTED. Exit non-zero on any
ERROR so it's CI-able.

What it asserts:

1. **Grain uniqueness on business keys, never surrogates.** Raw claim lines on
   `(claim_number, claim_line_number, adjudication_seq)` expect 2,840 violations;
   mart post-dedupe expects zero. Both SCD2 dimensions: no overlapping spans per
   durable key, exactly one `is_current`, no gaps.
2. **Referential integrity** as a matrix — fact × dimension × orphan count ×
   orphan % × **orphan dollars**. That last column makes it a business document
   rather than a QA log.
3. **Reconciliation to the penny.** `header.total_paid = SUM(line.paid)` per claim
   version; both netting formulas agree; `allowed = paid + deductible + copay +
   coinsurance + cob` on 100% of lines; `billed ≥ allowed ≥ paid` with the
   out-of-network exception carved out and counted. Presented as a **reconciliation
   ladder** — raw total → dedupe → conformance → mart total — where every step's
   delta carries a named reason. That ladder is the most demo-valuable output here.
4. **Distribution controls** so realism can't drift: top-1% cost share in
   [0.22, 0.30]; every chronic prevalence within 0.5pp of target; P(DM|HTN) in
   [0.18, 0.26]; paid-lag median in [20, 26] days; Dec:Jun elective outpatient
   surgery ratio in [1.35, 1.60].
5. **Clinical plausibility.** Sex-inappropriate codes = 0 at member grain, = 40 at
   master-person grain (EXPECTED, catches A5). LOS = discharge − admit exactly. No
   elective encounters on the 11 federal holidays. No future dates.
6. **Conformance coverage** — for every coded column in every source, assert 100%
   of distinct source values have a mapping. Expected failure: `'AMB'`. This check
   generalizes to client work better than anything else in the suite.
7. **Question-ladder assertions** — one per demo question, confirming each
   engineered insight is present at the stated magnitude. This is the build's
   definition of done: if the $2.7M or the 1→12 rank inversion isn't there, the
   build failed regardless of whether every row is internally consistent.
8. **Runout triangle** as a table, asserting `claims_completeness_factor` is below
   threshold for exactly the months under 95% complete.

`SQL/90_demo_query_pack.sql` pairs a naive and a correct query for every anomaly,
each returning both figures side by side so the delta is the punchline.

---

## Serving both audiences from one build

Ship `dim_member_current` and `dim_provider_current`, plus one wide file
`vw_claim_line_enriched` — claim line joined to every Type-1 dimension, no bridges,
one row per claim line, safe to sum. That gets the hipstervizninja audience
productive in five minutes; the star underneath is what makes the Concord audience
take the asset seriously. Pointing out in the demo that the flat view is only safe
*because* the bridges were kept out of it is itself the lesson.

The two cuts diverge in vocabulary order. Concord names the pattern first
("conformed dimension," "as-of join") then shows the failure. The ninja cut shows
the failure, names the technique, and labels the pattern last — front-loading
vocabulary loses a hands-on-keyboard audience in seconds. And the ninja cut can say
"whoever turned that rule on made your dashboard lie" where the Concord cut cannot:
same fact, different assignment of blame. In the Concord telling the villain is the
absence of architecture, never the client's staff — the auto-close rule was a
reasonable local fix by someone clearing a worklist, with a global cost no local
actor could see. That framing is what makes the story safe to tell in front of
people whose org has the same rule running right now.

Full narrative detail, personas, and the nine-question ladder go in
`docs/narrative.md` as the spec of record the schema answers to.

---

## Build order

1. `README.md`, `PLAN.md`, `docs/narrative.md`, `docs/data-model.md` — the spec,
   written first because the anomaly magnitudes are the generator's contract.
2. `Generators/config.py`, `names.py`, `ids.py`, `reference.py`.
3. `population.py` → `providers.py` → `eligibility.py` → `clinical.py` →
   `scheduling.py` → `claims.py` → `attribution.py` → `crosswalk.py`.
4. `anomalies.py`, then `write.py` and `build.py`.
5. `Build/build_mart.py`.
6. `Validation/validate.py` + `expectations.yml`.
7. `SQL/` — DDL and COPY generated from the schema registry, transforms written by
   hand as the lift artifact.
8. `Deliverables/` — generated manifests, then `data-trust-validation.md` and
   `anomaly-answer-key.md`.
9. `SESSION-HANDOFF.md`.

## Verification

- `python Generators/build.py --scale dev` completes clean, then
  `--scale demo`, then `--verify` twice to confirm byte-identical regeneration.
- `python Build/build_mart.py` then `python Validation/validate.py` exits zero,
  with every planted anomaly reporting EXPECTED at its stated magnitude and no
  ERROR rows.
- The question-ladder assertions confirm the headline numbers: North Ridge ranks
  1 of 12 on the EHR-only metric and 12 of 12 on the joined metric, leakage is
  ~$2.7M with ~$1.1M recapturable, and the Summit Point finding is ~$1.9M.
- Spot-check the concentration curve, the January deductible spike, and the
  July 2024 step change in North Ridge's closure distribution — those three are
  what a healthcare audience checks first.
- Load `Mart/vw_claim_line_enriched.csv.gz` into Tableau Public or Sigma and
  confirm it reads without type coercion warnings and sums correctly.
- Confirm no real NPI passes a check-digit validator and no SSN-shaped column
  exists anywhere in the output.

## Deliberately not in this session

No dashboard or workbook build in Sigma or Tableau. No DuckDB or Snowflake
instance stood up. No Parquet. No video or deck production. The front end comes
next session, once the model has been reviewed.
