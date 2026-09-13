-- Healthcare Data Hub - the validation suite as SQL
--
-- The design point that makes this layer worth building: planted anomalies
-- assert as EXPECTED with a magnitude, not as failures. A suite that goes red
-- on purpose teaches nothing. One that reads "orphan servicing providers:
-- expected 1,312, actual 1,312, $2.9M exposure - CONTROLLED" is a business
-- document rather than a QA log.
--
-- Severities: ERROR / WARN / INFO / EXPECTED.

USE SCHEMA healthcare_data_hub_synth;

-- ---------------------------------------------------------------------------
-- The reconciliation ladder. The most demo-valuable output in the project:
-- raw total, then each step's delta, every one with a NAMED reason.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW audit.vw_reconciliation_ladder AS
WITH raw_total AS (
    SELECT 1 AS step_order, 'Raw claim lines as received' AS step,
           COUNT(*) AS rows, SUM(paid_amount) AS paid
    FROM stg.clm__claim_line
), deduped AS (
    SELECT 2, 'Less duplicate lines from the re-driven extract',
           COUNT(*), SUM(paid_amount)
    FROM mart.fct_claim_line
), current_only AS (
    SELECT 3, 'Net of reversals and adjustments (is_current_version)',
           COUNT(*), SUM(paid_amount)
    FROM mart.fct_claim_line WHERE is_current_version
), complete_months AS (
    SELECT 4, 'Restricted to service months with complete runout',
           COUNT(*), SUM(l.paid_amount)
    FROM mart.fct_claim_line l
    JOIN mart.dim_date d ON d.date_key = l.service_date_key
    WHERE l.is_current_version AND d.claims_runout_complete_flag
)
SELECT * FROM raw_total
UNION ALL SELECT * FROM deduped
UNION ALL SELECT * FROM current_only
UNION ALL SELECT * FROM complete_months
ORDER BY step_order;

-- ---------------------------------------------------------------------------
-- The orphan matrix. The dollar column is what turns a QA log into a
-- business document: an orphan COUNT is a curiosity, and orphan DOLLARS that
-- an inner join would silently delete is a finding.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW audit.vw_orphan_matrix AS
SELECT
    'fct_claim_line'                          AS fact_table,
    'dim_provider (servicing)'                AS dimension_table,
    servicing_provider_resolution_status      AS resolution_status,
    COUNT(*)                                  AS orphan_rows,
    ROUND(RATIO_TO_REPORT(COUNT(*)) OVER (), 4) AS share_of_fact,
    ROUND(SUM(paid_amount), 2)                AS orphan_dollars
FROM mart.fct_claim_line
WHERE is_current_version
GROUP BY servicing_provider_resolution_status
UNION ALL
SELECT
    'fct_claim_line', 'dim_member', member_resolution_status,
    COUNT(*), ROUND(RATIO_TO_REPORT(COUNT(*)) OVER (), 4),
    ROUND(SUM(paid_amount), 2)
FROM mart.fct_claim_line
WHERE is_current_version
GROUP BY member_resolution_status
ORDER BY fact_table, dimension_table, orphan_rows DESC;

-- ---------------------------------------------------------------------------
-- Grain uniqueness on BUSINESS keys. Stated plainly because it is the most
-- common mistake in a data quality suite: a uniqueness test on a surrogate
-- key is worthless. It passes by construction.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW audit.vw_grain_uniqueness AS
SELECT 'stg.clm__claim_line' AS object_name,
       'claim_number + claim_line_number + adjudication_seq + net_sign' AS business_key,
       COUNT(*) - COUNT(DISTINCT claim_number || '|' || claim_line_number || '|'
                        || adjudication_seq || '|' || net_sign) AS violations,
       'EXPECTED' AS severity,
       'A re-driven extract duplicated one day of lines. The SURROGATE key is '
       || 'still unique, so a primary-key test passes.' AS note
FROM stg.clm__claim_line
UNION ALL
SELECT 'mart.fct_claim_line',
       'claim_number + claim_line_number + adjudication_seq + net_sign',
       COUNT(*) - COUNT(DISTINCT claim_number || '|' || claim_line_number || '|'
                        || adjudication_seq || '|' || net_sign),
       'ERROR',
       'Must be zero after de-duplication.'
FROM mart.fct_claim_line
UNION ALL
SELECT 'mart.fct_member_month', 'member_id + year_month',
       COUNT(*) - COUNT(DISTINCT member_id || '|' || year_month),
       'ERROR', 'The only sanctioned PMPM denominator. One row per member-month.'
FROM mart.fct_member_month;

-- ---------------------------------------------------------------------------
-- Reconciliation assertions. These must tie to the penny.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW audit.vw_reconciliation_checks AS
SELECT 'allowed = paid + deductible + copay + coinsurance + cob' AS check_name,
       COUNT(*) AS violations, 'ERROR' AS severity
FROM mart.fct_claim_line
WHERE ABS(allowed_amount - (paid_amount + deductible_amount + copay_amount
                            + coinsurance_amount + cob_amount)) > 0.005
UNION ALL
SELECT 'billed >= allowed', COUNT(*), 'ERROR'
FROM mart.fct_claim_line
WHERE ABS(billed_amount) < ABS(allowed_amount) - 0.011
UNION ALL
SELECT 'header total paid = SUM(line paid) per claim version', COUNT(*), 'ERROR'
FROM (
    SELECT l.claim_number, l.adjudication_seq,
           SUM(l.paid_amount) AS line_paid,
           MAX(TRY_TO_NUMBER(h.total_claim_paid_amount, 12, 2)) AS header_paid
    FROM mart.fct_claim_line l
    JOIN raw_clm.clm_claim_header h
      ON h.claim_number = l.claim_number
     AND TRY_TO_NUMBER(h.adjudication_seq) = l.adjudication_seq
    GROUP BY l.claim_number, l.adjudication_seq
    HAVING ABS(SUM(l.paid_amount)
               - MAX(TRY_TO_NUMBER(h.total_claim_paid_amount, 12, 2))) > 0.011
)
UNION ALL
-- The two sanctioned nettings. Note there is NO reversal exclusion in the
-- second: orphan reversals are current AND negative on purpose, so excluding
-- them breaks the tie. That is exactly why this check and the orphan-reversal
-- anomaly are paired.
SELECT 'both nettings agree: all rows vs is_current_version',
       IFF(ABS(
           (SELECT SUM(paid_amount) FROM mart.fct_claim_line)
         - (SELECT SUM(paid_amount) FROM mart.fct_claim_line WHERE is_current_version)
       ) > 1.00, 1, 0),
       'ERROR';

-- ---------------------------------------------------------------------------
-- Conformance coverage. Every distinct source value in a coded column must
-- have a mapping. This check generalizes to client work better than anything
-- else here, and it is cheap: one query per coded column.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW audit.vw_conformance_coverage AS
SELECT
    'ehr_encounter.encounter_type_source' AS coded_column,
    e.encounter_type_source               AS source_value,
    COUNT(*)                              AS rows,
    IFF(m.source_value IS NULL, 'NO MAPPING', 'mapped') AS status
FROM raw_ehr.ehr_encounter e
LEFT JOIN raw_ref.ref_service_line_crosswalk m
       ON m.crosswalk_domain = 'EHR_DEPARTMENT'
      AND UPPER(TRIM(m.source_value)) = UPPER(TRIM(e.encounter_type_source))
GROUP BY e.encounter_type_source, status
ORDER BY status, rows DESC;

-- ---------------------------------------------------------------------------
-- The runout triangle. Measured against the SAME calendar month in prior
-- years, de-trended. Comparing an incomplete month to an annual average
-- measures seasonality and calls it completeness - December alone carries a
-- 1.45x elective-surgery factor.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW audit.vw_runout_triangle AS
WITH monthly AS (
    SELECT d.year_month_name AS service_month,
           d.calendar_year, d.calendar_month,
           SUM(l.paid_amount) AS paid
    FROM mart.fct_claim_line l
    JOIN mart.dim_date d ON d.date_key = l.service_date_key
    WHERE l.is_current_version
    GROUP BY d.year_month_name, d.calendar_year, d.calendar_month
)
SELECT
    m.service_month,
    m.paid,
    AVG(p.paid * POWER(1.068, m.calendar_year - p.calendar_year)) AS detrended_prior_year_baseline,
    ROUND(m.paid / NULLIF(AVG(p.paid * POWER(1.068, m.calendar_year - p.calendar_year)), 0), 4)
        AS observed_completeness
FROM monthly m
LEFT JOIN monthly p
       ON p.calendar_month = m.calendar_month
      AND p.calendar_year  < m.calendar_year
GROUP BY m.service_month, m.paid, m.calendar_year
ORDER BY m.service_month;
