"""Declared primary, business, and foreign keys for every mart table.

Separated from the document generator so the declarations can be VERIFIED
against the shipped data rather than asserted. A manifest that claims a
primary key which is not actually unique is worse than no manifest.

  pk        the surrogate primary key, one column
  business  the natural/business key. For facts this is the grain statement,
            and it is the key that de-duplication must run on - a uniqueness
            test on a surrogate passes by construction
  fks       (column, referenced_table, referenced_column, note)
"""
from __future__ import annotations

# Tables grouped for the diagram and the document.
GROUPS = {
    "Conformed dimensions": [
        "dim_date", "dim_member", "dim_master_person", "dim_provider",
        "dim_provider_current", "dim_facility", "dim_coverage_plan",
        "dim_diagnosis", "dim_procedure", "dim_service_place", "dim_drg",
        "dim_claim_status", "dim_service_line",
    ],
    "Claims facts": [
        "fct_claim_header", "fct_claim_line", "br_claim_diagnosis",
    ],
    "Clinical facts": [
        "fct_encounter", "br_encounter_diagnosis", "fct_lab_result",
    ],
    "Referral facts": [
        "fct_referral", "fct_referral_outcome",
    ],
    "Membership and contract": [
        "fct_eligibility_span", "fct_member_month", "vbc_attribution_month",
        "vbc_attribution_restatement", "vbc_roster_version",
        "vbc_benchmark", "vbc_contract_terms",
    ],
    "Settlement and completeness": [
        "fct_member_year_cost", "fct_claims_lag_triangle",
    ],
    "Bridges and crosswalks": [
        "br_provider_affiliation", "xwalk_patient", "xwalk_provider",
    ],
    "Serving layer": ["vw_claim_line_enriched"],
}

KEYS: dict[str, dict] = {
    # ----------------------------------------------------------- dimensions
    "dim_date": {
        "grain": "one calendar day",
        "pk": "date_key",
        "business": ["full_date"],
        "fks": [],
        "note": "Role-played as service, incurred and paid date. Carries "
                "claims_runout_complete_flag, the guardrail for any "
                "service-date trend.",
    },
    "dim_member": {
        "grain": "one member",
        "pk": "member_key",
        "business": ["member_id"],
        "fks": [("member_durable_key", "dim_master_person", "master_person_id",
                 "the resolved person behind this member")],
        "note": "Carries the -1 Unknown and -2 Not Applicable members. Type 1 "
                "on demographics.",
    },
    "dim_master_person": {
        "grain": "one resolved person",
        "pk": "master_person_key",
        "business": ["master_person_id"],
        "fks": [],
        "note": "Resolution quality on every row. ehr_records_resolved > 1 "
                "means an over-match: two real people on one identity.",
    },
    "dim_provider": {
        "grain": "one provider per tracked-attribute change (type 2)",
        "pk": "provider_key",
        "business": ["provider_master_id", "row_effective_date"],
        "fks": [("facility_id", "dim_facility", "facility_id", None),
                ("service_line_code", "dim_service_line", "service_line_code", None)],
        "note": "Type 2. provider_master_id is the durable key; provider_key is "
                "point-in-time correct. Role-played four ways: referring, "
                "performing, billing, attributed PCP.",
    },
    "dim_provider_current": {
        "grain": "one provider (current row only)",
        "pk": "provider_key",
        "business": ["provider_master_id"],
        "fks": [("facility_id", "dim_facility", "facility_id", None)],
        "note": "The convenience view. Using it reassigns a provider's whole "
                "history to their current facility - which is the point of the "
                "as-of-join lesson.",
    },
    "dim_facility": {
        "grain": "one site of care",
        "pk": "facility_key",
        "business": ["facility_id"],
        "fks": [],
        "note": "site_code is the join key used throughout the facts. Carries "
                "performs_msk_surgery and annual_msk_case_capacity.",
    },
    "dim_coverage_plan": {
        "grain": "one payer x product x plan x benefit year",
        "pk": "coverage_plan_key",
        "business": ["plan_code"],
        "fks": [],
        "note": "Payer is an ATTRIBUTE here, not its own dimension: every "
                "attribute analysts slice by lives at plan grain.",
    },
    "dim_diagnosis": {
        "grain": "one ICD-10-CM code",
        "pk": "diagnosis_key",
        "business": ["icd10_code"],
        "fks": [],
        "note": "sex_restriction and max_age drive the clinical plausibility "
                "assertions.",
    },
    "dim_procedure": {
        "grain": "one procedure code, all code systems",
        "pk": "procedure_key",
        "business": ["code_system", "procedure_code"],
        "fks": [],
        "note": "One dimension with code_system as discriminator. Splitting CPT "
                "from ICD-10-PCS would force a UNION on every procedure query.",
    },
    "dim_service_place": {
        "grain": "one place-of-service code",
        "pk": "service_place_key",
        "business": ["pos_code"],
        "fks": [],
        "note": None,
    },
    "dim_drg": {
        "grain": "one MS-DRG",
        "pk": "drg_key",
        "business": ["drg_code"],
        "fks": [],
        "note": "Joins to the claim HEADER only. DRG is a header attribute.",
    },
    "dim_claim_status": {
        "grain": "one adjudication status",
        "pk": "claim_status_key",
        "business": ["status_code"],
        "fks": [],
        "note": "CO-45 is deliberately absent: the contractual write-off is an "
                "AMOUNT on the line, not a denial status.",
    },
    "dim_service_line": {
        "grain": "one service line",
        "pk": "service_line_key",
        "business": ["service_line_code"],
        "fks": [],
        "note": None,
    },
    # --------------------------------------------------------- claims facts
    "fct_claim_header": {
        "grain": "one claim x one adjudication version",
        "pk": "claim_header_key",
        "business": ["claim_number", "adjudication_seq", "net_sign"],
        "fks": [("member_key", "dim_member", "member_key", None),
                ("encounter_id", "fct_encounter", "encounter_id",
                 "NULLABLE by design: ~24% of claims have no Northlake encounter"),
                ("service_site_code", "dim_facility", "site_code", None),
                ("drg_code", "dim_drg", "drg_code", "inpatient facility claims only"),
                ("claim_status_code", "dim_claim_status", "status_code", None)],
        "note": "DRG, admit/discharge, length of stay, disposition and the "
                "claim total live ONLY here, so a DRG-by-procedure question is "
                "forced through the header-to-line join.",
    },
    "fct_claim_line": {
        "grain": "one claim x one line x one adjudication version",
        "pk": "claim_line_key",
        "business": ["claim_number", "claim_line_number", "adjudication_seq",
                     "net_sign"],
        "fks": [("member_key", "dim_member", "member_key", None),
                ("member_durable_key", "dim_master_person", "master_person_id", None),
                ("servicing_provider_key", "dim_provider", "provider_key",
                 "resolves to -1 where credentialing has no record"),
                ("service_date_key", "dim_date", "date_key", None),
                ("paid_date_key", "dim_date", "date_key", None),
                ("claim_number", "fct_claim_header", "claim_number", None),
                ("encounter_id", "fct_encounter", "encounter_id", "nullable"),
                ("referral_id", "fct_referral", "referral_id",
                 "populated on referral episodes and consults only"),
                ("service_site_code", "dim_facility", "site_code", None),
                ("procedure_code", "dim_procedure", "procedure_code", None),
                ("pos_code", "dim_service_place", "pos_code", None)],
        "note": "The de-duplication target. The SURROGATE claim_line_key is "
                "unique even on the raw file, so a primary-key uniqueness test "
                "passes while the business key is violated.",
    },
    "br_claim_diagnosis": {
        "grain": "one claim header x one diagnosis position (1-12)",
        "pk": None,
        "business": ["claim_number", "diagnosis_position"],
        "fks": [("claim_number", "fct_claim_header", "claim_number", None),
                ("icd10_code", "dim_diagnosis", "icd10_code", None)],
        "note": "HEADER grain, exactly like an 837. Claim LINES carry pointers "
                "into this list rather than their own codes. Joining a line to "
                "this bridge FANS OUT - that is correct behavior, not a bug.",
    },
    # ------------------------------------------------------- clinical facts
    "fct_encounter": {
        "grain": "one EHR encounter",
        "pk": "encounter_id",
        "business": ["encounter_id"],
        "fks": [("member_key", "dim_member", "member_key",
                 "resolves to -1 where the crosswalk failed"),
                ("member_durable_key", "dim_master_person", "master_person_id", None),
                ("encounter_date_key", "dim_date", "date_key", None),
                ("facility_id", "dim_facility", "facility_id",
                 "resolved through the facility crosswalk"),
                ("attending_provider_master_id", "dim_provider",
                 "provider_master_id", None)],
        "note": "The three-hop join to claims lives here, and it loses the "
                "unmatched share NON-randomly.",
    },
    "br_encounter_diagnosis": {
        "grain": "one encounter x one diagnosis x position",
        "pk": None,
        "business": ["encounter_id", "diagnosis_position"],
        "fks": [("encounter_id", "fct_encounter", "encounter_id", None),
                ("icd10_code", "dim_diagnosis", "icd10_code", None)],
        "note": "Mean ~3.25 diagnoses per encounter. No pre-built cost "
                "allocation ships: deciding how to allocate is the lesson.",
    },
    "fct_lab_result": {
        "grain": "one resulted lab component per encounter",
        "pk": None,
        "business": ["encounter_id", "lab_code"],
        "fks": [("encounter_id", "fct_encounter", "encounter_id", None)],
        "note": "result_status = NO_STRUCTURED_RESULT where an external lab "
                "returned nothing parseable - one half of the HbA1c gap.",
    },
    # ------------------------------------------------------- referral facts
    "fct_referral": {
        "grain": "one referral order",
        "pk": "referral_id",
        "business": ["referral_id"],
        "fks": [("member_durable_key", "dim_master_person", "master_person_id", None),
                ("referring_site_code", "dim_facility", "site_code", None),
                ("destination_site_code", "dim_facility", "site_code", None),
                ("referring_provider_master_id", "dim_provider",
                 "provider_master_id", "nullable: ~4% carry no referring provider"),
                ("source_encounter_id", "fct_encounter", "encounter_id", None)],
        "note": "days_to_closure and closure_actor_type are the fingerprints of "
                "the auto-close rule. destination_status_per_ehr_directory is "
                "the STALE belief, never the fact.",
    },
    "fct_referral_outcome": {
        "grain": "one referral, evaluated against confirming events",
        "pk": None,
        "business": ["referral_id"],
        "fks": [("referral_id", "fct_referral", "referral_id", None)],
        "note": "An auditable bridge with match_rule_version on every row. "
                "confirm_source records whether a CLAIM, an APPOINTMENT, BOTH "
                "or NONE confirmed the referral - two independent paths, so the "
                "finding survives a challenge to either join.",
    },
    # ------------------------------------------------- membership / contract
    "fct_eligibility_span": {
        "grain": "one member x plan x contiguous coverage span",
        "pk": "eligibility_span_key",
        "business": ["member_id", "plan_code", "span_start_date", "coverage_type"],
        "fks": [("member_id", "dim_member", "member_id", None),
                ("plan_code", "dim_coverage_plan", "plan_code", None)],
        "note": "NOT a denominator. Contains deliberate overlaps; summing span "
                "lengths double counts every one of them. coverage_type is part "
                "of the grain: a COBRA span legitimately starts on the same day "
                "as the active coverage it runs alongside.",
    },
    "fct_member_month": {
        "grain": "one member x one year-month with any coverage",
        "pk": "member_month_key",
        "business": ["member_id", "year_month"],
        "fks": [("member_id", "dim_member", "member_id", None),
                ("year_month", "dim_date", "year_month", None),
                ("plan_code", "dim_coverage_plan", "plan_code", None)],
        "note": "The ONLY sanctioned PMPM denominator. Built as the "
                "gaps-and-islands UNION of coverage, not the sum of spans.",
    },
    "vbc_attribution_month": {
        "grain": "one member x one month, current roster version",
        "pk": "attribution_month_key",
        "business": ["member_id", "year_month"],
        "fks": [("member_id", "dim_member", "member_id", None),
                ("attributed_site_code", "dim_facility", "site_code", None)],
        "note": "Restated retroactively. Compare roster VERSIONS, not just the "
                "current roster, or a denominator change reads as performance.",
    },
    "vbc_attribution_restatement": {
        "grain": "one member x month whose attribution status changed, "
                 "x the roster version that changed it",
        "pk": "restatement_key",
        "business": ["member_id", "year_month", "as_of_version"],
        "fks": [("member_id", "dim_member", "member_id", None),
                ("as_of_version", "vbc_roster_version", "as_of_version", None),
                ("attributed_site_code", "dim_facility", "site_code", None)],
        "note": "The delta, not a full versioned history. Roster at version V "
                "= current roster, minus additions applied after V, plus "
                "terminations applied after V. Carries member_months and "
                "risk_score so that reconstruction needs no other table. "
                "Changes run in BOTH directions - new_status is "
                "RETRO_TERMINATED or ATTRIBUTED.",
    },
    "vbc_roster_version": {
        "grain": "one monthly roster production run",
        "pk": "roster_version_key",
        "business": ["as_of_version"],
        "fks": [],
        "note": "Six rows. Exists so an as-of control has something to bind "
                "to and so 'which version is current' is stated in the data "
                "rather than left to a MAX().",
    },
    "vbc_benchmark": {
        "grain": "one month x line of business",
        "pk": "benchmark_key",
        "business": ["year_month", "line_of_business"],
        "fks": [("year_month", "dim_date", "year_month", None)],
        "note": "Calibrated against the ATTRIBUTED cohort, not the whole "
                "book, and risk-adjusted through a score normalized to a book "
                "mean of 1.0 within line of business.",
    },
    "vbc_contract_terms": {
        "grain": "one contract x performance year",
        "pk": "contract_term_key",
        "business": ["contract_id", "performance_year"],
        "fks": [],
        "note": "Minimum savings rate, shared savings and loss rates, quality "
                "gate, and the high-cost truncation threshold. Without these a "
                "workbook can show PMPM moved and cannot show the cheque moved.",
    },
    # ------------------------------------------- settlement and completeness
    "fct_member_year_cost": {
        "grain": "one member x performance year",
        "pk": "member_year_cost_key",
        "business": ["member_id", "performance_year"],
        "fks": [("member_id", "dim_member", "member_id", None),
                ("member_durable_key", "dim_master_person", "master_person_id",
                 None)],
        "note": "High-cost truncation is an ANNUAL, MEMBER-LEVEL cap. Applying "
                "it per claim line caps nothing, because no single line "
                "reaches the threshold. fct_claim_line.allowed_amount_truncated "
                "is this cap allocated back down pro rata and sums to it "
                "exactly.",
    },
    "fct_claims_lag_triangle": {
        "grain": "one service month x lag month (0-12, tail lumped at 12)",
        "pk": "lag_triangle_key",
        "business": ["service_year_month", "lag_months"],
        "fks": [("service_year_month", "dim_date", "year_month", None)],
        "note": "Dense: a lag with no claims is a zero row, not a missing one. "
                "is_observable is true only where the WHOLE development period "
                "had elapsed by the paid-through date - the end of the lag "
                "month, not its start. completion_factor_derived is chain "
                "ladder over observable cells and reproduces "
                "dim_date.claims_completeness_factor from the data alone.",
    },
    # ------------------------------------------------ bridges / crosswalks
    "br_provider_affiliation": {
        "grain": "one provider x facility x effective span",
        "pk": "affiliation_key",
        "business": ["provider_master_id", "facility_id", "effective_date"],
        "fks": [("provider_master_id", "dim_provider", "provider_master_id", None),
                ("facility_id", "dim_facility", "facility_id", None)],
        "note": "22% of providers hold two or more concurrent affiliations, so "
                "an unweighted join FANS OUT and overstates facility totals. "
                "allocation_pct sums to exactly 1.0 per provider-span.",
    },
    "xwalk_patient": {
        "grain": "one source system x one source patient identifier",
        "pk": "xwalk_patient_key",
        "business": ["source_system", "source_patient_id"],
        "fks": [("master_person_id", "dim_master_person", "master_person_id",
                 "NULL where the record never matched")],
        "note": "Three patient key spaces. Imperfect in BOTH directions: "
                "under-match loses records non-randomly, over-match collapses "
                "two real people onto one identity.",
    },
    "xwalk_provider": {
        "grain": "one source system x one source provider identifier",
        "pk": "xwalk_provider_key",
        "business": ["source_system", "source_provider_id"],
        "fks": [("provider_master_id", "dim_provider", "provider_master_id", None)],
        "note": "Three provider key spaces: credentialed NPI, EHR internal id, "
                "and claim-side NPI.",
    },
    # -------------------------------------------------------- serving layer
    "vw_claim_line_enriched": {
        "grain": "one claim line (denormalized)",
        "pk": "claim_line_key",
        "business": ["claim_number", "claim_line_number", "adjudication_seq",
                     "net_sign"],
        "fks": [("member_key", "dim_member", "member_key", None),
                ("servicing_provider_key", "dim_provider", "provider_key", None)],
        "note": "Claim line joined to every type-1 dimension, NO bridges, one "
                "row per line, safe to sum. It is only safe BECAUSE the "
                "diagnosis bridges were kept out of it.",
    },
}
