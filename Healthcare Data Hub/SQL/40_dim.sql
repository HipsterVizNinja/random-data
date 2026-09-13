-- Healthcare Data Hub - conformed dimensions
--
-- Two opinionated calls worth stating rather than discovering.
--
-- Payer collapses INTO plan. A dim_payer with one row is a snowflake for no
-- gain: every attribute analysts actually slice by - line of business,
-- funding type, product, metal tier - lives at plan grain.
--
-- ONE procedure dimension with code_system as a discriminator. Splitting CPT
-- from ICD-10-PCS is technically purer and practically hostile: "spend by
-- procedure" then needs two joins and a UNION every single time.
--
-- Every dimension carries a -1 Unknown and a -2 Not Applicable member. Facts
-- resolve unmatched keys to -1 and carry a companion resolution-status
-- column, so the mart stays inner-joinable AND the defect stays countable.
-- The trap then becomes an analyst who ignores the -1 bucket, which is the
-- realistic failure mode anyway.

USE SCHEMA healthcare_data_hub_synth;

CREATE OR REPLACE TABLE mart.dim_date AS
SELECT
    TRY_TO_NUMBER(date_key)                          AS date_key,
    TRY_TO_DATE(full_date, 'YYYY-MM-DD')             AS full_date,
    TRY_TO_NUMBER(calendar_year)                     AS calendar_year,
    TRY_TO_NUMBER(calendar_month)                    AS calendar_month,
    TRY_TO_NUMBER(year_month)                        AS year_month,
    year_month_name,
    TRY_TO_NUMBER(calendar_quarter)                  AS calendar_quarter,
    TRY_TO_NUMBER(day_of_week)                       AS day_of_week,
    day_name,
    TO_BOOLEAN(is_weekend)                           AS is_weekend,
    TO_BOOLEAN(is_holiday)                           AS is_holiday,
    TO_BOOLEAN(is_month_end)                         AS is_month_end,
    TRY_TO_NUMBER(days_in_month)                     AS days_in_month,
    TRY_TO_NUMBER(fiscal_year)                       AS fiscal_year,
    TRY_TO_NUMBER(fiscal_quarter)                    AS fiscal_quarter,
    TRY_TO_NUMBER(claims_completeness_factor, 5, 2)  AS claims_completeness_factor,
    TO_BOOLEAN(claims_runout_complete_flag)          AS claims_runout_complete_flag,
    TO_BOOLEAN(is_in_source_window)                  AS is_in_source_window,
    TO_BOOLEAN(is_in_analysis_window)                AS is_in_analysis_window
FROM raw_ref.ref_date;

-- ---------------------------------------------------------------------------
-- dim_member. The durable key is what makes the hub usable by two different
-- audiences: the architecture-minded join on the point-in-time key and see
-- the type-2 mechanics; the hands-on analyst joins the durable key against
-- the _current view and gets a right answer in five minutes.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE mart.dim_member AS
SELECT -1 AS member_key, 'UNKNOWN' AS member_id, NULL AS member_durable_key,
       NULL AS first_name, NULL AS last_name, NULL AS birth_date, NULL AS sex,
       NULL AS postal_code, NULL AS region, NULL AS line_of_business,
       NULL AS risk_score, 'SYNTHETIC' AS data_classification
UNION ALL
SELECT -2, 'NOT_APPLICABLE', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       NULL, 'SYNTHETIC'
UNION ALL
SELECT
    ROW_NUMBER() OVER (ORDER BY m.member_id) AS member_key,
    m.member_id,
    x.master_person_id                       AS member_durable_key,
    m.first_name, m.last_name,
    TO_VARCHAR(m.birth_date), m.sex,
    m.postal_code, m.region, m.line_of_business,
    TO_VARCHAR(m.risk_score),
    'SYNTHETIC'
FROM stg.elig__member m
LEFT JOIN stg.xwalk_patient x
       ON x.source_system = 'MERIDIAN_ELIG'
      AND x.source_patient_id = m.member_id;

-- ---------------------------------------------------------------------------
-- dim_provider, type 2. The affiliation change matters: a cardiologist moves
-- facility mid-window, and a CURRENT-state dimension silently reassigns
-- three years of her history to the new site. Both views ship.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE mart.dim_provider AS
SELECT
    TRY_TO_NUMBER(provider_key)                       AS provider_key,
    provider_master_id, npi, ehr_provider_id, provider_name,
    first_name, last_name, sex, primary_specialty, taxonomy_code,
    service_line_code,
    TO_BOOLEAN(is_pcp)                                AS is_pcp,
    site_code, facility_id, tin, network_status,
    TRY_TO_DATE(row_effective_date, 'YYYY-MM-DD')     AS row_effective_date,
    TRY_TO_DATE(row_expiration_date, 'YYYY-MM-DD')    AS row_expiration_date,
    TO_BOOLEAN(is_current)                            AS is_current,
    'SYNTHETIC'                                       AS data_classification
FROM raw_ref.ref_provider;

CREATE OR REPLACE VIEW mart.dim_provider_current AS
SELECT * FROM mart.dim_provider WHERE is_current;

-- ---------------------------------------------------------------------------
-- Network participation, type 2 on TIN x effective window.
--
-- This is the single most persuasive architecture argument in the deck,
-- because it is the one that cost real money. Summit Point's contract
-- terminated 2024-10-01. The EHR referral directory still reads PAR. An
-- as-of-service-date join against THIS table is the only correct way to
-- answer "was this provider in network when the care happened".
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE mart.dim_network_contract AS
SELECT
    TRY_TO_NUMBER(network_contract_key)            AS network_contract_key,
    tin, facility_id, site_code, network_status,
    TRY_TO_DATE(effective_date, 'YYYY-MM-DD')      AS effective_date,
    TRY_TO_DATE(expiration_date, 'YYYY-MM-DD')     AS expiration_date,
    TO_BOOLEAN(is_current)                         AS is_current,
    termination_reason,
    'SYNTHETIC'                                    AS data_classification
FROM raw_ref.ref_network_contract;

-- The as-of join, packaged so nobody has to remember to write it.
CREATE OR REPLACE FUNCTION mart.f_network_status_asof(
    p_site_code VARCHAR, p_service_date DATE
)
RETURNS VARCHAR
AS
$$
    SELECT network_status
    FROM mart.dim_network_contract
    WHERE site_code = p_site_code
      AND p_service_date BETWEEN effective_date AND expiration_date
    LIMIT 1
$$;

CREATE OR REPLACE TABLE mart.dim_facility AS
SELECT
    TRY_TO_NUMBER(facility_key)              AS facility_key,
    facility_id, site_code, facility_name, facility_type, region, postal_code,
    TRY_TO_NUMBER(bed_count)                 AS bed_count,
    TO_BOOLEAN(is_in_network_current)        AS is_in_network_current,
    service_line_group, tin, ccn,
    TO_BOOLEAN(is_clinic_group)              AS is_clinic_group,
    TRY_TO_NUMBER(attributed_panel_weight, 6, 4) AS attributed_panel_weight,
    'SYNTHETIC'                              AS data_classification
FROM raw_ref.ref_facility;

CREATE OR REPLACE TABLE mart.dim_procedure AS
SELECT
    TRY_TO_NUMBER(procedure_key)      AS procedure_key,
    code_system, procedure_code, procedure_description, service_category,
    betos_category,
    TRY_TO_NUMBER(typical_units)      AS typical_units,
    TO_BOOLEAN(is_facility_only)      AS is_facility_only,
    TO_BOOLEAN(is_msk_surgical)       AS is_msk_surgical,
    TO_BOOLEAN(bilateral_capable)     AS bilateral_capable,
    'SYNTHETIC'                       AS data_classification
FROM raw_ref.ref_procedure;

CREATE OR REPLACE TABLE mart.dim_diagnosis AS
SELECT
    TRY_TO_NUMBER(diagnosis_key)          AS diagnosis_key,
    icd10_code, icd10_description, ccsr_category, ccsr_body_system,
    TO_BOOLEAN(chronic_condition_flag)    AS chronic_condition_flag,
    hcc_code, condition_code, sex_restriction,
    TRY_TO_NUMBER(max_age)                AS max_age,
    'SYNTHETIC'                           AS data_classification
FROM raw_ref.ref_diagnosis;
