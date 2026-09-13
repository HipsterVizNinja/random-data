-- Healthcare Data Hub - Snowflake DDL
-- Synthetic demonstration data. Not derived from real patient records.
--
-- Landing tables mirror the flat files exactly: everything lands as VARCHAR.
-- Typing happens in the stg layer, which is the only honest place for it -
-- a real source emits strings, and pretending otherwise hides the conformance
-- work that is the point of this dataset.

CREATE SCHEMA IF NOT EXISTS healthcare_data_hub_synth;
USE SCHEMA healthcare_data_hub_synth;

CREATE SCHEMA IF NOT EXISTS raw_elig;
CREATE SCHEMA IF NOT EXISTS raw_clm;
CREATE SCHEMA IF NOT EXISTS raw_ehr;
CREATE SCHEMA IF NOT EXISTS raw_pm;
CREATE SCHEMA IF NOT EXISTS raw_vbc;
CREATE SCHEMA IF NOT EXISTS raw_ref;
-- Identity resolution is owned by an MDM process, so it stages as a SOURCE
-- rather than being derived inside the warehouse. The local build writes
-- these files to Mart/ because there is no separate MDM system to land
-- them from; in Snowflake they belong in their own raw schema.
CREATE SCHEMA IF NOT EXISTS raw_mdm;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS mart;
CREATE SCHEMA IF NOT EXISTS audit;

-- A single-row notice table so the dataset announces itself in any catalog,
-- data-source picker, or lineage view.
CREATE OR REPLACE TABLE mart._synthetic_data_notice (
    notice              VARCHAR,
    generated_by        VARCHAR,
    master_seed         NUMBER(10,0),
    hipaa_note          VARCHAR
);
INSERT INTO mart._synthetic_data_notice VALUES (
    'Synthetic data - Concord demonstration asset. Not derived from real patient records.',
    'Healthcare Data Hub generator, Generators/build.py',
    20260911,
    'Wholly fabricated. HIPAA de-identification standards (Safe Harbor, Expert '
    || 'Determination) do not apply and are not claimed. This data is NOT '
    || '"HIPAA compliant" because that concept does not apply to fabricated records.'
);

-- ---------------------------------------------------------------- raw_elig
CREATE OR REPLACE TABLE raw_elig.elig_member (
    member_id VARCHAR, subscriber_id VARCHAR, person_code VARCHAR,
    first_name VARCHAR, middle_initial VARCHAR, last_name VARCHAR,
    birth_date VARCHAR, sex VARCHAR, street_address VARCHAR,
    postal_code VARCHAR, region VARCHAR, line_of_business VARCHAR,
    risk_score VARCHAR, data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_elig.elig_eligibility_span (
    eligibility_span_key VARCHAR, member_id VARCHAR, subscriber_id VARCHAR,
    group_id VARCHAR, plan_code VARCHAR, line_of_business VARCHAR,
    span_start_date VARCHAR, span_end_date VARCHAR, coverage_type VARCHAR,
    is_primary_coverage VARCHAR, has_medical VARCHAR, has_rx VARCHAR,
    overlap_reason VARCHAR, data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_elig.elig_employer_group (
    group_id VARCHAR, group_name VARCHAR, enrollment_weight VARCHAR,
    is_acquired VARCHAR, data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_elig.elig_coverage_plan (
    coverage_plan_key VARCHAR, plan_code VARCHAR, plan_name VARCHAR,
    payer_name VARCHAR, line_of_business VARCHAR, product VARCHAR,
    funding_type VARCHAR, metal_tier VARCHAR, benefit_year VARCHAR,
    deductible_amount VARCHAR, oop_max_amount VARCHAR,
    requires_referral VARCHAR, is_risk_contract VARCHAR,
    data_classification VARCHAR
);

-- ----------------------------------------------------------------- raw_clm
CREATE OR REPLACE TABLE raw_clm.clm_claim_line (
    claim_line_key VARCHAR, claim_number VARCHAR, claim_line_number VARCHAR,
    claim_seq VARCHAR, member_id VARCHAR, mrn VARCHAR, encounter_id VARCHAR,
    claim_type VARCHAR, claim_role VARCHAR, source_kind VARCHAR,
    service_date VARCHAR, service_site_code VARCHAR, is_out_of_network VARCHAR,
    procedure_code VARCHAR, code_system VARCHAR, service_category VARCHAR,
    units VARCHAR, servicing_provider_master_id VARCHAR,
    billing_provider_master_id VARCHAR, latent_risk VARCHAR, region VARCHAR,
    pos_code VARCHAR, revenue_code VARCHAR, modifier_1 VARCHAR,
    modifier_2 VARCHAR, billed_amount VARCHAR, allowed_amount VARCHAR,
    contractual_writeoff_amount VARCHAR, denial_code VARCHAR,
    deductible_amount VARCHAR, copay_amount VARCHAR, coinsurance_amount VARCHAR,
    cob_amount VARCHAR, paid_amount VARCHAR, paid_date VARCHAR,
    paid_lag_days VARCHAR, adjudication_seq VARCHAR, is_current_version VARCHAR,
    net_sign VARCHAR, original_claim_number VARCHAR, is_orphan_reversal VARCHAR,
    source_load_batch_id VARCHAR, is_reversal VARCHAR, data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_clm.clm_claim_header (
    claim_header_key VARCHAR, claim_number VARCHAR, adjudication_seq VARCHAR,
    claim_seq VARCHAR, member_id VARCHAR, mrn VARCHAR, encounter_id VARCHAR,
    claim_type VARCHAR, claim_role VARCHAR, source_kind VARCHAR,
    service_site_code VARCHAR, is_out_of_network VARCHAR,
    service_from_date VARCHAR, service_to_date VARCHAR, paid_date VARCHAR,
    billing_provider_master_id VARCHAR, servicing_provider_master_id VARCHAR,
    line_count VARCHAR, total_billed_amount VARCHAR, total_allowed_amount VARCHAR,
    total_claim_paid_amount VARCHAR, net_sign VARCHAR, is_current_version VARCHAR,
    is_reversal VARCHAR, is_orphan_reversal VARCHAR, original_claim_number VARCHAR,
    source_load_batch_id VARCHAR, length_of_stay_days VARCHAR, admit_date VARCHAR,
    discharge_date VARCHAR, discharge_disposition VARCHAR, encounter_class VARCHAR,
    drg_code VARCHAR, claim_status_code VARCHAR, data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_clm.clm_claim_diagnosis (
    claim_number VARCHAR, diagnosis_position VARCHAR, icd10_code VARCHAR,
    is_primary VARCHAR, data_classification VARCHAR
);

-- ----------------------------------------------------------------- raw_ehr
CREATE OR REPLACE TABLE raw_ehr.ehr_encounter (
    encounter_id VARCHAR, mrn VARCHAR, member_id_truth VARCHAR,
    ehr_dept_id VARCHAR, site_code VARCHAR, encounter_class VARCHAR,
    encounter_type_source VARCHAR, encounter_date VARCHAR, admit_date VARCHAR,
    discharge_date VARCHAR, length_of_stay_days VARCHAR,
    attending_provider_master_id VARCHAR, patient_region VARCHAR,
    discharge_disposition VARCHAR, data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_ehr.ehr_encounter_diagnosis (
    encounter_id VARCHAR, diagnosis_position VARCHAR, icd10_code VARCHAR,
    is_primary VARCHAR, data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_ehr.ehr_lab_result (
    encounter_id VARCHAR, mrn VARCHAR, result_date VARCHAR, lab_code VARCHAR,
    lab_name VARCHAR, loinc_code VARCHAR, performing_lab_site VARCHAR,
    result_value VARCHAR, result_unit VARCHAR, result_status VARCHAR,
    is_abnormal VARCHAR, data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_ehr.ehr_referral_order (
    referral_id VARCHAR, source_encounter_id VARCHAR, mrn VARCHAR,
    referring_site_code VARCHAR, referring_provider_master_id VARCHAR,
    referral_specialty_code VARCHAR, placed_date VARCHAR,
    destination_site_code VARCHAR, destination_status_per_ehr_directory VARCHAR,
    referral_status VARCHAR, days_to_closure VARCHAR, closure_date VARCHAR,
    closure_actor_type VARCHAR, patient_region VARCHAR, data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_ehr.ehr_provider_directory (
    ehr_dept_id VARCHAR, site_code VARCHAR, facility_display_name VARCHAR,
    referral_network_status VARCHAR, accepts_referrals VARCHAR,
    last_maintained_date VARCHAR, data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_ehr.ehr_patient (
    mrn VARCHAR, first_name VARCHAR, last_name VARCHAR, birth_date VARCHAR,
    sex VARCHAR, postal_code VARCHAR, data_classification VARCHAR
);

-- ------------------------------------------------------------------ raw_pm
CREATE OR REPLACE TABLE raw_pm.pm_appointment (
    appointment_id VARCHAR, referral_id VARCHAR, mrn VARCHAR, site_code VARCHAR,
    appointment_date VARCHAR, appointment_status VARCHAR,
    appointment_type VARCHAR, scheduled_by_site_code VARCHAR,
    data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_pm.pm_authorization (
    authorization_id VARCHAR, referral_id VARCHAR, mrn VARCHAR,
    requested_date VARCHAR, decision_date VARCHAR, authorization_status VARCHAR,
    requested_site_code VARCHAR, units_requested VARCHAR, denial_reason VARCHAR,
    data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_pm.pm_referral_workflow_config (
    workflow_config_key VARCHAR, rule_code VARCHAR, rule_name VARCHAR,
    site_code VARCHAR, effective_date VARCHAR, expiration_date VARCHAR,
    rule_parameter_days VARCHAR, sets_status_to VARCHAR,
    requires_confirming_event VARCHAR, configured_by VARCHAR, rule_note VARCHAR,
    data_classification VARCHAR
);

-- ----------------------------------------------------------------- raw_vbc
CREATE OR REPLACE TABLE raw_vbc.vbc_attribution_month (
    attribution_month_key VARCHAR, member_id VARCHAR, year_month VARCHAR,
    year_month_name VARCHAR, attributed_site_code VARCHAR,
    line_of_business VARCHAR, member_months VARCHAR, risk_score VARCHAR,
    attribution_status VARCHAR, as_of_version VARCHAR, as_of_date VARCHAR,
    data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_vbc.vbc_attribution_restatement (
    restatement_key VARCHAR, member_id VARCHAR, year_month VARCHAR,
    year_month_name VARCHAR, attributed_site_code VARCHAR, prior_status VARCHAR,
    new_status VARCHAR, restatement_reason VARCHAR, as_of_date VARCHAR,
    data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_vbc.vbc_benchmark (
    benchmark_key VARCHAR, year_month VARCHAR, year_month_name VARCHAR,
    line_of_business VARCHAR, benchmark_pmpm VARCHAR, mean_risk_score VARCHAR,
    risk_adjusted_benchmark_pmpm VARCHAR, attributed_member_months VARCHAR,
    data_classification VARCHAR
);

-- ----------------------------------------------------------------- raw_ref
-- Reference tables land generically: the generator writes them with stable
-- headers, so a single CSV-inferred landing pattern is used per file.
CREATE OR REPLACE TABLE raw_ref.ref_network_contract (
    network_contract_key VARCHAR, tin VARCHAR, facility_id VARCHAR,
    site_code VARCHAR, network_status VARCHAR, effective_date VARCHAR,
    expiration_date VARCHAR, is_current VARCHAR, termination_reason VARCHAR,
    data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_ref.ref_provider (
    provider_key VARCHAR, provider_master_id VARCHAR, npi VARCHAR,
    ehr_provider_id VARCHAR, provider_name VARCHAR, first_name VARCHAR,
    last_name VARCHAR, sex VARCHAR, primary_specialty VARCHAR,
    taxonomy_code VARCHAR, service_line_code VARCHAR, is_pcp VARCHAR,
    site_code VARCHAR, facility_id VARCHAR, tin VARCHAR, network_status VARCHAR,
    row_effective_date VARCHAR, row_expiration_date VARCHAR, is_current VARCHAR,
    data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_ref.ref_provider_affiliation (
    affiliation_key VARCHAR, provider_master_id VARCHAR, npi VARCHAR,
    site_code VARCHAR, facility_id VARCHAR, effective_date VARCHAR,
    expiration_date VARCHAR, allocation_pct VARCHAR, is_primary_site VARCHAR,
    affiliation_note VARCHAR, data_classification VARCHAR
);

-- ----------------------------------------------------------------- raw_mdm
CREATE OR REPLACE TABLE raw_mdm.xwalk_patient (
    xwalk_patient_key VARCHAR, source_system VARCHAR, source_patient_id VARCHAR,
    master_person_id VARCHAR, match_method VARCHAR, match_score VARCHAR,
    match_run_date VARCHAR, is_active VARCHAR, data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_mdm.xwalk_provider (
    xwalk_provider_key VARCHAR, source_system VARCHAR, source_provider_id VARCHAR,
    provider_master_id VARCHAR, npi VARCHAR, match_method VARCHAR,
    match_score VARCHAR, match_run_date VARCHAR, is_active VARCHAR,
    data_classification VARCHAR
);

CREATE OR REPLACE TABLE raw_mdm.dim_master_person (
    master_person_key VARCHAR, master_person_id VARCHAR,
    source_system_count VARCHAR, best_match_score VARCHAR, weakest_method VARCHAR,
    has_claims VARCHAR, has_ehr VARCHAR, has_attribution VARCHAR,
    is_multi_source VARCHAR, ehr_records_resolved VARCHAR,
    resolution_confidence VARCHAR, data_classification VARCHAR
);
