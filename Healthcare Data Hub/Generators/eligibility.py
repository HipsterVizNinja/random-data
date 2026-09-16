"""Coverage spans, employer groups, and the member-month denominator.

Spans break at benefit-year boundaries because plans are priced by benefit
year, so a continuously covered member still has three spans across the window.

Two planted problems live here:
  - 3.5% of members carry OVERLAPPING spans, from two realistic causes: COBRA
    running alongside active coverage, and a plan change where the prior span
    was never termed.
  - The overlap is concentrated in one acquired employer group loaded under
    both its old and new group IDs. A naive span-sum therefore overstates that
    group's member-months and its PMPM looks better than truth. A wrong number
    that is wrong UNEVENLY is the kind that survives review.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

import config as C

BENEFIT_YEARS = (2023, 2024, 2025)

# The acquisition. Both group IDs are live in the enrollment feed for part of
# 2024, which is the realistic mechanism behind the duplicate spans.
ACQUIRED_GROUP_OLD = "KELL-4471"
ACQUIRED_GROUP_NEW = "NLK-KELL-01"
ACQUISITION_DATE = date(2024, 4, 1)

OVERLAP_RATE = 0.035

# Employer groups, now carrying the two attributes an ASO book cannot be built
# without: WHICH CLIENT the group belongs to, and HOW THAT CLIENT IS FUNDED.
#
# Funding is a property of the CLIENT, never of the member. Before this, every
# group had members on both the fully-insured and the self-funded plan at the
# same time, which meant "show me my self-funded book" returned a slice of
# every client instead of a set of clients. Self-funding correlates with size
# and with sector - public employers and health systems self-fund at almost any
# size, retail and hospitality mostly do not - and that is what this list
# encodes.
#
# client_id is the grain the ASO contract is written at, and it is NOT the
# group id. Kellerman is one client under two group ids either side of its
# acquisition; a book rolled up by group_id reports it as two clients and gets
# both of them wrong.
EMPLOYER_GROUPS = [
    # group_id, group_name, weight, client_id, sector, funding_type
    ("NLK-MFG-01", "Brightwater Manufacturing", 0.086, "CL-MFG",
     "MANUFACTURING", "ASO"),
    ("NLK-RET-01", "Crossroads Retail Group", 0.078, "CL-RET",
     "RETAIL", "FULLY_INSURED"),
    ("NLK-EDU-01", "Northlake Public Schools", 0.072, "CL-EDU",
     "PUBLIC_EDUCATION", "ASO"),
    ("NLK-MUN-01", "City of Northlake", 0.058, "CL-MUN",
     "PUBLIC_SECTOR", "ASO"),
    ("NLK-LOG-01", "Fairmont Logistics", 0.054, "CL-LOG",
     "TRANSPORTATION", "ASO"),
    ("NLK-TECH-01", "Sableworks Technology", 0.048, "CL-TECH",
     "TECHNOLOGY", "ASO"),
    ("NLK-FIN-01", "Harbor Trust Financial", 0.044, "CL-FIN",
     "FINANCIAL_SERVICES", "ASO"),
    ("NLK-FOOD-01", "Prairie Foods Cooperative", 0.042, "CL-FOOD",
     "FOOD_PRODUCTION", "FULLY_INSURED"),
    ("NLK-HLTH-01", "Northlake Health Partners Employees", 0.040, "CL-HLTH",
     "HEALTHCARE", "ASO"),
    ("NLK-CON-01", "Redstone Construction", 0.036, "CL-CON",
     "CONSTRUCTION", "FULLY_INSURED"),
    (ACQUIRED_GROUP_OLD, "Kellerman Industries", 0.034, "CL-KELL",
     "MANUFACTURING", "ASO"),
    ("NLK-UTIL-01", "Cornerstone Utilities", 0.030, "CL-UTIL",
     "UTILITIES", "ASO"),
    ("NLK-HOSP-01", "Lakeview Hospitality", 0.028, "CL-HOSP",
     "HOSPITALITY", "FULLY_INSURED"),
    ("NLK-PRINT-01", "Meridian Print and Packaging", 0.024, "CL-PRINT",
     "MANUFACTURING", "FULLY_INSURED"),
    ("NLK-AG-01", "Greenfield Agricultural", 0.022, "CL-AG",
     "AGRICULTURE", "FULLY_INSURED"),
    # Neither of these can be self-funded. An individual has no plan sponsor to
    # bear the risk, so the funding type is not a choice here - it is a fact.
    ("IND-MARKET", "Individual marketplace", 0.064, "CL-IND",
     "INDIVIDUAL", "FULLY_INSURED"),
    ("MA-INDIVIDUAL", "Medicare Advantage individual enrollment", 0.240,
     "CL-MAIND", "INDIVIDUAL", "FULLY_INSURED"),
]

# Client-level attributes that belong to the enrollment system's view of the
# client rather than to the ASO contract: who broke the account, when they
# joined, and the month the contract re-prices. The renewal month is the one
# that bites. Coverage spans break at CALENDAR year boundaries because plan
# design is priced by calendar benefit year, but two of these clients renew
# off-cycle, so their contract year and their benefit year are different
# windows. Any measure that blends them is wrong for those two clients only,
# which is the hardest kind of wrong to notice.
CLIENT_PROFILE = {
    "CL-MFG":   {"renewal_month": 1,  "client_since": "2016-01-01", "broker": "Ashfield Benefit Advisors"},
    "CL-RET":   {"renewal_month": 1,  "client_since": "2019-01-01", "broker": "Ashfield Benefit Advisors"},
    "CL-EDU":   {"renewal_month": 7,  "client_since": "2012-07-01", "broker": "Cardinal Risk Partners"},
    "CL-MUN":   {"renewal_month": 10, "client_since": "2014-10-01", "broker": "Cardinal Risk Partners"},
    "CL-LOG":   {"renewal_month": 1,  "client_since": "2018-01-01", "broker": "Ashfield Benefit Advisors"},
    "CL-TECH":  {"renewal_month": 1,  "client_since": "2021-01-01", "broker": "Wexler Group"},
    "CL-FIN":   {"renewal_month": 1,  "client_since": "2017-01-01", "broker": "Wexler Group"},
    "CL-FOOD":  {"renewal_month": 1,  "client_since": "2020-01-01", "broker": "Cardinal Risk Partners"},
    "CL-HLTH":  {"renewal_month": 1,  "client_since": "2011-01-01", "broker": "direct"},
    "CL-CON":   {"renewal_month": 1,  "client_since": "2022-01-01", "broker": "Wexler Group"},
    "CL-KELL":  {"renewal_month": 1,  "client_since": "2015-01-01", "broker": "Ashfield Benefit Advisors"},
    "CL-UTIL":  {"renewal_month": 1,  "client_since": "2013-01-01", "broker": "Cardinal Risk Partners"},
    "CL-HOSP":  {"renewal_month": 1,  "client_since": "2021-01-01", "broker": "Wexler Group"},
    "CL-PRINT": {"renewal_month": 1,  "client_since": "2019-01-01", "broker": "Ashfield Benefit Advisors"},
    "CL-AG":    {"renewal_month": 1,  "client_since": "2020-01-01", "broker": "Cardinal Risk Partners"},
    "CL-IND":   {"renewal_month": 1,  "client_since": "2014-01-01", "broker": "n/a"},
    "CL-MAIND": {"renewal_month": 1,  "client_since": "2013-01-01", "broker": "n/a"},
}

CLIENT_NAME = {
    "CL-MFG": "Brightwater Manufacturing",
    "CL-RET": "Crossroads Retail Group",
    "CL-EDU": "Northlake Public Schools",
    "CL-MUN": "City of Northlake",
    "CL-LOG": "Fairmont Logistics",
    "CL-TECH": "Sableworks Technology",
    "CL-FIN": "Harbor Trust Financial",
    "CL-FOOD": "Prairie Foods Cooperative",
    "CL-HLTH": "Northlake Health Partners Employees",
    "CL-CON": "Redstone Construction",
    "CL-KELL": "Kellerman Industries",
    "CL-UTIL": "Cornerstone Utilities",
    "CL-HOSP": "Lakeview Hospitality",
    "CL-PRINT": "Meridian Print and Packaging",
    "CL-AG": "Greenfield Agricultural",
    "CL-IND": "Individual marketplace",
    "CL-MAIND": "Medicare Advantage individual enrollment",
}

FUNDING_BY_GROUP = {g: f for g, _, _, _, _, f in EMPLOYER_GROUPS}
FUNDING_BY_GROUP[ACQUIRED_GROUP_NEW] = "ASO"
CLIENT_BY_GROUP = {g: c for g, _, _, c, _, _ in EMPLOYER_GROUPS}
CLIENT_BY_GROUP[ACQUIRED_GROUP_NEW] = "CL-KELL"
SECTOR_BY_GROUP = {g: s for g, _, _, _, s, _ in EMPLOYER_GROUPS}
SECTOR_BY_GROUP[ACQUIRED_GROUP_NEW] = "MANUFACTURING"

SELF_FUNDED_CLIENTS = sorted(
    {c for _, _, _, c, _, f in EMPLOYER_GROUPS if f == "ASO"}
)


def _size_tier(weight: float) -> str:
    """Enrollment size band. The ASO fee curve is priced off this."""
    if weight >= 0.070:
        return "LARGE"
    if weight >= 0.040:
        return "MID"
    return "SMALL"


def build_employer_groups() -> pd.DataFrame:
    rows = []
    for g, n, w, client, sector, funding in EMPLOYER_GROUPS:
        prof = CLIENT_PROFILE[client]
        rows.append({
            "group_id": g,
            "group_name": n,
            "client_id": client,
            "client_name": CLIENT_NAME[client],
            "enrollment_weight": w,
            "funding_type": funding,
            "sector": sector,
            "size_tier": _size_tier(w),
            "renewal_month": prof["renewal_month"],
            "client_since_date": prof["client_since"],
            "broker_name": prof["broker"],
            "is_acquired": g == ACQUIRED_GROUP_OLD,
        })
    prof = CLIENT_PROFILE["CL-KELL"]
    rows.append({
        "group_id": ACQUIRED_GROUP_NEW,
        "group_name": "Kellerman Industries (post-acquisition)",
        "client_id": "CL-KELL",
        "client_name": CLIENT_NAME["CL-KELL"],
        # Zero, because enrollment is drawn against the OLD id and migrated at
        # the acquisition date. A weight here would double-count the client.
        "enrollment_weight": 0.0,
        "funding_type": "ASO",
        "sector": "MANUFACTURING",
        "size_tier": _size_tier(0.034),
        "renewal_month": prof["renewal_month"],
        "client_since_date": prof["client_since"],
        "broker_name": prof["broker"],
        "is_acquired": True,
    })
    return pd.DataFrame(rows)


def build_eligibility(
    run: C.RunConfig, members: pd.DataFrame, plans: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    rng = run.rng("eligibility")
    n = len(members)

    # ---- assign an employer group, ONCE PER HOUSEHOLD
    #
    # Per household, not per member, and the difference is not cosmetic. An
    # employer group enrolls an EMPLOYEE; the spouse and children come with
    # the contract. Drawing the group per member - which this did until the
    # ASO layer was built on top of it - puts a subscriber in one employer's
    # plan and their child in another's, which cannot happen and which breaks
    # every household-grain measure downstream:
    #
    #   - a contract-month, the PEPM denominator, has no coherent group
    #   - one family's claims split across two employers' settlements
    #   - coverage tier is uncountable, because the family is not in one place
    #
    # It was invisible while every measure was at member grain. It surfaced
    # the moment something needed to count CONTRACTS: of the 33 over-matched
    # identity pairs, all 33 share a subscriber and only 2 shared a group.
    #
    # Medicare Advantage members are not on an employer plan at all, so they
    # route to individual enrollment regardless of the household draw.
    comm_groups = [
        (g, w) for g, _, w, _, _, _ in EMPLOYER_GROUPS if g != "MA-INDIVIDUAL"
    ]
    cg_ids = [g for g, _ in comm_groups]
    cg_w = np.array([w for _, w in comm_groups]); cg_w = cg_w / cg_w.sum()
    subscriber = members["subscriber_id"].to_numpy()
    households, hh_index = np.unique(subscriber, return_inverse=True)
    n_hh = len(households)
    # The weight now governs the share of CONTRACTS rather than the share of
    # lives, which is how a book of business is actually sized. Member counts
    # still land in proportion, because family size is drawn independently of
    # the group.
    hh_group = rng.choice(cg_ids, size=n_hh, p=cg_w)
    group_id = np.where(
        members["line_of_business"].to_numpy() == "MEDICARE_ADVANTAGE",
        "MA-INDIVIDUAL",
        hh_group[hh_index],
    )

    # ---- plan choice, constrained by how the GROUP is funded
    #
    # A member cannot elect a self-funded plan from a fully-insured sponsor,
    # and vice versa: the plan is the sponsor's, not the member's. The draw is
    # therefore made within the group's funding type rather than across all
    # three commercial products. The insured pair keeps its original 52/27
    # split, renormalized to the two products that remain available.
    #
    # Self-funded sponsors here offer ONE plan design. That is a scope
    # decision, not an oversight: adjudication in this dataset splits member
    # liability by a benefit-year reset curve rather than by an accumulator
    # against a real deductible, so a second self-funded plan design would be
    # a label with no economics behind it. Named in the ASO plan document.
    # The election is the SUBSCRIBER's and it covers the whole family, so the
    # insured product is drawn per household too. A family split across a
    # standard and a high-deductible plan is not an election anybody can make.
    funding = np.array([FUNDING_BY_GROUP[g] for g in group_id])
    ma_products = ["MMA-HMO", "MMA-DSNP"]
    insured_products = ["MHMO", "MHMO-HD"]
    hh_insured = rng.choice(insured_products, size=n_hh, p=[0.658, 0.342])
    base_product = np.where(
        members["line_of_business"].to_numpy() == "MEDICARE_ADVANTAGE",
        rng.choice(ma_products, size=n, p=[0.86, 0.14]),
        np.where(funding == "ASO", "MHMO-ASO", hh_insured[hh_index]),
    )

    # ---- enrollment and disenrollment. Most members span the full window.
    starts, ends = [], []
    for i in range(n):
        if rng.random() < 0.80:
            s = C.SOURCE_START
        else:
            # Mid-window new hires, spread across the three years.
            s = C.SOURCE_START + timedelta(days=int(rng.integers(1, 1000)))
        if rng.random() < 0.88:
            e = C.SOURCE_END
        else:
            span_days = (C.SOURCE_END - s).days
            e = s + timedelta(days=int(rng.integers(180, max(200, span_days))))
            e = min(e, C.SOURCE_END)
        starts.append(s)
        ends.append(e)

    overlap_pick = _choose_overlap_members(rng, members, group_id)

    rows = []
    key = 1
    for i in range(n):
        mem = members.iloc[i]
        member_start, member_end = starts[i], ends[i]
        lob = mem["line_of_business"]
        gid = group_id[i]
        product = base_product[i]

        for year in BENEFIT_YEARS:
            y_start = max(member_start, date(year, 1, 1))
            y_end = min(member_end, date(year, 12, 31))
            if y_start > y_end:
                continue
            # Kellerman members move to the new group ID at acquisition.
            eff_group = gid
            if gid == ACQUIRED_GROUP_OLD and y_end >= ACQUISITION_DATE:
                eff_group = ACQUIRED_GROUP_NEW
            plan_code = f"{product}-{year}"
            rows.append({
                "eligibility_span_key": key,
                "member_id": mem["member_id"],
                "subscriber_id": mem["subscriber_id"],
                "group_id": eff_group,
                "plan_code": plan_code,
                "line_of_business": lob,
                "span_start_date": y_start.isoformat(),
                "span_end_date": y_end.isoformat(),
                "coverage_type": "MEDICAL_RX",
                "is_primary_coverage": True,
                "has_medical": True,
                "has_rx": True,
                "overlap_reason": None,
            })
            key += 1

        # ---- planted overlaps
        reason = overlap_pick.get(i)
        if reason == "NEVER_TERMED_GROUP_CHANGE":
            # The acquisition: the OLD group ID span was never terminated, so
            # it runs on in parallel with the new one for the rest of 2024.
            rows.append({
                "eligibility_span_key": key,
                "member_id": mem["member_id"],
                "subscriber_id": mem["subscriber_id"],
                "group_id": ACQUIRED_GROUP_OLD,
                "plan_code": f"{product}-2024",
                "line_of_business": lob,
                "span_start_date": ACQUISITION_DATE.isoformat(),
                # Never terminated means never terminated: it runs to the end
                # of the member's coverage, not tidily to year end.
                "span_end_date": member_end.isoformat(),
                "coverage_type": "MEDICAL_RX",
                "is_primary_coverage": False,
                "has_medical": True,
                "has_rx": True,
                "overlap_reason": "Prior group span never terminated at acquisition",
            })
            key += 1
        elif reason == "COBRA":
            c_start = member_end - timedelta(days=int(rng.integers(30, 120)))
            c_start = max(c_start, member_start)
            c_end = min(c_start + timedelta(days=int(rng.integers(90, 210))), C.SOURCE_END)
            rows.append({
                "eligibility_span_key": key,
                "member_id": mem["member_id"],
                "subscriber_id": mem["subscriber_id"],
                "group_id": gid,
                "plan_code": f"{product}-{c_start.year}",
                "line_of_business": lob,
                "span_start_date": c_start.isoformat(),
                "span_end_date": c_end.isoformat(),
                "coverage_type": "COBRA",
                "is_primary_coverage": False,
                "has_medical": True,
                "has_rx": True,
                "overlap_reason": "COBRA overlapping active coverage",
            })
            key += 1

    spans = pd.DataFrame(rows)
    member_months = build_member_months(spans, members)
    return {
        "eligibility_span": spans,
        "member_month": member_months,
        "employer_group": build_employer_groups(),
    }


def _choose_overlap_members(
    rng: np.random.Generator, members: pd.DataFrame, group_id: np.ndarray
) -> dict[int, str]:
    """Pick which members get overlapping spans, concentrated in the acquisition."""
    n = len(members)
    n_overlap = int(round(OVERLAP_RATE * n))
    acquired_idx = np.flatnonzero(group_id == ACQUIRED_GROUP_OLD)
    other_idx = np.flatnonzero(group_id != ACQUIRED_GROUP_OLD)

    # About a fifth of the overlap lands in the acquired group. That is
    # enough to make its PMPM read visibly better than truth while staying
    # inside the range a real enrollment feed would produce - a defect big
    # enough to matter and small enough to survive a sniff test.
    n_acq = min(len(acquired_idx), int(round(n_overlap * 0.22)))
    n_oth = max(0, n_overlap - n_acq)
    chosen: dict[int, str] = {}
    if n_acq:
        for i in rng.choice(acquired_idx, size=n_acq, replace=False):
            chosen[int(i)] = "NEVER_TERMED_GROUP_CHANGE"
    if n_oth and len(other_idx):
        for i in rng.choice(other_idx, size=min(n_oth, len(other_idx)), replace=False):
            chosen[int(i)] = "COBRA"
    return chosen


def build_member_months(spans: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    """The ONLY sanctioned PMPM denominator.

    Never compute member-months by summing span lengths: that double counts
    every overlap. The correct answer needs the UNION of a member's coverage,
    which is a gaps-and-islands problem:

      1. sort spans per member and merge anything overlapping or adjacent into
         contiguous islands (vectorized with a running max of prior end dates)
      2. intersect each island with each calendar month
      3. sum the intersected days per member-month

    Plan and group attribution is settled separately, by whichever the member
    held for the most days in that month, with primary coverage winning ties.
    Without that tie-break the grain silently doubles at every benefit-year
    boundary.
    """
    s = spans[
        ["member_id", "plan_code", "group_id", "line_of_business",
         "is_primary_coverage", "span_start_date", "span_end_date"]
    ].copy()
    s["start"] = pd.to_datetime(s["span_start_date"])
    s["end"] = pd.to_datetime(s["span_end_date"])
    s = s.sort_values(["member_id", "start", "end"]).reset_index(drop=True)

    # ---- step 1: merge into islands
    prev_max_end = s.groupby("member_id")["end"].cummax().shift(1)
    same_member = s["member_id"].eq(s["member_id"].shift(1))
    # A new island starts when this span begins after every prior span ended.
    starts_new = (~same_member) | (s["start"] > prev_max_end + pd.Timedelta(days=1))
    s["island_id"] = starts_new.cumsum()
    islands = s.groupby(["member_id", "island_id"], as_index=False).agg(
        island_start=("start", "min"), island_end=("end", "max")
    )

    # ---- step 2: intersect islands with months
    months = pd.period_range(
        pd.Timestamp(C.SOURCE_START), pd.Timestamp(C.SOURCE_END), freq="M"
    )
    m_start = pd.to_datetime([pr.start_time.date() for pr in months])
    m_end = pd.to_datetime([pr.end_time.date() for pr in months])
    m_key = np.array([int(pr.strftime("%Y%m")) for pr in months])
    m_name = np.array([pr.strftime("%Y-%m") for pr in months])
    m_days = np.array([pr.days_in_month for pr in months])

    n_i, n_m = len(islands), len(months)
    isl_start = islands["island_start"].to_numpy()[:, None]
    isl_end = islands["island_end"].to_numpy()[:, None]
    lo = np.maximum(isl_start, m_start.to_numpy()[None, :])
    hi = np.minimum(isl_end, m_end.to_numpy()[None, :])
    days = ((hi - lo).astype("timedelta64[D]").astype(int) + 1).clip(min=0)

    rows_i, rows_m = np.nonzero(days)
    cov = pd.DataFrame({
        "member_id": islands["member_id"].to_numpy()[rows_i],
        "year_month": m_key[rows_m],
        "year_month_name": m_name[rows_m],
        "days_in_month": m_days[rows_m],
        "eligible_days": days[rows_i, rows_m],
    })
    cov = cov.groupby(
        ["member_id", "year_month", "year_month_name", "days_in_month"],
        as_index=False,
    ).agg(eligible_days=("eligible_days", "sum"))
    # An island union can never exceed the month itself.
    cov["eligible_days"] = np.minimum(cov["eligible_days"], cov["days_in_month"])

    # ---- step 3: attribute plan and group by dominant days in the month
    sp_start = s["start"].to_numpy()[:, None]
    sp_end = s["end"].to_numpy()[:, None]
    lo2 = np.maximum(sp_start, m_start.to_numpy()[None, :])
    hi2 = np.minimum(sp_end, m_end.to_numpy()[None, :])
    d2 = ((hi2 - lo2).astype("timedelta64[D]").astype(int) + 1).clip(min=0)
    ri, rm = np.nonzero(d2)
    attr = pd.DataFrame({
        "member_id": s["member_id"].to_numpy()[ri],
        "year_month": m_key[rm],
        "plan_code": s["plan_code"].to_numpy()[ri],
        "group_id": s["group_id"].to_numpy()[ri],
        "line_of_business": s["line_of_business"].to_numpy()[ri],
        "priority": np.where(s["is_primary_coverage"].to_numpy()[ri], 0, 1),
        "days": d2[ri, rm],
    })
    attr = (
        attr.sort_values(
            ["member_id", "year_month", "priority", "days"],
            ascending=[True, True, True, False],
        )
        .drop_duplicates(["member_id", "year_month"], keep="first")
        .drop(columns=["priority", "days"])
    )

    grp = cov.merge(attr, on=["member_id", "year_month"], how="left")
    grp["member_months"] = (grp["eligible_days"] / grp["days_in_month"]).round(4)

    meta = members[["member_id", "risk_score", "attributed_site_code", "region"]]
    grp = grp.merge(meta, on="member_id", how="left")

    # ---- annual re-scoring. A risk score is a property of a member IN A
    # PERFORMANCE YEAR, not a fixed attribute: the book is re-run every year
    # against that year's diagnoses. Carrying one frozen score across three
    # years means the risk-adjusted benchmark cannot move for any reason, and
    # "did our population get sicker or did we just code it better" - the
    # first question any ACO finance team asks - has no answer in the data.
    year = (grp["year_month"] // 100).astype(int)
    drift = year.map(C.RISK_DRIFT_BY_YEAR).fillna(1.0).astype(float)
    grp["risk_score"] = (grp["risk_score"].astype(float) * drift).round(4)
    grp["has_medical"] = True
    grp["has_rx"] = True
    grp = grp.sort_values(["member_id", "year_month"]).reset_index(drop=True)
    grp.insert(0, "member_month_key", np.arange(1, len(grp) + 1))
    return grp
