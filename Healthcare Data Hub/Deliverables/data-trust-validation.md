# Data trust validation

**Dataset:** Healthcare Data Hub (synthetic)  
**Scale:** demo - 48,000 members  
**Seed:** 20260911  
**Generated:** 2026-09-16 15:16  
**Classification:** SYNTHETIC. Wholly fabricated. Not derived from real patient records.

## Verdict

| | Count |
|---|---|
| Hard assertions passed | 54 of 54 |
| Planted defects confirmed present and controlled | 29 of 29 |
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
| Claim lines with a servicing provider absent from credentialing | CONTROLLED | 1188 | > 0 | $467,289.02 |
| Claim lines resolving to the -1 Unknown member | CONTROLLED | 0 | counted, not zero | $0.00 |
| Claims with no Northlake encounter (care delivered elsewhere) | CONTROLLED | 0.2967 | 0.15 to 0.32 |  |
| EHR encounters whose patient never resolved to a member | CONTROLLED | 17058 | > 0 |  |

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
| Both sanctioned nettings agree: all rows vs is_current_version | PASS | 611216073.24 | 611216073.24 |  |
| Naive span-sum overstates member-months versus the de-duplicated union | CONTROLLED | 0.69% over | > 0% |  |

- **RECON-001** - Holds to the penny on 100% of lines, every adjudication version.
- **RECON-003** - 388,406 claim-versions compared.
- **RECON-004** - Note there is NO reversal exclusion in the second formula. Orphan reversals are current and negative on purpose, so excluding them breaks the tie.
- **RECON-005** - Summing span lengths double counts every overlap. The correct denominator is the gaps-and-islands union.

## Distribution control

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| Allowed PMPM, COMMERCIAL | PASS | 555.61 | 480.0 to 620.0 |  |
| Admissions per 1000, COMMERCIAL | PASS | 59.4 | 55.0 to 70.0 |  |
| ED visits per 1000, COMMERCIAL | PASS | 178.6 | 150.0 to 190.0 |  |
| Allowed PMPM, MEDICARE_ADVANTAGE | PASS | 1004.6 | 900.0 to 1150.0 |  |
| Admissions per 1000, MEDICARE_ADVANTAGE | PASS | 240.8 | 200.0 to 260.0 |  |
| ED visits per 1000, MEDICARE_ADVANTAGE | PASS | 496.1 | 400.0 to 520.0 |  |
| Top 1% of members share of allowed | PASS | 0.2494 | 0.22 to 0.3 |  |
| Top 5% of members share of allowed | PASS | 0.5677 | 0.5 to 0.62 |  |
| Average length of stay, days | PASS | 4.28 | 3.9 to 4.6 |  |
| Median paid lag, days | PASS | 23.0 | 20 to 26 |  |
| Every chronic condition prevalence within tolerance of its benchmark | PASS | 0.14pp | <= 0.5pp |  |
| P(diabetes \| hypertension), emergent from the shared risk term | PASS | 0.2327 | 0.18 to 0.26 |  |

- **DIST-TOP1** - The single most recognizable realism check a payer audience applies.
- **DIST-PREV** - Worst deviation: HYPO off by 0.14pp.

## Clinical plausibility

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| Sex-inappropriate diagnoses at MEMBER grain | PASS | 0 | 0 |  |
| Master persons resolving to more than one distinct person | CONTROLLED | 33 | >= 10 |  |
| Of those, how many the one-line sex-mismatch query alone would find | CONTROLLED | 18 of 33 | reported for context |  |
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
| Share of ambulatory volume landing as UNKNOWN | CONTROLLED | 0.0347 | 0.02 to 0.05 |  |
| One physical hospital carries two EHR department identifiers | CONTROLLED | 2 | 2 |  |

- **CONF-001** - One clinic emits a value nobody mapped. It lands as UNKNOWN and gets filtered out as junk unless someone profiles distinct values BY SOURCE.
- **CONF-003** - An EMR upgrade renumbered the site mid-2024. Without the crosswalk, volume by facility splits one hospital into two as a step change in the middle of the year.

## Question ladder

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| Share of ORTHO-NR closures landing at day 30 after the rule | CONTROLLED | 0.632 | 0.55 to 0.72 |  |
| Same measure at every other site | CONTROLLED | 0.0329 | 0.0 to 0.08 |  |
| Referral confirmation rate is materially worse at ORTHO-NR | CONTROLLED | 0.656 vs 0.762 elsewhere | site materially lower |  |
| ORTHO-NR ranks best of 12 on EHR-apparent out-of-network rate | CONTROLLED | rank 1 of 12 | rank 1 |  |
| Excess cost of ORTHO-NR leaked episodes over the in-network equivalent | CONTROLLED | 871576.34 | >= 400,000 | $871,576.34 |
| ORTHO-NR share of system-wide referral leakage excess | CONTROLLED | 26.8% | reported for context |  |
| Excess cost routed to Summit Point after its contract terminated | CONTROLLED | 1284775.84 | >= 400,000 | $1,284,775.84 |
| Share of leaked spend that is plausibly recapturable | CONTROLLED | 1.0 | 0.25 to 1.0 |  |
| Why the remainder is not recapturable | CONTROLLED | geography 0.0%, capacity 0.0%; 711 leaked episodes vs 2,323 in-network case headroom | reported for context |  |

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
| Service month 2025-10 is incomplete, as designed | CONTROLLED | 93.6% of the de-trended prior-year month | 94% +/- 10% |  |
| Service month 2025-11 is incomplete, as designed | CONTROLLED | 76.9% of the de-trended prior-year month | 81% +/- 10% |  |
| Service month 2025-12 is incomplete, as designed | CONTROLLED | 33.4% of the de-trended prior-year month | 27% +/- 10% |  |
| Completeness declines monotonically toward the edge of the window | CONTROLLED | 94% > 77% > 33% | monotonically decreasing |  |
| dim_date flags exactly the incomplete months | PASS | ['2025-10', '2025-11', '2025-12'] | ['2025-10', '2025-11', '2025-12'] |  |

- **RUNOUT-2025-10** - Claims absent from this extract are exactly the ones that had not adjudicated by the paid-through date of 2026-01-02 - the slowest-paying, not a random sample. The observed ratio is asserted against the designed completeness rather than a flat threshold, which the designed curve contradicts for October.
- **RUNOUT-2025-11** - Claims absent from this extract are exactly the ones that had not adjudicated by the paid-through date of 2026-01-02 - the slowest-paying, not a random sample. The observed ratio is asserted against the designed completeness rather than a flat threshold, which the designed curve contradicts for October.
- **RUNOUT-2025-12** - Claims absent from this extract are exactly the ones that had not adjudicated by the paid-through date of 2026-01-02 - the slowest-paying, not a random sample. The observed ratio is asserted against the designed completeness rather than a flat threshold, which the designed curve contradicts for October.
- **RUNOUT-TREND** - The signature of runout. A real utilization drop would not get progressively steeper the closer you get to the extract date.
- **RUNOUT-FLAG** - claims_runout_complete_flag is the guardrail: any service-date trend should filter on it rather than relying on the analyst remembering where the data stops.

## Settlement

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| risk score book mean = 1.0 (COMMERCIAL) | PASS | 0.9991 | 1.0 +/- 0.02 |  |
| risk score book mean = 1.0 (MEDICARE_ADVANTAGE) | PASS | 1.0013 | 1.0 +/- 0.02 |  |
| attributed cohort mean risk > book | PASS | 1.1763 | 1.05 to 1.35 |  |
| restatement includes retro-ADDITIONS | PASS | 190 | >= 150 |  |
| restatement includes retro-terminations | PASS | 614 | >= 400 |  |
| every roster version ships | PASS | 6 | 6 |  |
| roster restatement moves PY2025 PMPM | PASS | 5.77 | 2.0 to 9.0 |  |
| line truncation ties to member-year | PASS | 786513287.0 | 786513286.57 | $0.43 |
| truncation removes a 99th-percentile tail | PASS | 9.3 | 4.0 to 12.0 | $80,675,444.68 |
| benchmark is beatable but not free (COMMERCIAL) | PASS | 3.27 | 1.0 to 7.0 |  |
| benchmark is beatable but not free (MEDICARE_ADVANTAGE) | PASS | 2.03 | 1.0 to 7.0 |  |
| over-match contaminates the cost tail | CONTROLLED | 8 | >= 1 | $2,036,225.53 |
| lag triangle ties to fct_claim_line | PASS | 867188731.25 | 867188731.25 | $0.00 |
| chain ladder recovers completeness (2025-07) | PASS | 0.9946 | 0.99 +/- 0.06 |  |
| chain ladder recovers completeness (2025-08) | PASS | 0.9888 | 0.99 +/- 0.06 |  |
| chain ladder recovers completeness (2025-09) | PASS | 0.9748 | 0.97 +/- 0.06 |  |
| chain ladder recovers completeness (2025-10) | PASS | 0.9353 | 0.94 +/- 0.06 |  |
| chain ladder recovers completeness (2025-11) | PASS | 0.795 | 0.81 +/- 0.06 |  |
| chain ladder recovers completeness (2025-12) | PASS | 0.2949 | 0.27 +/- 0.06 |  |
| asserted and derived completeness agree, every month | PASS | 0.0249 | <= 0.06 |  |

- **SET-01** - A risk score is only meaningful against a normalized book. Multiplying a benchmark PMPM by a raw morbidity weight produces a number with no contractual meaning.
- **SET-01** - A risk score is only meaningful against a normalized book. Multiplying a benchmark PMPM by a raw morbidity weight produces a number with no contractual meaning.
- **SET-02** - Attribution selects for care-seekers, so the attributed sub-population must run richer than the book it is drawn from. At 1.0 the attribution rule has stopped selecting.
- **SET-03** - A restatement history that only ever removes members models the convenient direction and nothing else.
- **SET-05** - The baseline roster used to be computed and discarded, leaving the as-of control with one position.
- **SET-06** - Reconstructing the baseline roster from the delta. This is the headline: an improvement that is bookkeeping, not care.
- **SET-07** - The pro-rata allocation back down to the line must sum exactly to the member-year cap, or the two grains disagree about the same contract term.
- **SET-08** - At a threshold too low for the cost curve this removes a quarter of all spend and stops being a tail treatment.
- **SET-09** - Risk-adjusted benchmark $860 against truncated attributed actual $832, PY2024.
- **SET-09** - Risk-adjusted benchmark $1,352 against truncated attributed actual $1,325, PY2024.
- **SET-10** - Two people wearing one identity surface as an artificial super-utilizer. Collapsing only the EHR key space left the payer spine intact, so claims never aggregated onto one person and the defect the answer key promises did not exist in the mart.
- **SET-12** - The completion factor is DERIVED from the paid dates present, not read off a constant. When these diverge, the extract is claiming a paid-through date its own data cannot support.
- **SET-12** - The completion factor is DERIVED from the paid dates present, not read off a constant. When these diverge, the extract is claiming a paid-through date its own data cannot support.
- **SET-12** - The completion factor is DERIVED from the paid dates present, not read off a constant. When these diverge, the extract is claiming a paid-through date its own data cannot support.
- **SET-12** - The completion factor is DERIVED from the paid dates present, not read off a constant. When these diverge, the extract is claiming a paid-through date its own data cannot support.
- **SET-12** - The completion factor is DERIVED from the paid dates present, not read off a constant. When these diverge, the extract is claiming a paid-through date its own data cannot support.
- **SET-12** - The completion factor is DERIVED from the paid dates present, not read off a constant. When these diverge, the extract is claiming a paid-through date its own data cannot support.
- **SET-13** - Checked across all 36 service months carrying claims.

## ASO book

| Check | Verdict | Actual | Expected | Dollar impact |
|---|---|---|---|---|
| the self-funded book is a set of CLIENTS | PASS | 9 | 9 |  |
| no member-month crosses the funding boundary | PASS | 0 in, 0 out | 0, 0 |  |
| no household spans two employers' plans | PASS | 0 | <= 0 |  |
| contract-months never exceed member-months | PASS | 0 client-months | 0 |  |
| admin fee on member-months overstates by the family factor | CONTROLLED | 2.224 | 1.9 to 2.4 | $20,720,874.46 |
| fee components tie to the fee total | PASS | 0.0 | <= 50.0 | $0.00 |
| net plan cost = paid - recovered + fees | PASS | 0.0 | <= 5.0 |  |
| monthly ISL allocation ties to the filings | PASS | 16592372.76 | 16592372.65 | $0.11 |
| CL-KELL 2025 rate set below truth | CONTROLLED | 11.62 | 8.0 to 18.0 |  |
| every other client's rate is clean | PASS | 0.05 | <= 0.5 |  |
| the stop-loss layer has claimants in it | PASS | 267 | >= 120 |  |
| late filings are declined and cost the client | CONTROLLED | 19 | >= 5 | $1,481,247.51 |
| some filings are claimed across two people | CONTROLLED | 4 | >= 1 | $116,468.37 |
| every over-claimed filing rolled up more than one member id | PASS | 4 | all > 1 |  |
| entangled durable keys are reported separately, not as over-claims | CONTROLLED | 8 filings | None | $1,219,752.95 |
| the re-driven extract over-funded a client | CONTROLLED | 163 weeks | >= 1 | $1,142,263.58 |
| the over-funding is material | CONTROLLED | 1142263.58 | >= 250,000 |  |

- **ASO-01** - Before this layer, 17 of 18 groups carried members on the fully-insured AND the self-funded plan at the same time, so 'show me my self-funded book' returned a slice of every client instead of a set of clients.
- **ASO-02** - A member cannot elect a self-funded plan from a fully-insured sponsor: the plan belongs to the sponsor, not the member.
- **ASO-03** - The employer enrolls the EMPLOYEE and the family comes with the contract. Drawing the group per member put a subscriber in one employer's plan and their child in another's, which made a contract-month - the PEPM denominator - uncountable. Of the 33 over-matched identity pairs, all 33 shared a subscriber and only 2 shared a group.
- **ASO-04** - A contract-month is credited only where the SUBSCRIBER was covered. Counting a dependent enrolled in a month the subscriber was not inflates every per-employee fee in the book.
- **ASO-05** - The administration fee is PER EMPLOYEE per month. The average contract here covers about 2.1 lives, so the same fee billed against member-months reads roughly twice its true size. Both columns ship so the error is a subtraction rather than an argument.
- **ASO-06** - Six fee components on three different denominators. If they do not sum to the total the app quotes, the app is quoting a number no schedule supports.
- **ASO-07** - Recovery RECEIVED rather than entitled, on purpose: a filing declined for late submission is money the client did not get, and a settlement built on entitlement quietly hands it back.
- **ASO-08** - The recovery is a policy-year event spread evenly across the policy year's months. Even spreading is a modeling choice and is named as one; summing to the filing exactly is not optional.
- **ASO-09** - The client was loaded under two group ids through an acquisition, so its spans overlap and the enrollment extract yields a denominator materially too large. The renewal was priced over that denominator. The deficit that follows looks like claims experience and is arithmetic.
- **ASO-10** - Isolation matters as much as size. A denominator error spread evenly across the book is a scaling factor nobody has to find; one that lands on a single client is the kind that survives review and decides a renewal.
- **ASO-12** - A filing past the deadline is declined and the CLIENT, not the carrier, absorbs the claim. No report of recoveries a plan was entitled to will ever show it.
- **ASO-13** - Filings assembled from the resolved-identity large claimant report sum every member id behind one master person. Where the MDM run OVER-matched - twins, a Jr/Sr pair - that is two different people on one stop-loss claim, and it ties to the resolved identity perfectly, which is why nothing else catches it.
- **ASO-13b** - A MASTER_PERSON_ID filing that rolled up exactly one member id would be a mislabel rather than an over-claim.
- **ASO-13c** - These filings are correctly scoped to one member whose durable key happens to carry two member ids. Worth routing to review; folding them into the over-claim figure overstates it roughly tenfold.
- **ASO-14** - The funding system draws against the adjudication extract as it arrived. A duplicate-row count in a data quality report does not make anyone act. A wire does.

## Claims runout triangle

The last three service months are structurally incomplete because claims adjudicate on a lag and the paid-through date is 2026-01-02. A monthly trend on service date run to the right edge shows a cliff that is not a utilization drop.

Measured against the SAME calendar month in prior years, de-trended. Comparing an incomplete month against an annual average measures seasonality and calls it completeness - December alone carries a 1.45x elective-surgery factor.

| Service month | Observed completeness | Designed | De-trended baseline |
|---|---|---|---|
| 2025-10 | 93.6% | 94% | $19,872,046 |
| 2025-11 | 76.9% | 81% | $19,701,012 |
| 2025-12 | 33.4% | 27% | $22,874,975 |

Control: restrict service-date trends to complete months, or trend on paid date, which IS complete. Mixing the two is the error.

---

Regenerate with `python Generators/build.py --scale demo` then `python Build/build_mart.py` then `python Validation/validate.py`.
