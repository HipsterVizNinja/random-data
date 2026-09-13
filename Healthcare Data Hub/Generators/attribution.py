"""ACO attribution roster, its restatement history, and contract benchmarks.

Attribution decides whose cost counts against the risk contract, and it is
restated retroactively every month with a two-month look-back. That makes it
the second trap in the demo and the one aimed squarely at Finance rather than
at Network Strategy.

The planted defect (anomaly A6): a few hundred high-cost members are
retro-terminated from attribution in exactly the months that contained an
inpatient stay at a non-affiliated hospital. Their cost leaves the numerator
and their member-months leave the denominator, so PMPM improves without any
care changing. Anyone measuring on the CURRENT roster sees a real-looking
improvement; only comparing roster VERSIONS reveals it.

Attribution rule modeled: plurality of primary-care visits in the look-back,
retrospective, minimum one qualifying visit. That is the rule an ACO audience
will assume, and getting it wrong is an instant credibility loss.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

import config as C
import org

LOOKBACK_MONTHS = 12
RETRO_WINDOW_MONTHS = 2

# The retro-termination cohort.
RETRO_TERM_MEMBERS = 340
RESTATE_FROM_YEAR_MONTH = 202504
# Restatement churn unrelated to the planted defect: ordinary roster movement.
# Kept small deliberately: ordinary churn is real, but if it dominates the
# planted retro-terminations it dilutes the signal into noise and the PMPM
# effect disappears behind random movement.
ORDINARY_CHURN_RATE = 0.0018


def build_attribution(
    run: C.RunConfig,
    members: pd.DataFrame,
    member_months: pd.DataFrame,
    encounters: pd.DataFrame,
    claim_lines: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    rng = run.rng("attribution")

    mm = member_months[
        ["member_id", "year_month", "year_month_name", "member_months",
         "line_of_business", "risk_score", "attributed_site_code"]
    ].copy()

    # ---- attributed PCP by plurality of primary care visits in the lookback
    pcp_sites = [s for s in org.CLINIC_GROUPS if s.startswith(("PRIM", "PEDS"))]
    amb = encounters[
        (encounters.encounter_class == "AMBULATORY")
        & encounters.site_code.isin(org.CLINIC_GROUPS)
    ]
    visits = (
        amb.groupby(["member_id_truth", "site_code"], as_index=False)
        .size()
        .rename(columns={"member_id_truth": "member_id", "size": "visits"})
        .sort_values(["member_id", "visits"], ascending=[True, False])
    )
    plurality = visits.drop_duplicates("member_id", keep="first")[
        ["member_id", "site_code", "visits"]
    ].rename(columns={"site_code": "plurality_site_code"})

    ros = mm.merge(plurality, on="member_id", how="left")
    # Minimum one qualifying visit in the look-back, or the member is not
    # attributed at all. This is what makes the denominator a real decision
    # rather than "everyone with coverage".
    ros["is_attributed"] = ros["plurality_site_code"].notna()
    ros["attributed_site_code"] = np.where(
        ros["is_attributed"], ros["plurality_site_code"], None
    )
    ros = ros[ros["is_attributed"]].copy()

    # ---- identify the retro-termination cohort: high-cost members with an
    # inpatient stay at a hospital Northlake is not affiliated with.
    # Northlake owns four hospitals but is only at risk through two of them
    # for this contract, so stays at the other two are the exposure.
    affiliated = {"HOSP-RVB", "HOSP-NLK"}
    ip = encounters[
        (encounters.encounter_class == "INPATIENT")
        & ~encounters.site_code.isin(affiliated)
    ][["member_id_truth", "encounter_date"]].rename(
        columns={"member_id_truth": "member_id"}
    )
    ip["year_month"] = (
        pd.to_datetime(ip["encounter_date"]).dt.strftime("%Y%m").astype(int)
    )
    cost = (
        claim_lines[claim_lines.is_current_version]
        .groupby("member_id", as_index=False)["allowed_amount"].sum()
        .rename(columns={"allowed_amount": "total_allowed"})
    )
    cand = (
        ip.merge(cost, on="member_id", how="left")
        .sort_values("total_allowed", ascending=False)
    )
    # Only the recent window is restated, which is why the improvement shows
    # up in the most recent quarters rather than across the whole history.
    cand = cand[cand["year_month"] >= RESTATE_FROM_YEAR_MONTH]
    n_retro = run.n(RETRO_TERM_MEMBERS)
    # Sampled from the high-cost quartile rather than taken straight off the
    # top of the cost ranking. Retro-termination is not cost-targeted by
    # design - it correlates with cost because those members sought care
    # outside the network - and taking the single most expensive members
    # roughly doubles the PMPM effect into something implausibly clean.
    if len(cand):
        cutoff = cand["total_allowed"].quantile(0.75)
        pool = cand.loc[cand["total_allowed"] >= cutoff, "member_id"].drop_duplicates()
        if len(pool) > n_retro:
            retro_members = pool.sample(n=n_retro, random_state=619)
        else:
            retro_members = pool
    else:
        retro_members = pd.Series([], dtype=object)
    retro_pairs = set(
        map(tuple, cand[cand.member_id.isin(set(retro_members))][
            ["member_id", "year_month"]].drop_duplicates().to_numpy())
    )

    # ---- version 1 of the roster: what Finance saw at the time
    original = ros.copy()
    original["as_of_version"] = 1
    original["as_of_date"] = "2025-10-15"
    original["attribution_status"] = "ATTRIBUTED"

    # ---- current roster: the restatement removes the retro-terminated
    # member-months, plus ordinary churn.
    current = ros.copy()
    key = list(zip(current["member_id"], current["year_month"]))
    retro_hit = np.array([k in retro_pairs for k in key])
    churn = rng.random(len(current)) < ORDINARY_CHURN_RATE
    removed = retro_hit | churn
    current["as_of_version"] = 2
    current["as_of_date"] = "2025-12-15"
    current["attribution_status"] = np.where(
        removed, "RETRO_TERMINATED", "ATTRIBUTED"
    )
    current_kept = current[~removed].copy()

    # ---- the restatement delta table: only rows whose status changed.
    # Storing only the delta keeps this at a fraction of a fully versioned
    # history while still supporting "show me the original and the restated
    # view side by side".
    delta = current[removed].copy()
    delta["prior_status"] = "ATTRIBUTED"
    delta["new_status"] = "RETRO_TERMINATED"
    delta["restatement_reason"] = np.where(
        retro_hit[removed],
        "Inpatient stay at non-affiliated facility in month",
        "Routine roster churn",
    )
    delta = delta[[
        "member_id", "year_month", "year_month_name", "attributed_site_code",
        "prior_status", "new_status", "restatement_reason", "as_of_date",
    ]].reset_index(drop=True)
    delta.insert(0, "restatement_key", np.arange(1, len(delta) + 1))

    out_current = current_kept[[
        "member_id", "year_month", "year_month_name", "attributed_site_code",
        "line_of_business", "member_months", "risk_score", "attribution_status",
        "as_of_version", "as_of_date",
    ]].reset_index(drop=True)
    out_current.insert(0, "attribution_month_key", np.arange(1, len(out_current) + 1))

    benchmark = _build_benchmark(rng, out_current)
    return {
        "vbc_attribution_month": out_current,
        "vbc_attribution_restatement": delta,
        "vbc_benchmark": benchmark,
    }


def _build_benchmark(rng, roster: pd.DataFrame) -> pd.DataFrame:
    """Risk-adjusted contract benchmark PMPM by month and line of business.

    Risk adjusted on purpose: the first question from anyone who has worked an
    ACO contract is "is that risk adjusted", and the dataset should reward
    asking rather than having no answer.
    """
    base = {"COMMERCIAL": 545.0, "MEDICARE_ADVANTAGE": 1045.0}
    rows = []
    key = 1
    grp = roster.groupby(
        ["year_month", "year_month_name", "line_of_business"], as_index=False
    ).agg(attributed_member_months=("member_months", "sum"),
          mean_risk_score=("risk_score", "mean"))
    for r in grp.itertuples():
        year = int(str(r.year_month)[:4])
        trend = 1.0 + 0.068 * (year - 2023)
        bench = base[r.line_of_business] * trend
        rows.append({
            "benchmark_key": key,
            "year_month": r.year_month,
            "year_month_name": r.year_month_name,
            "line_of_business": r.line_of_business,
            "benchmark_pmpm": round(bench, 2),
            "mean_risk_score": round(float(r.mean_risk_score), 4),
            "risk_adjusted_benchmark_pmpm": round(
                bench * float(r.mean_risk_score) / 0.85, 2
            ),
            "attributed_member_months": round(float(r.attributed_member_months), 4),
        })
        key += 1
    return pd.DataFrame(rows)
