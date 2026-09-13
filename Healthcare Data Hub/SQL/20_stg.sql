-- Healthcare Data Hub - staging layer
--
-- Typing, trimming, and code conformance. NO joins and NO business logic: the
-- moment staging starts joining, the layer stops being auditable and you lose
-- the ability to say "this is exactly what the source said, correctly typed".
--
-- The conformance work here is the substance. Three source systems encode sex
-- three different ways, one clinic emits an encounter type nobody mapped, and
-- one hospital changed its department identifier mid-2024.

USE SCHEMA healthcare_data_hub_synth;

-- ---------------------------------------------------------------------------
-- Sex arrives as M/F/U from eligibility, as HL7 table 0001 values 1/2/9 from
-- the EHR, and as Male/Female/Unknown from the attribution feed. One
-- vocabulary, and a documented source of truth per attribute.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW stg.elig__member AS
SELECT
    TRIM(member_id)                                   AS member_id,
    TRIM(subscriber_id)                               AS subscriber_id,
    TRIM(person_code)                                 AS person_code,
    TRIM(first_name)                                  AS first_name,
    TRIM(last_name)                                   AS last_name,
    TRY_TO_DATE(birth_date, 'YYYY-MM-DD')             AS birth_date,
    DECODE(UPPER(TRIM(sex)), 'M', 'M', 'F', 'F', 'U') AS sex,
    TRIM(sex)                                         AS sex_source_value,
    TRIM(postal_code)                                 AS postal_code,
    TRIM(region)                                      AS region,
    TRIM(line_of_business)                            AS line_of_business,
    TRY_TO_NUMBER(risk_score, 12, 4)                  AS risk_score
FROM raw_elig.elig_member;

CREATE OR REPLACE VIEW stg.ehr__patient AS
SELECT
    TRIM(mrn)                              AS mrn,
    TRIM(first_name)                       AS first_name,
    TRIM(last_name)                        AS last_name,
    TRY_TO_DATE(birth_date, 'YYYY-MM-DD')  AS birth_date,
    -- HL7 table 0001: 1 = male, 2 = female, 9 = unknown.
    DECODE(TRIM(sex), '1', 'M', '2', 'F', 'U') AS sex,
    TRIM(sex)                              AS sex_source_value,
    TRIM(postal_code)                      AS postal_code
FROM raw_ehr.ehr_patient;

-- ---------------------------------------------------------------------------
-- Claim lines. Money is NUMBER(12,2), never FLOAT: a float cent error
-- compounds across two million rows into a reconciliation break nobody can
-- explain.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW stg.clm__claim_line AS
SELECT
    TRY_TO_NUMBER(claim_line_key)                          AS claim_line_key,
    TRIM(claim_number)                                     AS claim_number,
    TRY_TO_NUMBER(claim_line_number)                       AS claim_line_number,
    TRY_TO_NUMBER(adjudication_seq)                        AS adjudication_seq,
    TRIM(member_id)                                        AS member_id,
    TRIM(mrn)                                              AS mrn,
    NULLIF(TRIM(encounter_id), '')                         AS encounter_id,
    TRIM(claim_type)                                       AS claim_type,
    TRIM(claim_role)                                       AS claim_role,
    TRIM(source_kind)                                      AS source_kind,
    TRY_TO_DATE(service_date, 'YYYY-MM-DD')                AS service_date,
    TRY_TO_DATE(paid_date, 'YYYY-MM-DD')                   AS paid_date,
    TRY_TO_NUMBER(paid_lag_days)                           AS paid_lag_days,
    TRIM(service_site_code)                                AS service_site_code,
    TO_BOOLEAN(is_out_of_network)                          AS is_out_of_network,
    TRIM(procedure_code)                                   AS procedure_code,
    TRIM(code_system)                                      AS code_system,
    TRIM(service_category)                                 AS service_category,
    TRY_TO_NUMBER(units, 9, 2)                             AS units,
    LPAD(TRIM(pos_code), 2, '0')                           AS pos_code,
    NULLIF(TRIM(revenue_code), '')                         AS revenue_code,
    NULLIF(TRIM(modifier_1), '')                           AS modifier_1,
    NULLIF(TRIM(modifier_2), '')                           AS modifier_2,
    NULLIF(TRIM(denial_code), '')                          AS denial_code,
    -- Dirty provider identifiers are trimmed and de-punctuated here, which is
    -- the only place that belongs.
    NULLIF(REGEXP_REPLACE(TRIM(servicing_provider_master_id), '[^A-Za-z0-9]', ''), '')
                                                           AS servicing_provider_master_id,
    NULLIF(REGEXP_REPLACE(TRIM(billing_provider_master_id), '[^A-Za-z0-9]', ''), '')
                                                           AS billing_provider_master_id,
    TRY_TO_NUMBER(billed_amount, 12, 2)                    AS billed_amount,
    TRY_TO_NUMBER(allowed_amount, 12, 2)                   AS allowed_amount,
    TRY_TO_NUMBER(contractual_writeoff_amount, 12, 2)      AS contractual_writeoff_amount,
    TRY_TO_NUMBER(deductible_amount, 12, 2)                AS deductible_amount,
    TRY_TO_NUMBER(copay_amount, 12, 2)                     AS copay_amount,
    TRY_TO_NUMBER(coinsurance_amount, 12, 2)               AS coinsurance_amount,
    TRY_TO_NUMBER(cob_amount, 12, 2)                       AS cob_amount,
    TRY_TO_NUMBER(paid_amount, 12, 2)                      AS paid_amount,
    TO_BOOLEAN(is_current_version)                         AS is_current_version,
    TO_BOOLEAN(is_reversal)                                AS is_reversal,
    TO_BOOLEAN(is_orphan_reversal)                         AS is_orphan_reversal,
    TRY_TO_NUMBER(net_sign)                                AS net_sign,
    NULLIF(TRIM(original_claim_number), '')                AS original_claim_number,
    TRIM(source_load_batch_id)                             AS source_load_batch_id
FROM raw_clm.clm_claim_line;

-- ---------------------------------------------------------------------------
-- Encounters. Two conformance problems land here.
--
-- 1. encounter_type_source drifts by site. Most emit 'OFFICE', four emit
--    'OFFICE VISIT', and one emits 'AMB' - which has NO row in the crosswalk
--    seed. It lands as UNKNOWN rather than being silently dropped, and the
--    conformance-coverage assertion in 60_audit.sql is what catches it.
-- 2. One hospital was renumbered in a mid-2024 EMR upgrade, so the same
--    physical site has two ehr_dept_id values. Resolving through
--    ref_facility_crosswalk is what stops it splitting into two facilities
--    as a step change in the middle of the year.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW stg.ehr__encounter AS
SELECT
    TRIM(e.encounter_id)                          AS encounter_id,
    TRIM(e.mrn)                                   AS mrn,
    TRIM(e.ehr_dept_id)                           AS ehr_dept_id,
    x.site_code                                   AS resolved_site_code,
    x.facility_id                                 AS facility_id,
    TRIM(e.encounter_class)                       AS encounter_class,
    TRIM(e.encounter_type_source)                 AS encounter_type_source,
    COALESCE(m.service_line_code, 'UNKNOWN')      AS service_line_code,
    CASE UPPER(TRIM(e.encounter_type_source))
        WHEN 'OFFICE'       THEN 'AMBULATORY'
        WHEN 'OFFICE VISIT' THEN 'AMBULATORY'
        WHEN 'URGENT'       THEN 'URGENT_CARE'
        WHEN 'ED'           THEN 'EMERGENCY'
        WHEN 'INPATIENT'    THEN 'INPATIENT'
        ELSE 'UNKNOWN'
    END                                           AS encounter_type_conformed,
    TRY_TO_DATE(e.encounter_date, 'YYYY-MM-DD')   AS encounter_date,
    TRY_TO_DATE(e.admit_date, 'YYYY-MM-DD')       AS admit_date,
    TRY_TO_DATE(e.discharge_date, 'YYYY-MM-DD')   AS discharge_date,
    TRY_TO_NUMBER(e.length_of_stay_days)          AS length_of_stay_days,
    TRIM(e.attending_provider_master_id)          AS attending_provider_master_id,
    TRIM(e.discharge_disposition)                 AS discharge_disposition
FROM raw_ehr.ehr_encounter e
LEFT JOIN raw_ref.ref_facility_crosswalk x
       ON TRIM(e.ehr_dept_id) = TRIM(x.ehr_dept_id)
      AND TRY_TO_DATE(e.encounter_date, 'YYYY-MM-DD')
          BETWEEN TRY_TO_DATE(x.effective_date, 'YYYY-MM-DD')
              AND TRY_TO_DATE(x.expiration_date, 'YYYY-MM-DD')
LEFT JOIN raw_ref.ref_service_line_crosswalk m
       ON m.crosswalk_domain = 'EHR_DEPARTMENT'
      AND UPPER(TRIM(m.source_value)) = UPPER(TRIM(e.encounter_type_source))
      AND TRY_TO_NUMBER(m.mapping_version) = 1;

CREATE OR REPLACE VIEW stg.ehr__referral_order AS
SELECT
    TRIM(referral_id)                              AS referral_id,
    TRIM(source_encounter_id)                      AS source_encounter_id,
    TRIM(mrn)                                      AS mrn,
    TRIM(referring_site_code)                      AS referring_site_code,
    NULLIF(TRIM(referring_provider_master_id), '') AS referring_provider_master_id,
    TRIM(referral_specialty_code)                  AS referral_specialty_code,
    TRY_TO_DATE(placed_date, 'YYYY-MM-DD')         AS placed_date,
    TRIM(destination_site_code)                    AS destination_site_code,
    TRIM(destination_status_per_ehr_directory)     AS destination_status_per_ehr_directory,
    TRIM(referral_status)                          AS referral_status,
    TRY_TO_NUMBER(days_to_closure)                 AS days_to_closure,
    TRY_TO_DATE(closure_date, 'YYYY-MM-DD')        AS closure_date,
    NULLIF(TRIM(closure_actor_type), '')           AS closure_actor_type
FROM raw_ehr.ehr_referral_order;

CREATE OR REPLACE VIEW stg.elig__eligibility_span AS
SELECT
    TRY_TO_NUMBER(eligibility_span_key)           AS eligibility_span_key,
    TRIM(member_id)                               AS member_id,
    TRIM(group_id)                                AS group_id,
    TRIM(plan_code)                               AS plan_code,
    TRIM(line_of_business)                        AS line_of_business,
    TRY_TO_DATE(span_start_date, 'YYYY-MM-DD')    AS span_start_date,
    TRY_TO_DATE(span_end_date, 'YYYY-MM-DD')      AS span_end_date,
    TRIM(coverage_type)                           AS coverage_type,
    TO_BOOLEAN(is_primary_coverage)               AS is_primary_coverage,
    NULLIF(TRIM(overlap_reason), '')              AS overlap_reason
FROM raw_elig.elig_eligibility_span;
