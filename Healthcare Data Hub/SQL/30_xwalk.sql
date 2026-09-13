-- Healthcare Data Hub - identity resolution
--
-- Physical TABLES, not views. Matching is expensive, has to be deterministic
-- across runs, and needs to be independently queryable as an artifact - "show
-- me the match-method distribution" is a question a data steward asks weekly.
--
-- The crosswalk is imperfect in BOTH directions on purpose:
--   under-match  a share of EHR records never resolve, and the loss is NOT
--                random - it skews toward one clinic group, so a naive inner
--                join deletes part of the finding and UNDERSTATES leakage
--   over-match   a few dozen master IDs collapse two genuinely distinct
--                people (twins, Jr/Sr pairs), landing as artificial
--                super-utilizers at the top of the cost distribution

USE SCHEMA healthcare_data_hub_synth;

CREATE OR REPLACE TABLE stg.xwalk_patient AS
SELECT
    TRY_TO_NUMBER(xwalk_patient_key)      AS xwalk_patient_key,
    TRIM(source_system)                   AS source_system,
    TRIM(source_patient_id)               AS source_patient_id,
    NULLIF(TRIM(master_person_id), '')    AS master_person_id,
    TRIM(match_method)                    AS match_method,
    TRY_TO_NUMBER(match_score, 4, 3)      AS match_score,
    TRY_TO_DATE(match_run_date, 'YYYY-MM-DD') AS match_run_date,
    TO_BOOLEAN(is_active)                 AS is_active
FROM raw_mdm.xwalk_patient;

CREATE OR REPLACE TABLE stg.xwalk_provider AS
SELECT
    TRY_TO_NUMBER(xwalk_provider_key)     AS xwalk_provider_key,
    TRIM(source_system)                   AS source_system,
    TRIM(source_provider_id)              AS source_provider_id,
    TRIM(provider_master_id)              AS provider_master_id,
    TRIM(npi)                             AS npi,
    TRIM(match_method)                    AS match_method,
    TRY_TO_NUMBER(match_score, 4, 3)      AS match_score
FROM raw_mdm.xwalk_provider;

-- Match-quality summary. Worth surfacing in the demo: a stewardship queue is
-- a governance mechanism, not a report.
CREATE OR REPLACE VIEW audit.vw_match_quality AS
SELECT
    source_system,
    match_method,
    COUNT(*)                                                  AS records,
    ROUND(RATIO_TO_REPORT(COUNT(*)) OVER (PARTITION BY source_system), 4)
                                                              AS share_of_source,
    ROUND(MIN(match_score), 3)                                AS min_score,
    ROUND(MAX(match_score), 3)                                AS max_score
FROM stg.xwalk_patient
GROUP BY source_system, match_method
ORDER BY source_system, records DESC;

-- The over-match detector. One query, and it is the satisfying teaching beat:
-- a master person carrying two distinct sexes or two distinct dates of birth
-- is two people wearing one identity.
CREATE OR REPLACE VIEW audit.vw_overmatch_candidates AS
SELECT
    x.master_person_id,
    COUNT(DISTINCT p.sex)        AS distinct_sex_values,
    COUNT(DISTINCT p.birth_date) AS distinct_birth_dates,
    COUNT(*)                     AS source_records,
    MIN(x.match_score)           AS weakest_match_score,
    MIN(x.match_method)          AS match_method
FROM stg.xwalk_patient x
JOIN stg.ehr__patient  p ON p.mrn = x.source_patient_id
WHERE x.source_system = 'CARELINE_EHR'
  AND x.master_person_id IS NOT NULL
GROUP BY x.master_person_id
HAVING COUNT(DISTINCT p.sex) > 1
    OR COUNT(DISTINCT p.birth_date) > 1
ORDER BY distinct_sex_values DESC, weakest_match_score;

-- Is the match loss random? Profile the unmatched against the matched on
-- several attributes before reporting ANY cross-source rate. If the unmatched
-- population is skewed, every rate computed on an inner join is biased in a
-- direction you have not measured.
CREATE OR REPLACE VIEW audit.vw_unmatched_skew AS
WITH ehr AS (
    SELECT x.source_patient_id AS mrn,
           x.match_method,
           (x.match_method = 'UNMATCHED') AS is_unmatched
    FROM stg.xwalk_patient x
    WHERE x.source_system = 'CARELINE_EHR'
)
SELECT
    a.attributed_site_code,
    COUNT(*)                                        AS ehr_records,
    SUM(IFF(e.is_unmatched, 1, 0))                  AS unmatched_records,
    ROUND(AVG(IFF(e.is_unmatched, 1, 0)), 4)        AS unmatched_rate
FROM ehr e
JOIN raw_ehr.ehr_encounter n ON n.mrn = e.mrn
JOIN raw_vbc.vbc_attribution_month a ON a.member_id = n.member_id_truth
GROUP BY a.attributed_site_code
ORDER BY unmatched_rate DESC;
