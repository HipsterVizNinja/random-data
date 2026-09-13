# Data trust validation

**Dataset:** Healthcare Data Hub (synthetic)  
**Scale:** demo - 48,000 members  
**Seed:** 20260911  
**Generated:** 2026-09-11 13:19  
**Classification:** SYNTHETIC. Wholly fabricated. Not derived from real patient records.

## Verdict

| | Count |
|---|---|
| Hard assertions passed | 25 of 25 |
| Planted defects confirmed present and controlled | 22 of 22 |
| Failures | **0** |

Every hard assertion passes, and every planted data-quality defect was found, measured, and controlled for. The figures below are generated from the shipped data, so this document cannot drift from the dataset it describes.

A note on how to read this. Checks marked EXPECTED are deliberate. This dataset carries planted data-quality problems because finding them and controlling for them is the exercise. An EXPECTED check that PASSES means the defect is present at the size it should be and the control for it works. A suite that goes red on purpose teaches nothing.

## Grain uniqueness

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| Raw claim lines violate the business key (planted duplicate extract) | CONTROLLED | 2840 | >= 2,000 |  |
| Surrogate key claim_line_key is unique even on the raw file | CONTROLLED | True | True |  |
| Mart claim lines are unique on the business key after de-duplication | PASS | 0 | 0 |  |
| Member-month is unique on (member_id, year_month) | PASS | 0 | 0 |  |
| Type-2 provider dimension has exactly one current row per provider | PASS | 0 | 0 |  |
| Type-2 provider spans do not overlap | PASS | 0 | 0 |  |

- **GRAIN-001** - A re-driven extract loaded one day of claim lines twice. These rows carry DISTINCT surrogate keys.
- **GRAIN-002** - Proof that a primary-key uniqueness test would have PASSED while the business key was violated. Test business keys.
- **GRAIN-004** - The only sanctioned PMPM denominator. One row per member-month.

## Referential integrity

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| Claim lines with a servicing provider absent from credentialing | CONTROLLED | 1176 | > 0 | $394,977.60 |
| Claim lines resolving to the -1 Unknown member | CONTROLLED | 0 | counted, not zero | $0.00 |
| Claims with no Northlake encounter (care delivered elsewhere) | CONTROLLED | 0.3048 | 0.15 to 0.32 |  |
| EHR encounters whose patient never resolved to a member | CONTROLLED | 17421 | > 0 |  |

- **REF-001** - An inner join to the provider dimension would silently delete these lines and the dollars on them.
- **REF-002** - Unmatched keys resolve to -1 so the mart stays joinable.
- **REF-003** - By design. Northlake cannot see care it did not deliver, which is precisely why the hub is necessary.
- **REF-004** - The EHR-to-claims join is a three-hop through the crosswalk and it loses this share. The loss is NOT random.

## Reconciliation

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| allowed = paid + deductible + copay + coinsurance + cob on every line | PASS | 0 | 0 |  |
| billed >= allowed on every line | PASS | 0 | 0 |  |
| Header total paid = SUM(line paid) per (claim, adjudication version) | PASS | 0 | 0 |  |
| Both sanctioned nettings agree: all rows vs is_current_version | PASS | 602924473.47 | 602924473.47 |  |
| Naive span-sum overstates member-months versus the de-duplicated union | CONTROLLED | 0.70% over | > 0% |  |

- **RECON-001** - Holds to the penny on 100% of lines, every adjudication version.
- **RECON-003** - 388,869 claim-versions compared.
- **RECON-004** - Note there is NO reversal exclusion in the second formula. Orphan reversals are current and negative on purpose, so excluding them breaks the tie.
- **RECON-005** - Summing span lengths double counts every overlap. The correct denominator is the gaps-and-islands union.

## Distribution control

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| Allowed PMPM, COMMERCIAL | PASS | 544.66 | 480.0 to 620.0 |  |
| Admissions per 1000, COMMERCIAL | PASS | 57.5 | 55.0 to 70.0 |  |
| ED visits per 1000, COMMERCIAL | PASS | 174.2 | 150.0 to 190.0 |  |
| Allowed PMPM, MEDICARE_ADVANTAGE | PASS | 1030.98 | 900.0 to 1150.0 |  |
| Admissions per 1000, MEDICARE_ADVANTAGE | PASS | 257.6 | 200.0 to 260.0 |  |
| ED visits per 1000, MEDICARE_ADVANTAGE | PASS | 463.9 | 400.0 to 520.0 |  |
| Top 1% of members share of allowed | PASS | 0.2515 | 0.22 to 0.3 |  |
| Top 5% of members share of allowed | PASS | 0.5694 | 0.5 to 0.62 |  |
| Average length of stay, days | PASS | 4.25 | 3.9 to 4.6 |  |
| Median paid lag, days | PASS | 22.0 | 20 to 26 |  |
| Every chronic condition prevalence within tolerance of its benchmark | PASS | 0.14pp | <= 0.5pp |  |
| P(diabetes \| hypertension), emergent from the shared risk term | PASS | 0.2327 | 0.18 to 0.26 |  |

- **DIST-TOP1** - The single most recognizable realism check a payer audience applies.
- **DIST-PREV** - Worst deviation: HYPO off by 0.14pp.

## Clinical plausibility

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| Sex-inappropriate diagnoses at MEMBER grain | PASS | 0 | 0 |  |
| Master persons resolving to more than one distinct person | CONTROLLED | 38 | >= 10 |  |
| Of those, how many the one-line sex-mismatch query alone would find | CONTROLLED | 22 of 38 | reported for context |  |
| length_of_stay_days equals discharge minus admit exactly | PASS | 0 | 0 |  |
| No encounters after the source window | PASS | 0 | 0 |  |
| No elective ambulatory encounters on weekends | PASS | 0 | 0 |  |
| Every NPI deliberately FAILS its check digit | CONTROLLED | 0 valid of 2,666 | 0 valid |  |

- **CLIN-001** - Enforced by the generator. Must be zero.
- **CLIN-002** - The over-match detector. Two distinct people share one master_person_id, so the identity carries two dates of birth and often two sexes. One query finds them, which is what makes this a satisfying teaching beat.
- **CLIN-002b** - Sex mismatch is the cheapest detector but it only catches the mixed-sex pairs. Same-sex twins need the date-of-birth check, which is why the audit view tests both.
- **CLIN-006** - A valid NPI resolves to a real clinician in the public NPPES registry, which synthetic data must never do. Validators will flag these, and that is intended.

## Conformance coverage

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| Encounter-type source values with no crosswalk entry | CONTROLLED | ['AMB'] | ['AMB'] |  |
| Share of ambulatory volume landing as UNKNOWN | CONTROLLED | 0.0337 | 0.02 to 0.05 |  |
| One physical hospital carries two EHR department identifiers | CONTROLLED | 2 | 2 |  |

- **CONF-001** - One clinic emits a value nobody mapped. It lands as UNKNOWN and gets filtered out as junk unless someone profiles distinct values BY SOURCE.
- **CONF-003** - An EMR upgrade renumbered the site mid-2024. Without the crosswalk, volume by facility splits one hospital into two as a step change in the middle of the year.

## Question ladder

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| Share of ORTHO-NR closures landing at day 30 after the rule | CONTROLLED | 0.6454 | 0.55 to 0.72 |  |
| Same measure at every other site | CONTROLLED | 0.0315 | 0.0 to 0.08 |  |
| Referral confirmation rate is materially worse at ORTHO-NR | CONTROLLED | 0.657 vs 0.768 elsewhere | site materially lower |  |
| ORTHO-NR ranks best of 12 on EHR-apparent out-of-network rate | CONTROLLED | rank 1 of 12 | rank 1 |  |
| Excess cost of ORTHO-NR leaked episodes over the in-network equivalent | CONTROLLED | 719190.07 | >= 400,000 | $719,190.07 |
| ORTHO-NR share of system-wide referral leakage excess | CONTROLLED | 22.6% | reported for context |  |
| Excess cost routed to Summit Point after its contract terminated | CONTROLLED | 1145647.67 | >= 400,000 | $1,145,647.67 |
| Share of leaked spend that is plausibly recapturable | CONTROLLED | 1.0 | 0.25 to 1.0 |  |
| Why the remainder is not recapturable | CONTROLLED | geography 0.0%, capacity 0.0%; 758 leaked episodes vs 2,283 in-network case headroom | reported for context |  |

- **LADDER-001** - A spike at a round number is a workflow rule, not clinical behavior.
- **LADDER-003** - Confirmation is measured against a real event - a claim or a completed appointment - not against the status field.
- **LADDER-004** - The naive single-source answer. This is the number that gets a clinic group held up as the model to copy.
- **LADDER-005** - The joined answer. Episodes that went out of network, priced against what the same care would have cost in network, attributed to the referring site. This is the figure the narrative quotes - NOT total out-of-network allowed, which sweeps in every outside claim in the book and answers nobody's question.
- **LADDER-006** - One clinic group of twelve, and it carries this share of the excess. That concentration is the argument.
- **LADDER-007** - Its contract ended 2024-10-01. The EHR referral directory still reads PAR, 14 months stale. A governance failure with a price tag, and nobody made a bad clinical decision.
- **LADDER-008** - Tested against real drive times and against in-network surgical capability and block time. At this panel size capacity does NOT bind, so nearly all leaked volume is recapturable. That is the opposite of what the design expected, and it is what the data says.
- **LADDER-009** - Named so the number can be defended rather than asserted.

## Completeness

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| Service month 2025-10 is materially incomplete | CONTROLLED | 74.1% of the de-trended prior-year month | < 90% |  |
| Service month 2025-11 is materially incomplete | CONTROLLED | 50.2% of the de-trended prior-year month | < 90% |  |
| Service month 2025-12 is materially incomplete | CONTROLLED | 37.5% of the de-trended prior-year month | < 90% |  |
| Completeness declines monotonically toward the edge of the window | CONTROLLED | 74% > 50% > 37% | monotonically decreasing |  |
| dim_date flags exactly the incomplete months | PASS | ['2025-10', '2025-11', '2025-12'] | ['2025-10', '2025-11', '2025-12'] |  |

- **RUNOUT-2025-10** - Claims absent from this extract are exactly the ones that had not adjudicated by the paid-through date of 2026-02-28 - the slowest-paying, not a random sample. Designed completeness 78%.
- **RUNOUT-2025-11** - Claims absent from this extract are exactly the ones that had not adjudicated by the paid-through date of 2026-02-28 - the slowest-paying, not a random sample. Designed completeness 54%.
- **RUNOUT-2025-12** - Claims absent from this extract are exactly the ones that had not adjudicated by the paid-through date of 2026-02-28 - the slowest-paying, not a random sample. Designed completeness 31%.
- **RUNOUT-TREND** - The signature of runout. A real utilization drop would not get progressively steeper the closer you get to the extract date.
- **RUNOUT-FLAG** - claims_runout_complete_flag is the guardrail: any service-date trend should filter on it rather than relying on the analyst remembering where the data stops.

## Claims runout triangle

The last three service months are structurally incomplete because claims adjudicate on a lag and the paid-through date is 2026-02-28. A monthly trend on service date run to the right edge shows a cliff that is not a utilization drop.

Measured against the SAME calendar month in prior years, de-trended. Comparing an incomplete month against an annual average measures seasonality and calls it completeness - December alone carries a 1.45x elective-surgery factor.

| Service month | Observed completeness | Designed | De-trended baseline |
|---|---|---|---|
| 2025-10 | 74.1% | 78% | $18,933,272 |
| 2025-11 | 50.2% | 54% | $20,954,476 |
| 2025-12 | 37.5% | 31% | $22,210,359 |

Control: restrict service-date trends to complete months, or trend on paid date, which IS complete. Mixing the two is the error.

---

Regenerate with `python Generators/build.py --scale demo` then `python Build/build_mart.py` then `python Validation/validate.py`.
