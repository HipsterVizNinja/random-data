-- Healthcare Data Hub - stage and load
--
-- The generator writes gzipped CSV, so AUTO_COMPRESS handles decompression and
-- no format conversion is needed anywhere in the lift.

USE SCHEMA healthcare_data_hub_synth;

CREATE OR REPLACE FILE FORMAT ff_hdh_csv
    TYPE = CSV
    FIELD_DELIMITER = ','
    SKIP_HEADER = 1
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    NULL_IF = ('', 'NULL', 'None')
    EMPTY_FIELD_AS_NULL = TRUE
    COMPRESSION = GZIP;

CREATE STAGE IF NOT EXISTS stg_hdh FILE_FORMAT = ff_hdh_csv;

-- From the project folder:
--   snowsql -q "PUT file://Source%20Data/raw_elig/*.csv.gz @stg_hdh/raw_elig/ AUTO_COMPRESS=FALSE"
--   snowsql -q "PUT file://Mart/xwalk_*.csv.gz @stg_hdh/mdm/ AUTO_COMPRESS=FALSE"
--   snowsql -q "PUT file://Mart/dim_master_person.csv.gz @stg_hdh/mdm/ AUTO_COMPRESS=FALSE"
-- repeat per source folder, then:

COPY INTO raw_elig.elig_member            FROM @stg_hdh/raw_elig/elig_member.csv.gz;
COPY INTO raw_elig.elig_eligibility_span  FROM @stg_hdh/raw_elig/elig_eligibility_span.csv.gz;
COPY INTO raw_elig.elig_employer_group    FROM @stg_hdh/raw_elig/elig_employer_group.csv.gz;
COPY INTO raw_elig.elig_coverage_plan     FROM @stg_hdh/raw_elig/elig_coverage_plan.csv.gz;

COPY INTO raw_clm.clm_claim_line          FROM @stg_hdh/raw_clm/clm_claim_line.csv.gz;
COPY INTO raw_clm.clm_claim_header        FROM @stg_hdh/raw_clm/clm_claim_header.csv.gz;
COPY INTO raw_clm.clm_claim_diagnosis     FROM @stg_hdh/raw_clm/clm_claim_diagnosis.csv.gz;

COPY INTO raw_ehr.ehr_encounter           FROM @stg_hdh/raw_ehr/ehr_encounter.csv.gz;
COPY INTO raw_ehr.ehr_encounter_diagnosis FROM @stg_hdh/raw_ehr/ehr_encounter_diagnosis.csv.gz;
COPY INTO raw_ehr.ehr_lab_result          FROM @stg_hdh/raw_ehr/ehr_lab_result.csv.gz;
COPY INTO raw_ehr.ehr_referral_order      FROM @stg_hdh/raw_ehr/ehr_referral_order.csv.gz;
COPY INTO raw_ehr.ehr_provider_directory  FROM @stg_hdh/raw_ehr/ehr_provider_directory.csv.gz;
COPY INTO raw_ehr.ehr_patient             FROM @stg_hdh/raw_ehr/ehr_patient.csv.gz;

COPY INTO raw_pm.pm_appointment           FROM @stg_hdh/raw_pm/pm_appointment.csv.gz;
COPY INTO raw_pm.pm_authorization         FROM @stg_hdh/raw_pm/pm_authorization.csv.gz;
COPY INTO raw_pm.pm_referral_workflow_config FROM @stg_hdh/raw_pm/pm_referral_workflow_config.csv.gz;

COPY INTO raw_vbc.vbc_attribution_month       FROM @stg_hdh/raw_vbc/vbc_attribution_month.csv.gz;
COPY INTO raw_vbc.vbc_attribution_restatement FROM @stg_hdh/raw_vbc/vbc_attribution_restatement.csv.gz;
COPY INTO raw_vbc.vbc_benchmark               FROM @stg_hdh/raw_vbc/vbc_benchmark.csv.gz;

-- The crosswalks. The local build writes these under Mart/ since no separate
-- MDM system exists to land them from; stage them from there.
COPY INTO raw_mdm.xwalk_patient     FROM @stg_hdh/mdm/xwalk_patient.csv.gz;
COPY INTO raw_mdm.xwalk_provider    FROM @stg_hdh/mdm/xwalk_provider.csv.gz;
COPY INTO raw_mdm.dim_master_person FROM @stg_hdh/mdm/dim_master_person.csv.gz;

COPY INTO raw_ref.ref_network_contract      FROM @stg_hdh/raw_ref/ref_network_contract.csv.gz;
COPY INTO raw_ref.ref_provider              FROM @stg_hdh/raw_ref/ref_provider.csv.gz;
COPY INTO raw_ref.ref_provider_affiliation  FROM @stg_hdh/raw_ref/ref_provider_affiliation.csv.gz;

-- Reference code sets land the same way; add one COPY per remaining ref file
-- (ref_date, ref_diagnosis, ref_procedure, ref_service_place, ref_drg,
--  ref_claim_status, ref_service_line, ref_revenue_code, ref_facility,
--  ref_service_line_crosswalk, ref_facility_crosswalk, ref_npi_registry).

-- Row counts should match Deliverables/manifest.sha256 exactly.
SELECT 'clm_claim_line' AS table_name, COUNT(*) AS rows FROM raw_clm.clm_claim_line
UNION ALL SELECT 'clm_claim_header', COUNT(*) FROM raw_clm.clm_claim_header
UNION ALL SELECT 'ehr_encounter', COUNT(*) FROM raw_ehr.ehr_encounter
UNION ALL SELECT 'ehr_referral_order', COUNT(*) FROM raw_ehr.ehr_referral_order
UNION ALL SELECT 'elig_eligibility_span', COUNT(*) FROM raw_elig.elig_eligibility_span
ORDER BY table_name;
