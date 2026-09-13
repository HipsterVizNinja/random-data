-- Healthcare Data Hub - fact layer
--
-- The member-month build is the piece most worth reading. Everything else is
-- key resolution and typing.

USE SCHEMA healthcare_data_hub_synth;

-- ---------------------------------------------------------------------------
-- fct_member_month: the ONLY sanctioned PMPM denominator.
--
-- Never compute member-months by summing span lengths. 3.5% of members carry
-- overlapping coverage spans - COBRA running alongside active coverage, and a
-- plan change where the prior span was never terminated - and summing spans
-- double counts every one of them. Worse, the overlap is concentrated in one
-- acquired employer group, so the error is UNEVEN: that group's PMPM reads
-- about 10% better than truth. A number that is wrong unevenly is the kind
-- that survives review.
--
-- The correct denominator is the UNION of a member's coverage, which is a
-- gaps-and-islands problem:
--   1. merge overlapping or adjacent spans per member into contiguous islands
--   2. intersect each island with each calendar month
--   3. sum the intersected days
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE mart.fct_member_month AS
WITH flagged AS (
    SELECT
        member_id, plan_code, group_id, line_of_business,
        is_primary_coverage, span_start_date, span_end_date,
        -- A new island starts when this span begins after EVERY prior span
        -- for that member has already ended.
        IFF(
            span_start_date > DATEADD(
                day, 1,
                MAX(span_end_date) OVER (
                    PARTITION BY member_id ORDER BY span_start_date, span_end_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                )
            ), 1, 0
        ) AS starts_new_island
    FROM stg.elig__eligibility_span
),
islanded AS (
    SELECT *,
           SUM(starts_new_island) OVER (
               PARTITION BY member_id ORDER BY span_start_date, span_end_date
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS island_id
    FROM flagged
),
islands AS (
    SELECT member_id, island_id,
           MIN(span_start_date) AS island_start,
           MAX(span_end_date)   AS island_end
    FROM islanded
    GROUP BY member_id, island_id
),
months AS (
    SELECT DISTINCT
           year_month,
           year_month_name,
           DATE_TRUNC('month', full_date)                       AS month_start,
           LAST_DAY(full_date)                                  AS month_end,
           DAY(LAST_DAY(full_date))                             AS days_in_month
    FROM mart.dim_date
    WHERE is_in_source_window
),
covered AS (
    SELECT
        i.member_id,
        m.year_month,
        m.year_month_name,
        m.days_in_month,
        LEAST(
            SUM(DATEDIFF(day,
                         GREATEST(i.island_start, m.month_start),
                         LEAST(i.island_end,   m.month_end)) + 1),
            m.days_in_month
        ) AS eligible_days
    FROM islands i
    JOIN months m
      ON i.island_start <= m.month_end
     AND i.island_end   >= m.month_start
    GROUP BY i.member_id, m.year_month, m.year_month_name, m.days_in_month
),
-- A member who changes plan or group mid-month is attributed to whichever
-- they held for the most days. Without this tie-break the grain silently
-- doubles at every benefit-year boundary.
attributed AS (
    SELECT member_id, year_month, plan_code, group_id, line_of_business
    FROM (
        SELECT
            s.member_id, m.year_month, s.plan_code, s.group_id,
            s.line_of_business,
            ROW_NUMBER() OVER (
                PARTITION BY s.member_id, m.year_month
                ORDER BY IFF(s.is_primary_coverage, 0, 1),
                         DATEDIFF(day,
                                  GREATEST(s.span_start_date, m.month_start),
                                  LEAST(s.span_end_date,   m.month_end)) DESC
            ) AS rn
        FROM stg.elig__eligibility_span s
        JOIN months m
          ON s.span_start_date <= m.month_end
         AND s.span_end_date   >= m.month_start
    )
    WHERE rn = 1
)
SELECT
    ROW_NUMBER() OVER (ORDER BY c.member_id, c.year_month) AS member_month_key,
    c.member_id,
    c.year_month,
    c.year_month_name,
    c.eligible_days,
    c.days_in_month,
    ROUND(c.eligible_days / c.days_in_month, 4)            AS member_months,
    a.plan_code,
    a.group_id,
    a.line_of_business,
    mm.risk_score,
    TRUE                                                   AS has_medical,
    TRUE                                                   AS has_rx,
    'SYNTHETIC'                                            AS data_classification
FROM covered c
LEFT JOIN attributed a ON a.member_id = c.member_id AND a.year_month = c.year_month
LEFT JOIN stg.elig__member mm ON mm.member_id = c.member_id;

-- ---------------------------------------------------------------------------
-- fct_claim_line
--
-- De-duplicated on the BUSINESS key. A uniqueness test on claim_line_key
-- would have PASSED on the raw file: a re-driven extract duplicated one day
-- of lines and the duplicates carry distinct surrogate keys. A uniqueness
-- test on a surrogate key is worthless.
--
-- Note what is NOT de-duplicated: bilateral procedures and same-day repeats
-- legitimately produce near-identical rows distinguished only by modifier
-- (50, 76, LT/RT). De-duplicating on "the obvious business columns" destroys
-- thousands of legitimate lines and UNDERSTATES paid. Modifiers are part of
-- line identity.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE mart.fct_claim_line AS
WITH deduped AS (
    SELECT l.*,
           ROW_NUMBER() OVER (
               PARTITION BY l.claim_number, l.claim_line_number,
                            l.adjudication_seq, l.net_sign
               ORDER BY l.source_load_batch_id
           ) AS dupe_rank
    FROM stg.clm__claim_line l
)
SELECT
    d.claim_line_key,
    d.claim_number, d.claim_line_number, d.adjudication_seq,
    COALESCE(mem.member_key, -1)                              AS member_key,
    mem.member_durable_key,
    d.member_id,
    IFF(mem.member_key IS NULL, 'ORPHAN_SOURCE_VALUE', 'MATCHED')
                                                              AS member_resolution_status,
    d.encounter_id,
    d.claim_type, d.claim_role, d.source_kind,
    d.service_date,
    TO_NUMBER(TO_CHAR(d.service_date, 'YYYYMMDD'))            AS service_date_key,
    TO_NUMBER(TO_CHAR(d.service_date, 'YYYYMM'))              AS service_year_month,
    d.paid_date,
    TO_NUMBER(TO_CHAR(d.paid_date, 'YYYYMMDD'))               AS paid_date_key,
    d.paid_lag_days,
    d.service_site_code, d.is_out_of_network,
    d.procedure_code, d.code_system, d.service_category,
    d.units, d.pos_code, d.revenue_code, d.modifier_1, d.modifier_2,
    d.denial_code,
    -- The servicing provider is where the orphan keys live, so its resolution
    -- status is the column that keeps that defect countable.
    COALESCE(pv.provider_key, -1)                             AS servicing_provider_key,
    CASE
        WHEN d.servicing_provider_master_id IS NULL THEN 'SOURCE_NULL'
        WHEN pv.provider_key IS NOT NULL            THEN 'MATCHED'
        ELSE 'ORPHAN_SOURCE_VALUE'
    END                                                       AS servicing_provider_resolution_status,
    d.billed_amount, d.allowed_amount, d.contractual_writeoff_amount,
    d.deductible_amount, d.copay_amount, d.coinsurance_amount, d.cob_amount,
    d.paid_amount,
    d.is_current_version, d.is_reversal, d.is_orphan_reversal, d.net_sign,
    d.original_claim_number, d.source_load_batch_id,
    'SYNTHETIC'                                               AS data_classification
FROM deduped d
LEFT JOIN mart.dim_member   mem ON mem.member_id = d.member_id
LEFT JOIN mart.dim_provider pv
       ON pv.provider_master_id = d.servicing_provider_master_id
      AND pv.is_current
WHERE d.dupe_rank = 1;

-- ---------------------------------------------------------------------------
-- fct_referral_outcome: referral to confirming event, as an auditable bridge.
--
-- Confirmation is a first-class modeled metric with a rule version on every
-- row, not ad-hoc SQL in a workbook. TWO independent confirmation sources are
-- checked - a claim and a completed appointment - because if the only
-- evidence were the claims join, the first skeptic in the room blames the
-- match rate and the finding dies.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE mart.fct_referral_outcome AS
WITH r AS (
    SELECT ro.*, x.master_person_id AS member_durable_key
    FROM stg.ehr__referral_order ro
    LEFT JOIN stg.xwalk_patient x
           ON x.source_system = 'CARELINE_EHR'
          AND x.source_patient_id = ro.mrn
),
claim_confirm AS (
    SELECT DISTINCT r.referral_id
    FROM r
    JOIN mart.fct_claim_line l
      ON l.member_durable_key = r.member_durable_key
     AND l.service_site_code  = r.destination_site_code
     AND l.service_date BETWEEN r.placed_date AND DATEADD(day, 90, r.placed_date)
),
appt_confirm AS (
    SELECT DISTINCT TRIM(referral_id) AS referral_id
    FROM raw_pm.pm_appointment
    WHERE TRIM(appointment_status) IN ('COMPLETED', 'ARRIVED')
      AND referral_id IS NOT NULL
)
SELECT
    r.referral_id,
    r.member_durable_key,
    r.referring_site_code,
    r.destination_site_code,
    r.placed_date,
    r.referral_status,
    r.days_to_closure,
    r.closure_actor_type,
    CASE
        WHEN c.referral_id IS NOT NULL AND a.referral_id IS NOT NULL THEN 'BOTH'
        WHEN c.referral_id IS NOT NULL                               THEN 'CLAIM'
        WHEN a.referral_id IS NOT NULL                               THEN 'APPOINTMENT'
        ELSE 'NONE'
    END                                                   AS confirm_source,
    (c.referral_id IS NOT NULL OR a.referral_id IS NOT NULL) AS is_confirmed,
    'v1-window90d'                                        AS match_rule_version,
    CASE
        WHEN c.referral_id IS NOT NULL AND a.referral_id IS NOT NULL THEN 0.99
        WHEN c.referral_id IS NOT NULL                               THEN 0.90
        WHEN a.referral_id IS NOT NULL                               THEN 0.80
        ELSE 0.00
    END                                                   AS confidence,
    'SYNTHETIC'                                           AS data_classification
FROM r
LEFT JOIN claim_confirm c ON c.referral_id = r.referral_id
LEFT JOIN appt_confirm  a ON a.referral_id = r.referral_id;
