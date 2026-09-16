# Data model

## Layers

Without a local database engine the layer boundary lives in the file tree
rather than in schemas. The shape is the same one you would build in
Snowflake, and `SQL/` holds that version.

```
Source Data/     five source systems as landed. Dirty, string-typed,
                 defects intact. This is the shippable artifact.
      |
      |  Build/build_mart.py   (conform, resolve, dimension, fact, serve)
      v
Mart/            conformed dimensions, facts, bridges, and one wide view
```

Naming, so nothing needs quoting in Snowflake, Sigma, or Tableau: all
identifiers lowercase; `dim_`, `fct_`, `br_` (bridge), `xwalk_` prefixes;
`<entity>_key` for surrogates, `<entity>_id` for natural keys. Degenerate
dimensions keep their source names (`claim_number`, `claim_line_number`).

One honest note about the compromise. Modeling logic would be more credible
executed in inspectable SQL than in pandas, and it will be once this lands in
a warehouse. For now the Python build and the reference SQL are maintained as
two expressions of the same transform, and the validation suite asserts the
Python output meets the stated expectations.

## Source systems

Each one earns its place by contributing something no other source can.

| Landing | System | Only it contributes |
|---|---|---|
| `raw_ehr` | CareLine EHR | Clinical intent, a second patient identity space (MRN), and care that generated no claim |
| `raw_clm` | Meridian claims | Money, adjudication state, reversals, POS, DRG, revenue codes, paid-date lag |
| `raw_elig` | Meridian enrollment | Denominators. No rate, no PMPM, no per-1000 without it |
| `raw_pm` | PracticeOne scheduling | Whether care was actually scheduled and attended — the second confirmation path — and the workflow rule that explains the aha |
| `raw_vbc` | Northlake attribution feed | Who counts against the contract, and the retroactive restatement history |
| `raw_ref` | Terminology and MDM | Code sets and the type-2 network contract |

## Three identity spaces, deliberately

Patients arrive as `member_id` (eligibility and claims), `mrn` (EHR), and
`subscriber_id` plus a two-digit person code (attribution feed). The third
*looks* joinable to the first and is not. Providers arrive as a credentialed
NPI, an EHR internal id, and a claim-side NPI with dirty values.

This is the hub's center of gravity. The EHR-to-claims join is structurally a
three-hop through the crosswalk, and it loses about 3% — non-randomly.

### Crosswalk design

`xwalk_patient` carries `source_system`, `source_patient_id`,
`master_person_id`, `match_method`, `match_score`, `match_run_date`.

| Tier | Share | Score |
|---|---|---|
| `EXACT` | ~82% | 1.000 |
| `DETERMINISTIC_NAME_DOB_ZIP` | ~13% | 0.95–0.999 |
| `PROBABILISTIC` | ~1.9% | 0.72–0.94 |
| `UNMATCHED` | ~3.1% | null |

Imperfect in **both** directions, because both failure modes teach something
different:

- **Under-match.** The unmatched share skews more than twice as heavily toward
  North Ridge patients. A naive inner join therefore deletes part of the
  headline finding and *understates* it.
- **Over-match.** Roughly forty master person IDs each collapse two genuinely
  distinct people — twins and Jr/Sr pairs matched on name, date of birth and
  address. They surface as artificial super-utilizers at the top of the cost
  distribution, contaminating precisely the top-1% figure the demo quotes.
  Over-matching is the more interesting failure and is almost never
  demonstrated.

Every fact carries **both** `member_key` (the point-in-time correct row) and
`member_durable_key` (the master person id). That dual key is what serves two
audiences from one model: the architecture-minded join the point-in-time key
and see the type-2 mechanics, and the hands-on analyst joins the durable key
against a `_current` view and gets a right answer in five minutes.

## Conformed dimensions

| Table | Grain | Notes |
|---|---|---|
| `dim_date` | one day | service, incurred and paid roles; `claims_completeness_factor`; `claims_runout_complete_flag`; July fiscal year |
| `dim_member` | one member | type 1 on demographics; carries the durable key |
| `dim_provider` | **type 2** | role-played four ways: referring, performing, billing, attributed PCP |
| `dim_network_contract` | **type 2** | participation by TIN and effective window. The as-of join lives here |
| `dim_facility` | one site of care | 4 hospitals, 12 clinic groups, 8 urgent care, 10 ASCs, 2 SNFs, plus diagnostic and therapy sites |
| `dim_coverage_plan` | payer × product × plan × benefit year | MA and commercial HMO only |
| `dim_service_line` | one service line | crosswalked from three sources, deliberately imperfect |
| `dim_diagnosis` | one ICD-10-CM code | CCSR category, chronic flag, HCC, sex and age restrictions |
| `dim_procedure` | one code, **all systems** | `code_system` as discriminator |
| `dim_drg`, `dim_service_place`, `dim_claim_status` | one code each | |

### Two opinionated calls

**Payer collapses into plan.** A `dim_payer` with one row is a snowflake for
no gain: every attribute analysts actually slice by — line of business,
funding type, product, metal tier — lives at plan grain.

**One procedure dimension, `code_system` as a discriminator.** Splitting CPT
from ICD-10-PCS is technically purer and practically hostile, because "spend
by procedure" then needs two joins and a UNION every single time.

### Unknown members

Every dimension carries a `-1 Unknown` and a `-2 Not Applicable` row. Facts
resolve unmatched keys to `-1` and carry a companion
`<entity>_resolution_status` column with values `MATCHED`,
`ORPHAN_SOURCE_VALUE`, or `SOURCE_NULL`.

This is better than leaving broken keys in the mart: the mart stays
inner-joinable *and* the defect stays countable. The trap then becomes an
analyst who ignores the `-1` bucket, which is the realistic failure mode
anyway.

Only two dimensions are type 2 — provider and network contract. Everything
else is type 1. Type 2 everywhere is where synthetic data projects die.

## Facts and bridges

| Table | Grain (one row =) |
|---|---|
| `fct_claim_line` | claim × line × adjudication version |
| `fct_claim_header` | claim × adjudication version |
| `br_claim_diagnosis` | claim header × diagnosis position 1–12 |
| `fct_encounter` | one EHR encounter |
| `br_encounter_diagnosis` | encounter × diagnosis × position |
| `fct_lab_result` | one resulted lab component |
| `fct_referral` | one referral order |
| `fct_referral_outcome` | one referral × confirming-event evaluation |
| `fct_member_month` | member × year-month with coverage |
| `fct_eligibility_span` | member × plan × contiguous span |
| `vbc_attribution_month` | member × month, current roster version |
| `vbc_attribution_restatement` | attribution change × the roster version that made it |
| `vbc_roster_version` | one monthly roster production run |
| `vbc_contract_terms` | contract × performance year |
| `fct_member_year_cost` | member × performance year, truncation applied |
| `fct_claims_lag_triangle` | service month × lag month |
| `br_provider_affiliation` | provider × facility × effective span |

### The pieces worth reading

**The 837 diagnosis structure, modeled literally.** Diagnoses live at *header*
grain in `br_claim_diagnosis` at positions 1–12. Claim *lines* carry pointers
into that list rather than their own codes. That is how an 837P actually
works, it avoids a third diagnosis bridge, and the unpivot-and-resolve
exercise is one no other synthetic healthcare dataset bothers to reproduce.

**`fct_member_month` is the only sanctioned PMPM denominator.** Built from the
gaps-and-islands *union* of a member's coverage, not from summing span
lengths. About 3.5% of members carry overlapping spans — COBRA alongside
active coverage, and a plan change where the prior span was never terminated —
and summing spans double counts every one. Worse, the overlap concentrates in
one acquired employer group, so the error is **uneven**: that group's PMPM
reads roughly 10% better than truth. A number that is wrong unevenly is the
kind that survives review.

**`fct_referral_outcome` is a real bridge, not ad-hoc SQL.** Referral to
confirming event within a 90-day window, carrying `match_rule_version`,
`confirm_source` (`CLAIM` / `APPOINTMENT` / `BOTH` / `NONE`), and
`confidence`. Making confirmation a first-class modeled metric with a
versioned rule is the whole point: it is auditable, and it can be challenged
on its rule rather than on somebody's workbook formula.

**Header versus line.** DRG, admit and discharge dates, length of stay,
disposition and the claim total live *only* on the header, so any
DRG-by-procedure question is forced through the join.
`header.total_claim_paid_amount = SUM(line.paid_amount)` per claim version,
exact to the penny.

**One admission, several claims.** An inpatient stay emits one institutional
claim plus several professional ones (attending, surgeon, anesthesia,
radiology read), all carrying the same `encounter_id`. Counting claims as
admissions inflates volume several fold. The correct answer is
`COUNT(DISTINCT encounter_id)`. About 24% of claims carry no `encounter_id` at
all, because that care happened outside Northlake — which is exactly why the
hub is necessary.

**The roster is versioned, and the restatement runs both ways.** The roster is
produced monthly; `vbc_attribution_month` carries the current version and
`vbc_attribution_restatement` carries every change stamped with the version
that made it, wide enough (site, line of business, member-months, risk score)
that any earlier version reconstructs without touching another table:

```
roster at version V
  = current roster
  − additions applied after V
  + terminations applied after V
```

Changes run in both directions — `new_status` is `RETRO_TERMINATED` or
`ATTRIBUTED`. A restatement history that only ever removes members models the
convenient direction and nothing else, and the additions are drawn without
reference to cost so the net effect is honest rather than manufactured.

**Risk scores are normalized to a book mean of 1.0, within line of business.**
Commercial and Medicare Advantage normalize separately, because that is what a
contract does: a commercial 1.0 and an MA 1.0 describe very different people
and neither is scored against the other. `fct_member_month` then applies an
annual re-scoring factor, so "did the population get sicker or did we code it
better" is a question the data can answer. Raw morbidity weights were shipping
before, which made `risk_adjusted_benchmark_pmpm` a number with no contractual
meaning in either direction.

**High-cost truncation is an annual, member-level cap.** `fct_member_year_cost`
applies the threshold on `vbc_contract_terms` — roughly the 99th percentile of
member-year allowed for each book, which is the MSSP rule and removes 6–10% of
spend. `fct_claim_line.allowed_amount_truncated` is that cap allocated back
down pro rata so the cap is sliceable by month and site; it sums to the
member-year figure exactly. Applying a threshold per claim line instead — the
obvious shortcut — caps nothing, because no single line reaches it.

**Completeness is derived, not asserted.** `fct_claims_lag_triangle` develops
each service month by paid-lag month, and chain ladder over the mature months
reproduces `dim_date.claims_completeness_factor` from the paid dates alone. A
cell counts as observable only where the *whole* development period had
elapsed by the paid-through date — the end of the lag month, not its start.
Counting a period the extract only half covers puts a partial month of payments
beside full ones, and the chain ladder reads the missing half as a real
slowdown: the same error as trending to the right edge, one level down.

**Reversals and adjustments.** Three columns do the work: `adjudication_seq`,
`is_current_version`, `net_sign`. A reversal is a full negation of the version
it supersedes; an adjustment is that reversal plus a new positive version. A
v3 negates the v2 *replacement*, not the original v1, or the arithmetic stops
closing.

Two sanctioned nettings tie exactly:

```sql
SELECT SUM(paid_amount) FROM fct_claim_line;
SELECT SUM(paid_amount) FROM fct_claim_line WHERE is_current_version;
```

Note there is **no reversal exclusion** in the second. Orphan reversals — ones
whose original adjudicated before the window opened — are current and negative
on purpose, so filtering them out breaks the tie. That is precisely why the
orphan-reversal anomaly and this design are paired.

## Source of truth by attribute

Where two sources disagree, the model has to pick, and the pick has to be
documented rather than implicit.

| Attribute | Source of truth | Why |
|---|---|---|
| Sex, date of birth | Eligibility | It is the enrollment record of fact, and it is what the payer adjudicates against |
| Diagnosis detail | EHR | Claims carry only what was billed |
| Cost | Claims | The EHR has no idea what anything cost |
| Network status as of a date | `dim_network_contract` | The EHR directory is a stale copy and is treated as evidence of belief, never of fact |
| Coverage exposure | `fct_member_month` | Never the raw spans |
| Attribution | `vbc_attribution_month` plus the restatement table | Both the original and restated views must reproduce |

## Money and types

Every money column is `NUMBER(12,2)` and never `FLOAT`. The line identity
holds to the penny on 100% of rows, every adjudication version:

```
allowed = paid + deductible + copay + coinsurance + cob
billed >= allowed
```

CO-45, the contractual write-off, is `contractual_writeoff_amount` — an
**amount column, not a denial status**. Treating it as a denial is the fastest
way to lose a revenue-cycle person in the room.

No `ARRAY`, `OBJECT` or `VARIANT` columns anywhere in the mart. The diagnosis
bridges exist precisely so arrays are not needed, and a semi-structured column
would break both Tableau extracts and Sigma.

## The serving view

`vw_claim_line_enriched` is one row per claim line, joined to every type-1
dimension, with no bridges. It is safe to sum.

It is safe to sum *only because* the diagnosis bridges were deliberately kept
out of it — and saying that out loud during the demo is itself the lesson.
