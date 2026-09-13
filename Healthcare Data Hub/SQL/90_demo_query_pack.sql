-- Healthcare Data Hub - demo query pack
--
-- Every block pairs the NAIVE query with the CORRECT one and returns both
-- figures side by side, so the delta is the punchline rather than an
-- assertion. Run them in order during a demo; each one sets up the next.
--
-- Do not hand this file to an audience before the reveal. It gives away every
-- answer.

USE SCHEMA healthcare_data_hub_synth;

-- ===========================================================================
-- Q1. ONE SOURCE (EHR). "How are our clinic groups managing referrals?"
--
-- This is the trap being SET. The naive answer has to look good, not
-- suspicious: North Ridge posts the best closure rate and the lowest apparent
-- out-of-network rate of all twelve groups. The obvious recommendation is to
-- roll their workflow out everywhere.
-- ===========================================================================
SELECT
    referring_site_code,
    COUNT(*)                                                       AS referrals,
    ROUND(AVG(IFF(referral_status = 'CLOSED_COMPLETE', 1, 0)), 3)  AS closure_rate,
    ROUND(AVG(IFF(referral_status = 'OPEN', 1, 0)), 3)             AS open_rate,
    ROUND(AVG(IFF(destination_status_per_ehr_directory = 'NONPAR', 1, 0)), 3)
                                                                   AS apparent_oon_rate
FROM stg.ehr__referral_order
WHERE placed_date >= '2024-07-01'
GROUP BY referring_site_code
ORDER BY apparent_oon_rate;          -- North Ridge sorts FIRST. Best of twelve.

-- ===========================================================================
-- Q2. THE BREADCRUMB. Plot time-to-status before trusting any status field.
--
-- A spike at a round number is a workflow rule, not clinical behavior. This
-- is two drags from the previous view because days_to_closure is a STORED
-- column, not something you have to derive.
-- ===========================================================================
SELECT
    referring_site_code,
    IFF(placed_date >= '2024-07-01', 'after 2024-07-01', 'before') AS period,
    ROUND(AVG(IFF(days_to_closure BETWEEN 29 AND 31, 1, 0)), 3)    AS share_closing_at_day_30,
    ROUND(AVG(IFF(closure_actor_type = 'SYSTEM', 1, 0)), 3)        AS share_closed_by_system,
    COUNT(*)                                                       AS referrals
FROM stg.ehr__referral_order
WHERE referral_status = 'CLOSED_COMPLETE'
GROUP BY referring_site_code, period
ORDER BY share_closing_at_day_30 DESC;

-- The smoking gun, once you suspect the mechanism. One row.
SELECT rule_code, site_code, effective_date, rule_parameter_days,
       sets_status_to, requires_confirming_event, rule_note
FROM raw_pm.pm_referral_workflow_config
WHERE TO_BOOLEAN(requires_confirming_event) = FALSE
  AND sets_status_to IS NOT NULL;

-- ===========================================================================
-- Q3. THE REVERSAL. Measure the outcome against a CONFIRMING EVENT rather
-- than against the status field.
--
-- Two independent confirmation paths - a claim AND a completed appointment -
-- so the first skeptic in the room cannot kill the finding by blaming the
-- match rate.
-- ===========================================================================
SELECT
    o.referring_site_code,
    COUNT(*)                                                AS referrals,
    -- The naive measure, straight off the status field.
    ROUND(AVG(IFF(o.referral_status = 'CLOSED_COMPLETE', 1, 0)), 3)
                                                            AS naive_completion_rate,
    -- The correct measure, against a real event.
    ROUND(AVG(IFF(o.is_confirmed, 1, 0)), 3)                AS true_confirmation_rate,
    ROUND(AVG(IFF(o.confirm_source = 'BOTH', 1, 0)), 3)     AS confirmed_by_both_sources,
    ROUND(AVG(IFF(o.referral_status = 'CLOSED_COMPLETE', 1, 0))
          - AVG(IFF(o.is_confirmed, 1, 0)), 3)              AS the_gap
FROM mart.fct_referral_outcome o
WHERE o.placed_date >= '2024-07-01'
GROUP BY o.referring_site_code
ORDER BY the_gap DESC;               -- North Ridge sorts FIRST. Worst of twelve.

-- ===========================================================================
-- Q4. WHY THE LEAKAGE WAS INVISIBLE. As-of-service-date network status.
--
-- Current-state dimensions rewrite history. Summit Point's contract
-- terminated 2024-10-01 and the EHR referral directory still reads PAR - a
-- governance failure with a price tag, and nobody made a bad clinical
-- decision.
-- ===========================================================================
SELECT
    r.destination_site_code,
    d.referral_network_status                AS ehr_directory_says,
    d.last_maintained_date                   AS directory_last_maintained,
    c.network_status                          AS contract_says_now,
    c.effective_date                          AS contract_effective,
    c.termination_reason,
    COUNT(*)                                  AS referrals_sent
FROM stg.ehr__referral_order r
JOIN raw_ehr.ehr_provider_directory d ON d.site_code = r.destination_site_code
JOIN mart.dim_network_contract      c ON c.site_code = r.destination_site_code
                                     AND c.is_current
WHERE r.placed_date >= c.effective_date        -- sent AFTER the termination
  AND d.referral_network_status <> c.network_status
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY referrals_sent DESC;

-- ===========================================================================
-- Q5. THE JOIN THAT PUNISHES CARELESSNESS.
--
-- Is the match loss random? The unmatched population skews toward North Ridge
-- patients, so a naive inner join deletes part of the finding and
-- UNDERSTATES the leakage. The careless analyst gets a wrong answer that
-- still looks plausible, which is the worst kind.
-- ===========================================================================
SELECT * FROM audit.vw_unmatched_skew;

-- ===========================================================================
-- Q6. THE ORPHAN JOIN. Count what an inner join would DROP before running it.
-- ===========================================================================
SELECT
    'inner join to provider dimension' AS approach,
    COUNT(*)                           AS lines_kept,
    ROUND(SUM(paid_amount), 2)         AS paid_kept
FROM mart.fct_claim_line
WHERE is_current_version
  AND servicing_provider_resolution_status = 'MATCHED'
UNION ALL
SELECT 'left join, unmatched to the -1 member',
       COUNT(*), ROUND(SUM(paid_amount), 2)
FROM mart.fct_claim_line
WHERE is_current_version;

SELECT * FROM audit.vw_orphan_matrix;

-- ===========================================================================
-- Q7. REVERSAL NETTING. Three ways to get this wrong, two ways to get it
-- right, and the two right answers must tie exactly.
-- ===========================================================================
SELECT 'CORRECT: every row, net signs included' AS method,
       ROUND(SUM(paid_amount), 2) AS total_paid
FROM mart.fct_claim_line
UNION ALL
SELECT 'CORRECT: WHERE is_current_version (no reversal exclusion)',
       ROUND(SUM(paid_amount), 2)
FROM mart.fct_claim_line WHERE is_current_version
UNION ALL
SELECT 'WRONG: WHERE adjudication_seq = 1',
       ROUND(SUM(paid_amount), 2)
FROM mart.fct_claim_line WHERE adjudication_seq = 1
UNION ALL
SELECT 'WRONG: WHERE paid_amount > 0 (dropped the reversals to tidy up)',
       ROUND(SUM(paid_amount), 2)
FROM mart.fct_claim_line WHERE paid_amount > 0
UNION ALL
SELECT 'WRONG: excluded reversals from the current version',
       ROUND(SUM(paid_amount), 2)
FROM mart.fct_claim_line WHERE is_current_version AND NOT is_reversal;

-- ===========================================================================
-- Q8. PMPM. The denominator is a decision, and the wrong one is wrong
-- UNEVENLY - concentrated in a single acquired employer group whose PMPM then
-- reads about 10% better than truth.
-- ===========================================================================
WITH correct_denominator AS (
    SELECT group_id, SUM(member_months) AS member_months
    FROM mart.fct_member_month GROUP BY group_id
),
naive_denominator AS (
    -- Summing span lengths double counts every overlapping span.
    SELECT group_id,
           SUM(DATEDIFF(day, span_start_date, span_end_date) + 1) / 30.44 AS member_months
    FROM stg.elig__eligibility_span GROUP BY group_id
),
cost AS (
    SELECT mm.group_id, SUM(l.allowed_amount) AS allowed
    FROM mart.fct_claim_line l
    JOIN mart.fct_member_month mm
      ON mm.member_id = l.member_id
     AND mm.year_month = l.service_year_month
    WHERE l.is_current_version
    GROUP BY mm.group_id
)
SELECT
    c.group_id,
    ROUND(cd.member_months, 1)                         AS correct_member_months,
    ROUND(nd.member_months, 1)                         AS naive_member_months,
    ROUND(c.allowed / NULLIF(cd.member_months, 0), 2)  AS correct_pmpm,
    ROUND(c.allowed / NULLIF(nd.member_months, 0), 2)  AS naive_pmpm,
    ROUND(100 * (1 - (c.allowed / NULLIF(nd.member_months, 0))
                   / NULLIF(c.allowed / NULLIF(cd.member_months, 0), 0)), 2)
                                                       AS pct_pmpm_understated
FROM cost c
JOIN correct_denominator cd ON cd.group_id = c.group_id
JOIN naive_denominator   nd ON nd.group_id = c.group_id
ORDER BY pct_pmpm_understated DESC;

-- ===========================================================================
-- Q9. RUNOUT. Never trend an incomplete measure to its right edge.
-- ===========================================================================
SELECT * FROM audit.vw_runout_triangle ORDER BY service_month DESC LIMIT 18;

-- The same trend, done correctly: filter on the completeness flag.
SELECT d.year_month_name, ROUND(SUM(l.paid_amount), 2) AS paid
FROM mart.fct_claim_line l
JOIN mart.dim_date d ON d.date_key = l.service_date_key
WHERE l.is_current_version
  AND d.claims_runout_complete_flag       -- the guardrail
GROUP BY d.year_month_name
ORDER BY d.year_month_name;

-- ===========================================================================
-- Q10. ADMISSIONS. One inpatient stay emits one institutional claim plus
-- several professional claims, ALL carrying the same encounter_id. Counting
-- claims as admissions inflates volume several fold.
-- ===========================================================================
SELECT
    'WRONG: COUNT(*) of inpatient claims' AS method,
    COUNT(*) AS admissions
FROM raw_clm.clm_claim_header
WHERE encounter_class = 'INPATIENT' AND TO_BOOLEAN(is_current_version)
UNION ALL
SELECT 'CORRECT: COUNT(DISTINCT encounter_id)',
       COUNT(DISTINCT encounter_id)
FROM raw_clm.clm_claim_header
WHERE encounter_class = 'INPATIENT' AND TO_BOOLEAN(is_current_version);

-- ===========================================================================
-- Q11. THE OVER-MATCH. Two people wearing one identity, found in one query,
-- contaminating precisely the top-1% cost figure the demo quotes.
-- ===========================================================================
SELECT * FROM audit.vw_overmatch_candidates LIMIT 50;

-- ===========================================================================
-- Q12. THE CERTIFIED NUMBER. One leakage figure, with its denominator, its
-- as-of date, its completeness treatment, and its unmatched-population
-- footnote stated on the same row. This is what a data leader actually buys.
-- ===========================================================================
WITH scope AS (
    SELECT o.referral_id, o.referring_site_code, o.is_confirmed,
           mart.f_network_status_asof(o.destination_site_code, o.placed_date)
               AS network_status_asof_service
    FROM mart.fct_referral_outcome o
    JOIN mart.dim_date d ON d.full_date = o.placed_date
    WHERE d.claims_runout_complete_flag
      AND o.placed_date >= '2024-07-01'
)
SELECT
    COUNT(*)                                                      AS referrals_in_scope,
    ROUND(AVG(IFF(network_status_asof_service = 'NONPAR', 1, 0)), 4)
                                                                  AS certified_leakage_rate,
    'as-of 2025-12-01 crosswalk run'                              AS identity_as_of,
    'service months with complete claims runout only'             AS completeness_treatment,
    (SELECT ROUND(AVG(IFF(match_method = 'UNMATCHED', 1, 0)), 4)
     FROM stg.xwalk_patient WHERE source_system = 'CARELINE_EHR') AS unmatched_population_share,
    'unmatched records resolve to member_key -1 and are reported, not dropped'
                                                                  AS unmatched_treatment
FROM scope;
