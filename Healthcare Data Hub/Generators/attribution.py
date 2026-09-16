"""ACO attribution roster, its version history, restatements, and contracts.

Attribution decides whose cost counts against the risk contract, and it is
restated retroactively every month with a look-back. That makes it the second
trap in the demo and the one aimed squarely at Finance rather than at Network
Strategy.

The planted defect (anomaly A6): a few hundred high-cost members are
retro-terminated from attribution in exactly the months that contained an
inpatient stay at a non-affiliated hospital. Their cost leaves the numerator
and their member-months leave the denominator, so PMPM improves without any
care changing. Anyone measuring on the CURRENT roster sees a real-looking
improvement; only comparing roster VERSIONS reveals it.

Three things here exist so that finding survives a challenge:

1. **Every monthly roster version ships**, not just the latest. The roster is
   produced monthly and each run is a version somebody may have quoted from.
   `vbc_attribution_month` carries the current version; the restatement delta
   carries enough to reconstruct any earlier one exactly.

2. **Restatement runs in BOTH directions.** Members are retro-ADDED as well as
   retro-terminated. A restatement history that only ever removes people models
   the convenient direction and nothing else, and a reviewer is right to say so.
   The additions are drawn without reference to cost, so the net effect is an
   honest one rather than a manufactured one.

3. **The benchmark is calibrated against the ATTRIBUTED cohort**, and risk
   scores are normalized to a book mean of 1.0 within line of business, so
   `risk_adjusted_benchmark_pmpm` is a number a settlement can actually be
   computed against.

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

# Reasons a member-month is retro-ADDED to the roster. These are the ordinary
# mechanics of a retrospective attribution rule catching up with late data.
ADD_REASONS = [
    "Late-arriving primary care encounter in look-back",
    "Retroactive enrollment reinstatement",
    "Attribution appeal upheld",
]


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

    # ---- terminations: the planted cohort plus ordinary churn.
    current = ros.copy()
    key = list(zip(current["member_id"], current["year_month"]))
    retro_hit = np.array([k in retro_pairs for k in key])
    churn = (rng.random(len(current)) < ORDINARY_CHURN_RATE) & (
        current["year_month"].to_numpy() >= RESTATE_FROM_YEAR_MONTH
    )
    removed = retro_hit | churn

    term = current[removed].copy()
    term["prior_status"] = "ATTRIBUTED"
    term["new_status"] = "RETRO_TERMINATED"
    term["restatement_reason"] = np.where(
        retro_hit[removed],
        "Inpatient stay at non-affiliated facility in month",
        "Routine roster churn",
    )

    # ---- retro-ADDITIONS. Member-months that ARE on the roster today but were
    # absent from the earlier versions, because the qualifying encounter or the
    # enrollment reached the payer late.
    #
    # Drawn WITHOUT reference to cost, deliberately. Cost-targeting the
    # additions the way the terminations are targeted would manufacture a
    # second effect pointing the same way and make the whole restatement look
    # designed. Letting them fall where they fall is what makes the net figure
    # defensible: the terminations still dominate, but they have to earn it.
    eligible_add = (~removed) & (
        current["year_month"].to_numpy() >= RESTATE_FROM_YEAR_MONTH
    )
    add_idx = np.flatnonzero(eligible_add)
    n_add = min(run.n(C.RETRO_ADD_MEMBERS), len(add_idx))
    chosen_add = rng.choice(add_idx, size=n_add, replace=False) if n_add else []
    add = current.iloc[chosen_add].copy()
    add["prior_status"] = "NOT_ATTRIBUTED"
    add["new_status"] = "ATTRIBUTED"
    add["restatement_reason"] = rng.choice(ADD_REASONS, size=len(add))

    # ---- the current roster: terminations removed, additions present.
    current_kept = current[~removed].copy()
    current_kept["attribution_status"] = "ATTRIBUTED"
    current_kept["as_of_version"] = C.ROSTER_CURRENT_VERSION
    current_kept["as_of_date"] = C.ROSTER_VERSIONS[-1][1]

    # ---- stamp every restatement with the version that first applied it.
    delta = pd.concat([term, add], ignore_index=True)
    delta = _assign_versions(delta)
    delta = delta.sort_values(
        ["as_of_version", "member_id", "year_month"]
    ).reset_index(drop=True)
    delta = delta[[
        "member_id", "year_month", "year_month_name", "attributed_site_code",
        "line_of_business", "member_months", "risk_score",
        "prior_status", "new_status", "restatement_reason",
        "as_of_version", "as_of_date",
    ]]
    delta.insert(0, "restatement_key", np.arange(1, len(delta) + 1))

    out_current = current_kept[[
        "member_id", "year_month", "year_month_name", "attributed_site_code",
        "line_of_business", "member_months", "risk_score", "attribution_status",
        "as_of_version", "as_of_date",
    ]].reset_index(drop=True)
    out_current.insert(0, "attribution_month_key", np.arange(1, len(out_current) + 1))

    versions = _build_roster_versions(delta, out_current)
    benchmark = _build_benchmark(out_current)
    terms = _build_contract_terms(out_current)
    return {
        "vbc_attribution_month": out_current,
        "vbc_attribution_restatement": delta,
        "vbc_roster_version": versions,
        "vbc_benchmark": benchmark,
        "vbc_contract_terms": terms,
    }


def _assign_versions(delta: pd.DataFrame) -> pd.DataFrame:
    """Which monthly roster run first carried each restatement.

    A change to service month S surfaces in the roster produced the month
    after S at the earliest - the payer cannot restate a month before it has
    the claims and encounters for it. Everything that would fall before the
    first shipped version lands on the second, because version 1 is the
    baseline every later version is a change against.
    """
    if not len(delta):
        delta["as_of_version"] = pd.Series(dtype=int)
        delta["as_of_date"] = pd.Series(dtype=object)
        return delta
    version_month = {
        v: int(d[:4]) * 100 + int(d[5:7]) for v, d in C.ROSTER_VERSIONS
    }
    as_of_date = dict(C.ROSTER_VERSIONS)

    def first_version(ym: int) -> int:
        nxt = ym + 1 if ym % 100 < 12 else (ym // 100 + 1) * 100 + 1
        for v, vm in version_month.items():
            if v >= 2 and vm >= nxt:
                return v
        return C.ROSTER_CURRENT_VERSION

    ver = delta["year_month"].astype(int).map(first_version)
    delta = delta.copy()
    delta["as_of_version"] = ver.clip(lower=2, upper=C.ROSTER_CURRENT_VERSION)
    delta["as_of_date"] = delta["as_of_version"].map(as_of_date)
    return delta


def _build_roster_versions(delta: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """One row per monthly roster production run.

    Small on purpose. Its job is to let a workbook put an as-of control on the
    page without anyone hand-typing six dates, and to state in the data which
    version is current rather than leaving that to a MAX().
    """
    rows = []
    applied = delta.groupby("as_of_version").size().to_dict() if len(delta) else {}
    terms = (
        delta[delta.new_status == "RETRO_TERMINATED"].groupby("as_of_version").size()
        .to_dict() if len(delta) else {}
    )
    adds = (
        delta[delta.new_status == "ATTRIBUTED"].groupby("as_of_version").size()
        .to_dict() if len(delta) else {}
    )
    for v, d in C.ROSTER_VERSIONS:
        cumulative = sum(n for ver, n in applied.items() if ver <= v)
        rows.append({
            "roster_version_key": v,
            "as_of_version": v,
            "as_of_date": d,
            "version_label": f"v{v} as of {d}",
            "restatements_applied_this_version": int(applied.get(v, 0)),
            "retro_terminations_this_version": int(terms.get(v, 0)),
            "retro_additions_this_version": int(adds.get(v, 0)),
            "restatements_applied_cumulative": int(cumulative),
            "is_current_version": v == C.ROSTER_CURRENT_VERSION,
            "is_baseline_version": v == 1,
        })
    return pd.DataFrame(rows)


def _build_benchmark(roster: pd.DataFrame) -> pd.DataFrame:
    """Risk-adjusted contract benchmark PMPM by month and line of business.

    Two calibration decisions, both of which the previous version got wrong in
    ways that made the table unusable:

    **The base is the ATTRIBUTED cohort, not the book.** Attribution selects
    for care-seekers, so the attributed sub-population runs materially richer
    than the 48,000 members it is drawn from. A benchmark set on the book
    figure is not a stretch target, it is an arithmetic impossibility, and
    every group fails cost every year for a reason that has nothing to do with
    care.

    **Risk adjustment multiplies through a NORMALIZED score.** Risk scores now
    mean 1.0 for the average member of each book, so multiplying a benchmark
    PMPM by the attributed cohort's mean score says exactly what it should:
    this cohort is N% sicker than the book, so it is allowed to cost N% more.
    Multiplying through an unnormalized morbidity weight - which is what shipped
    before - produced a number with no contractual meaning in either direction.
    """
    rows = []
    key = 1
    grp = roster.groupby(
        ["year_month", "year_month_name", "line_of_business"], as_index=False
    ).agg(attributed_member_months=("member_months", "sum"),
          mean_risk_score=("risk_score", "mean"))
    for r in grp.itertuples():
        year = int(str(r.year_month)[:4])
        trend = 1.0 + C.BENCHMARK_TREND_PER_YEAR * (year - 2023)
        bench = C.BENCHMARK_BASE_PMPM[r.line_of_business] * trend
        rows.append({
            "benchmark_key": key,
            "year_month": r.year_month,
            "year_month_name": r.year_month_name,
            "line_of_business": r.line_of_business,
            "benchmark_pmpm": round(bench, 2),
            "mean_risk_score": round(float(r.mean_risk_score), 4),
            "risk_adjusted_benchmark_pmpm": round(
                bench * float(r.mean_risk_score), 2
            ),
            "attributed_member_months": round(float(r.attributed_member_months), 4),
        })
        key += 1
    return pd.DataFrame(rows)


def _build_contract_terms(roster: pd.DataFrame) -> pd.DataFrame:
    """The terms a settlement is actually computed under.

    Without this table a workbook can show that PMPM moved and cannot show
    that the CHEQUE moved, which is the only version of the finding a CFO
    acts on. Every lever here is a real one:

    - **minimum savings rate** - savings below it are treated as noise and
      pay nothing. It is the reason a 1% improvement is worth zero and a 3%
      improvement is worth millions, and it is why the restatement matters so
      much: moving PMPM across the MSR boundary is worth more than the
      arithmetic suggests.
    - **high-cost truncation** - each member's annual allowed is capped before
      the settlement runs, so one catastrophic case cannot decide a contract.
      This is also the honest defense against the retro-termination finding,
      and the finding has to survive it to be worth reporting.
    - **quality gate** - shared savings are earned only above a quality score.
    """
    rows = []
    mm = roster.groupby(
        [roster["year_month"] // 100, "line_of_business"]
    )["member_months"].sum()
    for (cid, cname, lob, first_year, ss, sl, msr, gate, trunc) in C.CONTRACTS:
        for year, status in sorted(C.PERFORMANCE_YEARS.items()):
            if year < first_year:
                continue
            scored_through = (
                C.IN_FLIGHT_SCORED_THROUGH if status == "IN_FLIGHT"
                else year * 100 + 12
            )
            rows.append({
                "contract_id": cid,
                "contract_name": cname,
                "line_of_business": lob,
                "performance_year": year,
                "settlement_status": status,
                "scored_through_year_month": scored_through,
                "runout_months": C.CONTRACT_RUNOUT_MONTHS,
                "minimum_savings_rate_pct": round(msr * 100, 2),
                "shared_savings_rate_pct": round(ss * 100, 2),
                "shared_loss_rate_pct": round(sl * 100, 2),
                "quality_gate_score_min": gate,
                "high_cost_truncation_threshold": trunc,
                "attributed_member_months": round(
                    float(mm.get((year, lob), 0.0)), 4),
            })
    out = pd.DataFrame(rows)
    out.insert(0, "contract_term_key", np.arange(1, len(out) + 1))
    return out
