# Provider Incentive Program — Sigma Build Plan

A Sigma workbook that computes, explains and defends the distribution of a shared-savings
bonus pool across Northlake Health Partners' twelve attributed clinic groups.

Planning document. **Nothing is built in Sigma from this pass.** Companion wireframe:
[provider_incentive_program_wireframe.html](provider_incentive_program_wireframe.html).

Every figure in this plan is measured from the shipped `demo` build (seed 20260911), not
transcribed from a design. The commands that produced them are in
[§18 Verification](#18-verification).

---

## 1. Context

[Healthcare Data Hub](README.md) is a synthetic provider-side value-based-care dataset:
five source systems, 26 mart tables, twelve planted data-quality defects. Northlake is
financially accountable for a panel whose care it can see about 60% of, under two risk
contracts with Meridian Health Plan.

The dataset shipped with no front end. This is the first application built on it, and it was
chosen because a provider incentive program is the one artefact in value-based care where a
data-quality defect converts directly into a wrong cheque. Every other VBC dashboard produces
a misleading chart. This one produces a misallocated payment, and the misallocation is
measurable: **$488,705 of a $4.2M pool, 11.6%, moves when you fix one join.**

### Scope decisions, confirmed

| Decision | Choice |
|---|---|
| **Payee grain** | The **twelve clinic groups**, not individual clinicians. Reasoning in [§4](#4-why-the-payee-is-a-clinic-group-and-not-a-clinician). |
| **Where logic lives** | A new Sigma **data model**, `Northlake VBC`. The workbook is presentation-only, as in [Store Performance Command Center](../Retail/STORE_PERFORMANCE_COMMAND_CENTER_BUILD.md). |
| **Performance years** | **PY2024** settled (100% claims-complete) and **PY2025 YTD through September** in flight. October–December 2025 is displayed but never scored. |
| **Cost target** | **Peer-relative**, not the shipped `vbc_benchmark`. Reasoning in [§5](#5-why-vbc_benchmark-cannot-be-the-cost-target). |
| **Attributed population** | `vbc_attribution_month` — the payer's roster — never `fct_member_month`. Reasoning in [§6](#6-the-denominator-trap-two-rosters-that-disagree). |

---

## 2. What the program is

A four-domain weighted scorecard, 100 points, distributing a fixed pool.

| Domain | Pts | Measure | Direction |
|---|---|---|---|
| **Cost** | 25 | Risk-adjusted allowed A/E ratio vs the attributed-population mean | lower better |
| **Utilization** | 10 | ED visits per 1,000 attributed member-years | lower better |
| **Quality** | 30 | HbA1c testing rate among attributed diabetics (documented two-source union) | higher better |
| **Network integrity** | 25 | True out-of-network referral rate, destination network status joined **as of placed date** | lower better |
| **Access** | 10 | Appointment no-show rate | lower better |

Each measure is scored on a three-tier gate against the peer distribution: zero points at the
25th percentile of performance, 60% of points at the peer mean, full points at the 75th
percentile, linear between. The pool is then distributed on points **weighted by attributed
member-months**, so a group is rewarded for performance and sized by the population it carries.

Pool for modelling: **$4,200,000**.

---

## 3. The finding the app exists to surface

North Ridge Orthopedics' referral leakage is invisible on EHR data alone and visible the
moment the destination's network status is joined as of the date the referral was placed.

**PY2025 YTD, ORTHO-NR:**

| | EHR pick-list | As-of contract join |
|---|---|---|
| Out-of-network referral rate | **6.9%** — best of twelve | **52.8%** — worst of twelve |
| Peer range on the same measure | 14.0–18.5% | 20.1–23.1% |
| Composite rank | **3 of 12** | **12 of 12** |
| Bonus earned | $547,607 | $288,466 |

**The rank moves nine places and $259,141 leaves the group.** Across all twelve groups
$488,705 is redistributed — 11.6% of the pool.

Three mechanisms, all independently visible in the data:

1. **The destination.** 2,010 of ORTHO-NR's PY2025 referrals go to Summit Point Surgery Center.
   `ref_network_contract` has Summit as `PAR` through 2024-09-30 and `NONPAR` from 2024-10-01.
   The EHR referral directory still reads `PAR`. Summit alone carries **$4,695,077** of
   out-of-network allowed spend.
2. **The auto-close rule.** From 2024-07-01 a PracticeOne scheduling rule closes ORTHO-NR
   referrals at day 30 regardless of outcome. The month it turns on, closure rate steps
   0.825 → 0.969 and the confirmed-event rate drops 0.805 → 0.565.
3. **The fingerprint.** 69.0% of ORTHO-NR closures land in days 25–31, against 9.0% for every
   other group, with a spike exactly at day 30. No clinical process produces that shape.

| Days to closure | ORTHO-NR | All others |
|---|---|---|
| 0–10 | 8.5% | 24.5% |
| 10–25 | 18.2% | 52.8% |
| **25–31** | **69.0%** | **9.0%** |
| 31+ | 4.3% | 13.6% |

The framing discipline from [docs/narrative.md](docs/narrative.md) holds here and matters more
in an incentive app than anywhere else: **the villain is the absence of architecture, never the
client's staff.** Of ORTHO-NR's 170 referring providers, the 30 with a scoreable volume
(n ≥ 30) all sit between 54.8% and 66.7% true out-of-network. That is not a few bad actors —
it is one pick-list nobody owned. A scorecard that names individuals here would be both unfair
and wrong.

---

## 4. Why the payee is a clinic group and not a clinician

Attribution in this dataset lands on a **site**. `vbc_attribution_month` carries
`attributed_site_code` and no provider column.

Clinician-level panels *can* be derived — plurality of visits at the attributed site assigns
24,339 of 25,116 attributed members to one of 1,719 providers. The panels are then too small
to carry a rate:

```
panel size    median 10    mean 14.2    p75 19    max 96
```

A ten-member panel means one open care gap moves the quality measure ten points. A
clinician-level diabetic denominator here is roughly two to seven people. **Any cost or
quality measure paid at clinician level in this dataset is paying on sampling noise.**

Two further structural facts point the same way:

- Five of the twelve attributed groups — ORTHO-NR, CARD-RVB, GI-EGR, SPIN-MRD, WMN-SBR —
  employ **zero PCPs**. Only 33–39% of their attributed members have ever seen a PCP anywhere.
  "Attributed PCP" is not a coherent concept for roughly 40% of the book.
- Group denominators are sound: 697–3,293 members, 5,999–28,460 member-months in PY2025 YTD.

**Clinician level appears in exactly one place**, because it is the one place the denominator
supports it: referral stewardship. Referrals run a median of 48 per referring provider across
1,810 providers. Page 4 lists referring providers with `n ≥ 30` and suppresses the rest, and it
is labelled a coaching view, not a payment view.

---

## 5. Why `vbc_benchmark` cannot be the cost target

The shipped benchmark is calibrated against the **whole book**, not the attributed cohort.
Measured over PY2024:

| Population | Commercial allowed PMPM | MA allowed PMPM |
|---|---|---|
| All 48,000 members (`fct_member_month`) | $552 | $1,022 |
| `vbc_benchmark.benchmark_pmpm` | **$582** | **$1,116** |
| Attributed roster only (25,116 members) | **$946** | **$1,422** |

The benchmark tracks the all-member figure closely and the attributed figure not at all, which
is correct and expected — attribution selects for care-seekers, so the attributed sub-population
runs richer than the book it is drawn from.

Two consequences:

1. `risk_adjusted_benchmark_pmpm` is unusable as a cost target. It is a fixed
   `benchmark_pmpm × mean_risk_score × 1.1765` and averages **$266** for commercial against an
   attributed actual of $946. Scored against it, all twelve groups fail cost and nobody earns.
2. The external benchmark still belongs on the page — for the **contract-level** question
   ("will Northlake earn shared savings?", Marcus's question), which is a different question
   from the **internal distribution** ("how is the pool split?", Dana's and Priya's).

So: **peer-relative cost scoring**, each group's risk-adjusted A/E against the attributed-
population mean. This is also how most real provider incentive programs work — a fixed pool
distributed on relative performance — so the choice is defensible on its merits and not just a
workaround. Keep the external benchmark visible as contract context on page 1, clearly
separated from the scorecard.

`Expected Allowed` per member-month is `benchmark_pmpm(LOB, month) × (member risk_score / mean_risk_score(LOB, month))`.
The benchmark's *level* cancels out of a peer-relative comparison; its *risk and seasonality
shape* is what the measure is borrowing, and that part is sound.

---

## 6. The denominator trap: two rosters that disagree

| | Members | Member-months |
|---|---|---|
| `fct_member_month` | 48,000 | 1,501,125 |
| `vbc_attribution_month` | **25,116** | **808,971** |

`fct_member_month.attributed_site_code` is populated for **all 48,000 members** — it is
Northlake's own belief about attribution. `vbc_attribution_month` is the payer's roster, and it
is what settlement is computed from. They disagree two ways:

- 692,154 member-months exist in `fct_member_month` and not on the payer's roster.
- Of the 808,971 they share, the attributed site **disagrees on 7.03%**.

A program built off `fct_member_month` pays on a population Meridian is not paying Northlake
for. The data model must make the payer roster the only path to a denominator, and the
workbook must never expose `fct_member_month.attributed_site_code` as a grouping field.

---

## 7. Runout, and why the scored window stops at September

`dim_date.claims_completeness_factor` is measured from the generator, not estimated:

| Service month | Completeness | Scored? |
|---|---|---|
| ≤ 2025-09 | 1.00 | yes |
| 2025-10 | 0.78 | no |
| 2025-11 | 0.54 | no |
| 2025-12 | 0.31 | no |

Read PY2025 naively and Northlake's PMPM falls from $1,034 in March to $483 in December — a
53% "improvement" that is almost entirely artefact. The scored window is therefore
**January–September 2025**, gated on `claims_runout_complete_flag = TRUE`. October onward
appears on the trend chart as a dashed accrual estimate with the completion factor applied and
a label saying it is not scored.

**Do not let the completion factor into the scorecard.** Grossing up an incomplete month and
paying on it pays on a forecast. The factor is for the trend chart and the accrual view only.

---

## 8. Roster restatement: real, and smaller than it looks

1,665 attributed member-months were retroactively terminated. 224 are the poisoned kind —
high-cost members dropped in exactly the months containing an inpatient stay at a
non-affiliated hospital — and every one lands in 2025.

Reconstructing the pre-restatement roster and re-running PMPM on identical claims:

| Month | Original roster | Restated roster | Change |
|---|---|---|---|
| 2025-03 | $1,033.9 | $1,035.0 | +0.1% |
| **2025-04** | $905.7 | $807.1 | **−10.9%** |
| 2025-05 | $919.5 | $822.6 | −10.5% |
| 2025-07 | $855.5 | $777.0 | −9.2% |
| 2025-09 | $894.0 | $832.4 | −6.9% |

Five to eleven points of monthly PMPM improvement with no change in care.

**But be straight about the grain.** At full-year, group level the effect washes out: across
PY2024 every group moves less than a dollar of PMPM, at most 0.54%. It bites on **monthly
trend** and on the **in-flight year**, not on a settled annual score. The app should carry a
cohort-hold toggle and a roster-version stamp because both are cheap and correct — not because
they will change a PY2024 payout. Overselling this is the fastest way to lose a numerate
audience.

---

## 9. Data model: `Northlake VBC`

New Sigma data model. Nothing exists in Sigma today — this data is gzipped CSV on local disk,
so **step zero is getting it in**: either CSV upload (26 mart files, largest 62MB) or the
Snowflake lift in [SQL/](SQL/), which per [SESSION-HANDOFF.md](SESSION-HANDOFF.md) has never
been executed and should be expected to need fixes.

### Sources consumed

| Table | Grain | Role |
|---|---|---|
| `vbc_attribution_month` | member × month | **the only legal denominator** |
| `vbc_benchmark` | month × LOB | risk and seasonality shape for Expected |
| `vbc_attribution_restatement` | member × month | roster-version reconstruction |
| `vw_claim_line_enriched` | claim line | allowed and paid dollars, OON flag |
| `fct_encounter` | encounter | ED and inpatient utilization |
| `fct_referral` + `fct_referral_outcome` | referral | network integrity, both confirmations |
| `fct_lab_result` | result | HbA1c numerator, EHR side |
| `br_claim_diagnosis`, `br_encounter_diagnosis` | bridge | diabetic denominator, both sides |
| `dim_diagnosis` | ICD-10 | `condition_code`, `chronic_condition_flag`, `hcc_code` |
| `dim_provider_current`, `dim_facility`, `dim_date`, `dim_member` | dimension | conformed attributes |
| `ref_network_contract` | TIN × window | **type-2, as-of joined** |

### Hidden build steps

| Element | What it does |
|---|---|
| `src_roster_current` | `vbc_attribution_month` at `as_of_version = 2`. The scoring denominator. |
| `src_roster_original` | `src_roster_current` unioned with `vbc_attribution_restatement` — reconstructs the pre-restatement roster for the cohort-hold toggle. |
| `member_month_spend` | `vw_claim_line_enriched` filtered `is_current_version = TRUE`, summed to member × service month. **Materialize.** Collapses 1.02M lines before any join. |
| `member_month_expected` | Roster joined to `vbc_benchmark` on month + LOB; Expected Allowed per member-month. |
| `dx_diabetic_member_month` | Union of claim-side and encounter-side DM2 diagnoses to member × month. Distinct. |
| `a1c_event_member_month` | Union of `fct_lab_result.lab_code = 83036` and claim `procedure_code = '83036'` to member × month. Distinct. |
| `network_status_asof` | `ref_network_contract` resolved for a `(site_code, date)` pair where `effective_date <= date <= expiration_date`. **The single most important element in the model.** |
| `referral_scored` | `fct_referral` → `fct_referral_outcome` on `referral_id`, plus `network_status_asof` on destination + `placed_date`. Carries EHR-directory status *and* true status side by side so the gap is a field, not an argument. |
| `encounter_util` | ED and inpatient counts to member × month. |
| `appointment_access` | `pm_appointment` to site × month, completed / no-show / cancelled. |

### Published

**`Group Performance Month`** — the spine. One row per **attributed group × month**, carrying
member-months, risk, actual and expected allowed, ED and inpatient counts, diabetic denominator
and HbA1c numerator, referral counts by true and apparent network status, and appointment
outcomes. Everything downstream aggregates this.

**`Group Scorecard`** — one row per group × performance year: the five domain scores, the
composite, the rank, and the modelled payout under both the naive and governed definitions.

**`Referring Provider Stewardship`** — one row per referring provider × performance year, with
`n < 30` flagged for suppression. The coaching view.

Every metric carries a description naming its denominator. That is not documentation garnish —
it is the thing that lets Ask a Question answer correctly and lets Ken certify a number.

---

## 10. Measures, build-ready

Sigma syntax, written against `Group Performance Month` unless noted.

### Denominator and cost

| Field | Formula | Notes |
|---|---|---|
| `Attributed Member Months` | `Sum([Member Months])` | From the payer roster only |
| `Attributed Members` | `CountDistinct([Member Id])` | |
| `Attributed Member Years` | `[Attributed Member Months] / 12` | The per-1,000 denominator |
| `Actual Allowed` | `Sum([Allowed Amount])` | `is_current_version = TRUE` already applied upstream |
| `Expected Allowed` | `Sum([Expected Allowed])` | Benchmark × member risk / LOB mean risk |
| `Allowed PMPM` | `[Actual Allowed] / NullIf([Attributed Member Months], 0)` | |
| `Cost A/E` | `[Actual Allowed] / NullIf([Expected Allowed], 0)` | The scored cost measure |
| `Peer Mean A/E` | `Sum([Actual Allowed]) / Sum([Expected Allowed])` over all groups | The target |

### Utilization

| Field | Formula |
|---|---|
| `ED Visits` | `Sum([Ed Encounter Count])` |
| `ED per 1000` | `1000 * [ED Visits] / NullIf([Attributed Member Years], 0)` |
| `Admits per 1000` | `1000 * Sum([Ip Encounter Count]) / NullIf([Attributed Member Years], 0)` |

### Quality — and the union rule, written down

The two sources disagree and neither is a superset. PY2025 HbA1c, attributed members:

```
EHR lab result only    1,662
Claim line only        2,626
Both                   1,230
union                  5,518
```

1,178 external-lab results carry `result_status = 'NO_STRUCTURED_RESULT'` — the test happened,
there is no value. So *tested* and *controlled* have **different denominators** and the second
cannot be computed from the first.

| Field | Formula | Notes |
|---|---|---|
| `Diabetic Denominator` | `CountDistinct(If([Is Diabetic Dx], [Member Id]))` | Union of claim-side and encounter-side DM2 |
| `A1c Tested` | `CountDistinct(If([Has A1c Event], [Member Id]))` | Union of lab result and claim CPT 83036 |
| `A1c Testing Rate` | `[A1c Tested] / NullIf([Diabetic Denominator], 0)` | **The scored quality measure** |
| `A1c Result Available` | `CountDistinct(If([Has A1c Value], [Member Id]))` | Excludes `NO_STRUCTURED_RESULT` |
| `A1c Controlled Rate` | `CountDistinct(If([A1c Value] < 8, [Member Id])) / NullIf([A1c Result Available], 0)` | **Reported, never scored** — different denominator |

`A1c Controlled Rate` stays on the page as context and stays out of the payout. Paying on a
measure whose denominator is "patients whose lab happened to route to the in-house lab" pays
groups for their lab contract, not their diabetes care.

### Network integrity — the as-of join

| Field | Formula | Notes |
|---|---|---|
| `Referrals Placed` | `Count([Referral Id])` | |
| `EHR OON Rate` | `CountIf([Destination Status Per Ehr Directory] = "NONPAR") / NullIf([Referrals Placed], 0)` | **The wrong answer.** Shown deliberately, side by side. |
| `True OON Rate` | `CountIf([Destination Network Status Asof] = "NONPAR") / NullIf([Referrals Placed], 0)` | **The scored measure** |
| `Directory Gap` | `[True OON Rate] - [EHR OON Rate]` | Governance exposure, in points |
| `Confirmed Rate` | `CountIf([Is Confirmed]) / NullIf([Referrals Placed], 0)` | Appointment or claim confirms the referral landed |
| `System Closed Rate` | `CountIf([Closure Actor Type] = "SYSTEM") / NullIf(CountIf([Referral Status] = "CLOSED_COMPLETE"), 0)` | The auto-close tell |
| `OON Allowed` | `Sum(If([Is Out Of Network], [Allowed Amount], 0))` | The recapture number |
| `Null Referrer Rate` | `CountIf(IsNull([Referring Provider Master Id])) / NullIf([Referrals Placed], 0)` | 3.8–5.8% by group. Reported as a bucket, never dropped. |

### Access

| Field | Formula |
|---|---|
| `No Show Rate` | `CountIf([Appointment Status] = "NO_SHOW") / NullIf(CountIf([Appointment Status] <> "SCHEDULED"), 0)` |
| `Panel Touch Rate` | `CountDistinct(If([Has Group Encounter], [Member Id])) / NullIf([Attributed Members], 0)` |

`Panel Touch Rate` is Priya's measure — the share of an attributed panel that has actually been
seen at the attributing group. Measured at **96.9% system-wide**, and 93.9% at ORTHO-NR against
97.0–97.6% everywhere else. Reported, not scored, in v1: it is a roster-quality measure more
than a performance measure, and it would punish groups for Meridian's attribution logic.

### Scoring

| Field | Formula | Notes |
|---|---|---|
| `Domain Points` | 3-tier gate — see below | Per measure |
| `Composite Score` | `Sum([Domain Points])` across the five measures | 0–100 |
| `Weighted Share` | `[Composite Score] * [Attributed Member Months]` | Size-fair |
| `Modelled Payout` | `[Pool] * [Weighted Share] / Sum([Weighted Share])` | |
| `Payout per Member` | `[Modelled Payout] / NullIf([Attributed Members], 0)` | The fairness check |

Gate structure, lower-is-better measures (invert for higher-is-better):

```
v >= p75(worst)  ->  0
v <= p25(best)   ->  max points
v <= mean        ->  max * (0.60 + 0.40 * (mean - v) / (mean - p25))
otherwise        ->  max * 0.60 * (p75 - v) / (p75 - mean)
```

---

## 11. Workbook pages

Five pages. Page 2 is the product.

**1 · Pool & Contract Position.** The contract-level question. Pool size, total attributed
member-months, actual vs benchmark PMPM by month against `vbc_benchmark`, split commercial and
MA. Carries the trust header described below. This is the only page where the external
benchmark appears, and it is visibly separated from the scorecard.

**2 · Scorecard & Payout.** Twelve groups, five domain scores, composite, rank, modelled
payout, payout per member. A **Definition toggle — `EHR directory` / `As-of contract`** drives
the network measure and recomputes the whole page. Flipping it moves ORTHO-NR from rank 3 to
rank 12 and $259,141 off their payout, in front of the audience, in one click. A second panel
shows the payout delta as a diverging bar so the redistribution is legible in one read.

**3 · Group Detail.** Single group: the five domains against the peer distribution as dot
plots, twelve-month trend of each measure, cost decomposition by `service_category`, and the
referral destination table with `EHR status` and `True status as of placed date` as adjacent
columns. For ORTHO-NR that table is the finding.

**4 · Referral Stewardship.** Clinician level, referring providers with `n ≥ 30`, ranked by
true OON rate. Carries the days-to-closure histogram — the 25–31 day spike — and the
`System Closed Rate` column. Labelled a coaching view. Suppressed rows are counted, not hidden:
"140 of 170 providers below the n ≥ 30 reporting threshold."

**5 · Payout Ledger.** The input table and its audit trail. What was modelled, what was
approved, what was adjusted and by whom, with a reason required on every override.

### The trust header

A persistent strip, visible on every page, carrying the four facts that decide whether a number
is payable:

```
Roster version 2 · as of 2025-12-15     Paid through 2026-02-28
Scored window 2025-01 → 2025-09 (9 of 9 months complete)
Excluded from scoring: 2025-10 (0.78) · 2025-11 (0.54) · 2025-12 (0.31)
```

This is the thing Ken buys. A payout figure with no as-of date and no completeness statement is
not a number, it is an opinion, and it is the reason three decks quote three leakage rates.

---

## 12. Input tables

**`INPUT_PAYOUT_DECISION`** — one row per group × performance year. The approval loop.

| Column | Type | Notes |
|---|---|---|
| `Decision Id` | UUID | PK |
| `Attributed Site Code` | Text | Pre-filled from page context |
| `Performance Year` | Text | Pre-filled from the control |
| `Modelled Payout` | Number | Written from the scorecard at submit time — frozen, not live |
| `Approved Payout` | Number (editable) | Defaults to modelled |
| `Adjustment Reason` | Text | **Required when approved ≠ modelled** |
| `Roster Version` / `Paid Through` | Text / Date | Stamped at submit. Makes the decision reproducible. |
| `Network Definition Used` | Text | `EHR directory` or `As-of contract`. The field that makes the difference auditable. |
| `Status` | Open / In Review / Approved / Paid | |
| `Approved By` / `Approved Date` | Text / Date | |

**`INPUT_MEASURE_EXCLUSION`** — the appeals mechanism, and the thing that keeps Priya at the
table. One row per group × measure × year with a documented reason, e.g. Sunberry Pediatrics
excluded from the adult HbA1c measure. Columns: `Attributed Site Code`, `Performance Year`,
`Measure`, `Exclusion Reason`, `Requested By`, `Approved By`, `Status`.

Both live in Sigma. No changes to the mart CSVs.

---

## 13. Actions

1. **Toggle network definition** — control action on page 2, switches the network measure
   between the EHR pick-list and the as-of contract join and recomputes every dependent
   element. The demo beat.
2. **Drill to group** — row click on the scorecard sets the Group control and navigates to
   page 3.
3. **Drill to stewardship** — from the group's network domain tile to page 4, pre-filtered.
4. **Submit for approval** — writes a row to `INPUT_PAYOUT_DECISION` with the modelled payout,
   roster version, paid-through date and active network definition frozen in.
5. **Request measure exclusion** — from any domain tile, opens a pre-filled
   `INPUT_MEASURE_EXCLUSION` row.
6. **Hold cohort** — toggles the denominator between the current roster and
   `src_roster_original`, so the restatement effect is visible rather than argued about.

---

## 14. AI layer

**Ask a Question** works only if every published metric carries a description naming its
denominator, which is why [§9](#9-data-model-northlake-vbc) insists on it. The questions that
must answer correctly:

- "Which group has the highest out-of-network referral rate?" — must return ORTHO-NR from the
  as-of measure, not the pick-list measure. If both fields are exposed with equally plausible
  names, this answers wrong. **Name them `True OON Rate` and `EHR Directory OON Rate (do not
  score)`** and hide the latter from the AI index.
- "How much would North Ridge earn?" — must state the network definition and the scored window.
- "Why did North Ridge's score drop?" — the decomposition answer.

**A custom agent** for payout defence: given a group and a domain, it returns the measure
value, the peer distribution, the points earned, the gate thresholds, and the lineage back to
source column and load batch. Marcus asks it "why is this number what it is"; Priya asks it
"what would my group need to do to earn the next tier". That second question is the one that
changes behaviour, and it is a different product from a dashboard.

---

## 15. Reference figures

PY2025 YTD (2025-01 → 2025-09), governed definitions, $4.2M pool.

| Group | MM | A/E | ED/1000 | A1c rate | True OON | No-show | Score | Rank | Payout |
|---|---|---|---|---|---|---|---|---|---|
| Northlake Cancer Center | 9,598 | 1.250 | 217.5 | 50.2% | 22.9% | 5.8% | 86.4 | 1 | $274,944 |
| Centerline Primary Care | 28,460 | 1.275 | 232.7 | 49.5% | 20.9% | 5.2% | 84.9 | 2 | $801,282 |
| Meridian Spine and Pain | 10,336 | 1.792 | 189.2 | 50.5% | 21.8% | 5.0% | 75.0 | 3 | $257,112 |
| Eastgate Family Health | 22,395 | 1.311 | 249.7 | 47.5% | 21.9% | 5.4% | 70.2 | 4 | $521,383 |
| Sunberry Women's Health | 20,339 | 1.272 | 210.6 | 43.7% | 22.8% | 5.2% | 60.5 | 5 | $407,926 |
| Westport Multispecialty | 17,114 | 1.221 | 171.8 | 44.5% | 21.8% | 6.2% | 60.2 | 6 | $341,528 |
| Sunberry Pediatrics | 6,000 | 1.230 | 132.0 | 32.8% | 20.1% | 6.3% | 60.0 | 7 | $119,390 |
| Riverbend Cardiology | 14,009 | 1.140 | 203.0 | 44.7% | 21.9% | 6.3% | 58.9 | 8 | $273,470 |
| Northlake Family Medicine | 25,198 | 1.413 | 280.5 | 48.2% | 21.8% | 5.7% | 53.4 | 9 | $445,942 |
| Westport Internal Medicine | 20,674 | 1.350 | 217.1 | 49.4% | 23.1% | 5.5% | 46.9 | 10 | $321,831 |
| Eastgate Digestive Health | 10,555 | 1.347 | 222.8 | 52.3% | 23.0% | 7.1% | 41.9 | 11 | $146,726 |
| **North Ridge Orthopedics** | 21,888 | 1.400 | 256.0 | 53.0% | **52.8%** | 5.3% | **39.7** | **12** | **$288,466** |

Leakage, PY2025 YTD: **$12,996,664** out-of-network allowed on $181,378,478 total (7.2%).
Top destinations: ASC-SUMMIT $4,695,077 · IMG-OPEN $2,469,487 · ASC-LKSD $1,962,362 ·
ASC-CRST $1,943,702 · ASC-PINE $1,926,037.

---

## 16. Open items to verify before any build

1. **Get the data into Sigma.** Nothing exists there. CSV upload or the unexecuted Snowflake
   lift in [SQL/](SQL/). Decide first — it changes whether `network_status_asof` is a Sigma join
   or the `f_network_status_asof` UDF the handoff flags as untested.
2. **Two float key columns.** `dim_provider.facility_id` and `fct_claim_header.drg_code` read
   back as floats because they contain nulls, and a string comparison against an integer parent
   key reports 100% orphans on a sound relationship. Type them explicitly on load.
3. **Deduplicate on the business key.** A9a planted 2,840 duplicate claim lines in 2024-07 under
   `BATCH-REDRIVE-20240714`. `claim_line_key` is unique across all of them, so a PK test passes.
   De-duplicate on `(claim_number, claim_line_number, adjudication_seq)`, earliest batch wins —
   and do **not** additionally dedupe on "the obvious business columns", because A9b planted
   legitimate bilateral and same-day-repeat lines that differ only by modifier. The naive fix
   for one creates the other. **$1,998,144 of overstatement rides on getting this right.**
4. **Resolve orphan providers to −1, never inner join.** A12 planted 1,312 claim lines with no
   provider row, 68% at UC-NORTHGATE. An inner join to the provider dimension silently drops
   $394,978.
5. **Confirm the cost gate.** As specified, SPIN-MRD finishes 3rd with the worst A/E of twelve
   (1.792) because it maxes quality, network and access. That is defensible on the merits and
   Finance will still challenge it. Recommend a gate: no group ranks above median with
   `Cost A/E` above the peer 75th percentile. Needs Marcus's sign-off, not mine.
6. **Confirm measure applicability.** Sunberry Pediatrics scores 0 of 30 on adult HbA1c with a
   denominator of 125. Either exclude via `INPUT_MEASURE_EXCLUSION` or substitute a paediatric
   measure. Scoring it as-is is indefensible.
7. **Pool size and weights** are modelling assumptions ($4.2M; 25/10/30/25/10). Both need a
   real owner before anything is presented as a payout.

---

## 17. Explicit non-goals

- **Clinician-level payment.** [§4](#4-why-the-payee-is-a-clinic-group-and-not-a-clinician).
  Panels of ten cannot carry a rate.
- **HEDIS-certified measure logic.** The HbA1c measure is HEDIS-*shaped*, not HEDIS-compliant.
  Say so out loud; a healthcare audience will ask.
- **Medication adherence.** No NDC-level pharmacy in the dataset, by design.
- **Readmissions.** Computable but not at a rigour worth paying on here.
- **Behavioural health.** Deliberately absent from the dataset. 42 CFR Part 2 handling is a
  distraction and a risk in a demo asset.
- **Attribution logic.** The app consumes Meridian's roster. It does not re-derive who should
  be attributed to whom.
- **Row-level security.** v1 shows all twelve groups to all viewers. Real RLS on
  `attributed_site_code` is a fast follow, not a v1 feature.

---

## 18. Verification

Every figure above was measured on the shipping `demo` build. To reproduce:

```sh
python Generators/build.py --scale demo --verify   # confirm the data is byte-identical
python Build/build_mart.py
python Validation/validate.py                      # 25 hard assertions
python Build/verify_keys.py                        # every PK, BK and FK
```

The scorecard, payout and rank-inversion figures come from two analysis scripts written for
this plan. Before the build, these should move into `Validation/` as assertions so that a
change in the data that would move a payout shows up as a test failure rather than a surprise
in a meeting.

The single most useful check available: run the whole scorecard against the clean twin.

```sh
python Generators/build.py --scale demo --no-anomalies
```

ORTHO-NR's rank inversion should vanish entirely. **The delta is the lesson**, and it is also
the regression test — if the governed scorecard still shows a nine-place inversion against
clean data, the measure is wrong, not the data.
