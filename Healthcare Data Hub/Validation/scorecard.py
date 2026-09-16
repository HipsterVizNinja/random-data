#!/usr/bin/env python3
"""The provider incentive scorecard, computed from the shipped mart.

    python Validation/scorecard.py
    python Validation/scorecard.py --truncated   # cost on truncated allowed

This exists because PROVIDER_INCENTIVE_PROGRAM_PLAN.md §15 carried a scorecard
produced by two throwaway analysis scripts that were never committed. §18 said
so itself and said they should become assertions. They were not, the dataset was
rebuilt, and every figure in §15 went stale with nothing to catch it.

So the scorecard lives here now, implementing §10 exactly: five measures, a
three-tier gate against the peer distribution, points weighted by attributed
member-months, and a fixed pool.

Nothing here is a Sigma substitute. It is the reference implementation the
workbook has to reproduce, and the thing that fails when the data moves under
the plan.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Generators"))
import config as C  # noqa: E402

MART = ROOT / "Mart"
RAW = ROOT / "Source Data"

POOL = 4_200_000.0
WINDOW = (202501, 202509)          # PY2025 YTD, every month runout-complete
DM2_PREFIX = "E11"
A1C_CPT = "83036"

# measure -> (points, lower_is_better)
MEASURES = {
    "cost_ae":      (25, True),
    "ed_per_1000":  (10, True),
    "a1c_rate":     (30, False),
    "true_oon":     (25, True),
    "no_show":      (10, True),
}


def read(name: str, **kw) -> pd.DataFrame:
    return pd.read_csv(MART / f"{name}.csv.gz", low_memory=False, **kw)


def _bool(s: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(s):
        return s.fillna(False)
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "t", "yes"])


# --------------------------------------------------------------- the measures

def build_scorecard(cost_column: str) -> pd.DataFrame:
    lo, hi = WINDOW
    att = read("vbc_attribution_month")
    att = att[att["year_month"].between(lo, hi)
              & (att["attribution_status"] == "ATTRIBUTED")]
    member = read("dim_member", usecols=["member_id", "member_durable_key"])
    dur = member.drop_duplicates("member_id").set_index("member_id")[
        "member_durable_key"]
    att = att.assign(member_durable_key=att["member_id"].map(dur))

    groups = att.groupby("attributed_site_code").agg(
        member_months=("member_months", "sum"),
        members=("member_id", "nunique"))
    groups["member_years"] = groups["member_months"] / 12

    # ---- cost: actual against a risk-adjusted expectation.
    #
    # Expected is benchmark PMPM x the member's risk relative to the roster mean
    # for that book and month, which is §10's "Benchmark x member risk / LOB
    # mean risk". Now that risk scores normalize to a book mean of 1.0, that
    # ratio finally means what it says.
    bench = read("vbc_benchmark")[
        ["year_month", "line_of_business", "benchmark_pmpm", "mean_risk_score"]]
    a = att.merge(bench, on=["year_month", "line_of_business"], how="left")
    a["expected_allowed"] = (
        a["benchmark_pmpm"] * (a["risk_score"] / a["mean_risk_score"])
        * a["member_months"])

    lines = read("fct_claim_line", usecols=[
        "member_id", "member_durable_key", "service_year_month",
        "allowed_amount", "allowed_amount_truncated", "is_current_version"])
    lines = lines[_bool(lines["is_current_version"])]

    # Cost joins on MEMBER_ID, not the durable key.
    #
    # The roster is keyed by member_id and the over-match collapses 16 people
    # onto a shared durable key, so joining cost on the durable key hands the
    # same spend to both member IDs and inflates the attributed total by
    # $1,576,432 across eleven of the twelve groups. In a payout model that is
    # not a curiosity, it is a wrong cheque.
    #
    # The durable key is the right join for CLINICAL data, where the EHR has
    # its own identifiers and resolution is the only way across. For money it
    # is the wrong one: member_id IS the payer's key, the claims carry it, and
    # it needs no resolution to be exact. Use the source key where the source
    # key is authoritative.
    spend = lines.groupby(["member_id", "service_year_month"])[cost_column].sum()
    a["actual_allowed"] = spend.reindex(
        list(zip(a["member_id"], a["year_month"]))).fillna(0).to_numpy()
    cost = a.groupby("attributed_site_code")[
        ["actual_allowed", "expected_allowed"]].sum()
    groups = groups.join(cost)
    groups["cost_ae"] = groups["actual_allowed"] / groups["expected_allowed"]
    groups["allowed_pmpm"] = groups["actual_allowed"] / groups["member_months"]

    # ---- utilization: ED visits by the members the group is accountable for,
    # wherever the visit happened. That is the whole point of a risk contract.
    enc = read("fct_encounter", usecols=[
        "member_durable_key", "encounter_date", "encounter_type_conformed"])
    enc["year_month"] = pd.to_datetime(
        enc["encounter_date"]).dt.strftime("%Y%m").astype(int)
    enc = enc[enc["year_month"].between(lo, hi)]
    panel = att[["member_durable_key", "year_month", "attributed_site_code"]]
    ed = enc[enc["encounter_type_conformed"] == "EMERGENCY"].merge(
        panel, on=["member_durable_key", "year_month"], how="inner")
    groups["ed_visits"] = ed.groupby("attributed_site_code").size()
    groups["ed_visits"] = groups["ed_visits"].fillna(0)
    groups["ed_per_1000"] = 1000 * groups["ed_visits"] / groups["member_years"]

    # ---- quality: the documented two-source union.
    groups = groups.join(_a1c(att, lines.index, lo, hi))

    # ---- network integrity: destination status AS OF the placed date.
    groups = groups.join(_network(lo, hi))

    # ---- access.
    groups = groups.join(_no_show(lo, hi))

    fac = read("dim_facility", usecols=["site_code", "facility_name"])
    groups = groups.join(fac.set_index("site_code")["facility_name"])
    return groups.reset_index().rename(columns={"index": "attributed_site_code"})


def _a1c(att: pd.DataFrame, _unused, lo: int, hi: int) -> pd.DataFrame:
    """Diabetic denominator and A1c testing rate, both as documented unions.

    Neither source is a superset of the other, so the union is the measure and
    the rule is written down rather than implied. External-lab orders that
    returned NO_STRUCTURED_RESULT still count as TESTED - the test happened -
    which is why the controlled rate has a different denominator and is
    reported but never scored.
    """
    panel = att[["member_durable_key", "attributed_site_code"]].drop_duplicates(
        "member_durable_key").set_index("member_durable_key")[
        "attributed_site_code"]

    # Diabetic: claim-side header diagnoses unioned with encounter-side.
    ch = read("fct_claim_header", usecols=[
        "claim_number", "member_durable_key", "service_year_month"])
    ch = ch[ch["service_year_month"].between(lo, hi)]
    bc = read("br_claim_diagnosis", usecols=["claim_number", "icd10_code"])
    bc = bc[bc["icd10_code"].astype(str).str.startswith(DM2_PREFIX)]
    dm_claim = set(ch.merge(bc, on="claim_number")["member_durable_key"])

    enc = read("fct_encounter", usecols=[
        "encounter_id", "member_durable_key", "encounter_date"])
    enc["ym"] = pd.to_datetime(enc["encounter_date"]).dt.strftime("%Y%m").astype(int)
    enc = enc[enc["ym"].between(lo, hi)]
    be = read("br_encounter_diagnosis", usecols=["encounter_id", "icd10_code"])
    be = be[be["icd10_code"].astype(str).str.startswith(DM2_PREFIX)]
    dm_enc = set(enc.merge(be, on="encounter_id")["member_durable_key"])
    diabetic = (dm_claim | dm_enc) & set(panel.index)

    # Tested: EHR lab result unioned with the claim-side CPT.
    lab = read("fct_lab_result", usecols=["encounter_id", "lab_code",
                                          "lab_name", "result_status"])
    lab = lab[lab["lab_name"].astype(str).str.upper().str.contains("HBA1C")]
    lab = lab.merge(enc[["encounter_id", "member_durable_key"]],
                    on="encounter_id", how="inner")
    tested_lab = set(lab["member_durable_key"])

    cl = read("fct_claim_line", usecols=[
        "member_durable_key", "service_year_month", "procedure_code",
        "is_current_version"])
    cl = cl[_bool(cl["is_current_version"])
            & cl["service_year_month"].between(lo, hi)
            & (cl["procedure_code"].astype(str) == A1C_CPT)]
    tested_claim = set(cl["member_durable_key"])
    tested = (tested_lab | tested_claim) & diabetic

    d = pd.Series({m: panel.get(m) for m in diabetic}).rename("site")
    t = pd.Series({m: panel.get(m) for m in tested}).rename("site")
    out = pd.DataFrame({
        "diabetic_denominator": d.value_counts(),
        "a1c_tested": t.value_counts(),
    }).fillna(0)
    out["a1c_rate"] = out["a1c_tested"] / out["diabetic_denominator"]
    return out


def _network(lo: int, hi: int) -> pd.DataFrame:
    """True out-of-network rate, contract joined as of the PLACED date.

    The EHR pick-list is carried alongside as evidence of belief, never of
    fact. The gap between them is the governance exposure.
    """
    R = read("fct_referral", usecols=[
        "referral_id", "referring_site_code", "placed_date",
        "destination_site_code", "destination_status_per_ehr_directory"])
    R = R.assign(ym=pd.to_datetime(R["placed_date"]).dt.strftime("%Y%m").astype(int))
    R = R[R["ym"].between(lo, hi)]
    R["placed"] = pd.to_datetime(R["placed_date"])

    nc = pd.read_csv(RAW / "raw_ref" / "ref_network_contract.csv.gz")
    nc["eff"] = pd.to_datetime(nc["effective_date"])
    # 9999-12-31 is out of range for a pandas Timestamp, so the open-ended
    # contracts have to be recognized rather than coerced.
    exp = nc["expiration_date"].astype(str)
    nc["exp"] = pd.to_datetime(exp.where(~exp.str.startswith("9999"),
                                         "2099-12-31"), format="%Y-%m-%d")
    j = R.merge(nc[["site_code", "network_status", "eff", "exp"]],
                left_on="destination_site_code", right_on="site_code", how="left")
    j = j[(j["placed"] >= j["eff"]) & (j["placed"] <= j["exp"])]
    j = j.drop_duplicates("referral_id")

    g = j.groupby("referring_site_code")
    out = pd.DataFrame({
        "referrals_placed": g.size(),
        "true_oon": g.apply(
            lambda x: (x["network_status"] == "NONPAR").mean(), include_groups=False),
        "ehr_oon": g.apply(
            lambda x: (x["destination_status_per_ehr_directory"] == "NONPAR").mean(),
            include_groups=False),
    })
    out["directory_gap"] = out["true_oon"] - out["ehr_oon"]
    return out


def _no_show(lo: int, hi: int) -> pd.DataFrame:
    ap = pd.read_csv(RAW / "raw_pm" / "pm_appointment.csv.gz")
    ap["ym"] = pd.to_datetime(ap["appointment_date"]).dt.strftime("%Y%m").astype(int)
    ap = ap[ap["ym"].between(lo, hi) & (ap["appointment_status"] != "SCHEDULED")]
    g = ap.groupby("site_code")
    return pd.DataFrame({
        "no_show": g.apply(lambda x: (x["appointment_status"] == "NO_SHOW").mean(),
                           include_groups=False),
    })


# ---------------------------------------------------------------- the scoring

def gate(values: pd.Series, points: int, lower_is_better: bool) -> pd.Series:
    """Three-tier gate against the peer distribution, exactly as §10 states.

    Zero at the 25th percentile of performance, 60% of points at the peer mean,
    full points at the 75th. Linear between. Peer-relative by construction, so
    a uniform rescaling of the underlying measure - a risk-score normalization,
    for instance - moves scores only through the shape of the distribution.
    """
    v = values.astype(float)
    best = v.quantile(0.25) if lower_is_better else v.quantile(0.75)
    worst = v.quantile(0.75) if lower_is_better else v.quantile(0.25)
    mean = v.mean()
    out = []
    for x in v:
        better_than_mean = (x <= mean) if lower_is_better else (x >= mean)
        beyond_best = (x <= best) if lower_is_better else (x >= best)
        beyond_worst = (x >= worst) if lower_is_better else (x <= worst)
        if beyond_best:
            p = points
        elif beyond_worst:
            p = 0.0
        elif better_than_mean:
            span = (mean - best) if lower_is_better else (best - mean)
            frac = 0.0 if span == 0 else (
                (mean - x) / span if lower_is_better else (x - mean) / span)
            p = points * (0.60 + 0.40 * frac)
        else:
            span = (worst - mean) if lower_is_better else (mean - worst)
            frac = 0.0 if span == 0 else (
                (worst - x) / span if lower_is_better else (x - worst) / span)
            p = points * 0.60 * frac
        out.append(round(min(max(p, 0.0), points), 4))
    return pd.Series(out, index=v.index)


def score(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for m, (pts, lower) in MEASURES.items():
        df[f"pts_{m}"] = gate(df[m], pts, lower)
    df["composite"] = df[[f"pts_{m}" for m in MEASURES]].sum(axis=1)
    df["weighted_share"] = df["composite"] * df["member_months"]
    df["payout"] = POOL * df["weighted_share"] / df["weighted_share"].sum()
    df["payout_per_member"] = df["payout"] / df["members"]
    return df.sort_values("composite", ascending=False).reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--truncated", action="store_true",
                    help="score cost on high-cost-truncated allowed")
    ap.add_argument("--ehr-oon", action="store_true",
                    help="score network integrity on the EHR pick-list instead "
                         "of the as-of contract join - the WRONG answer, "
                         "computed so the rank inversion can be measured")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    col = "allowed_amount_truncated" if args.truncated else "allowed_amount"
    base = build_scorecard(col)
    if args.ehr_oon:
        base = base.assign(true_oon=base["ehr_oon"])
    df = score(base)
    df.insert(0, "rank", np.arange(1, len(df) + 1))

    print(f"\nProvider incentive scorecard - PY2025 YTD "
          f"({WINDOW[0]} to {WINDOW[1]}), pool ${POOL:,.0f}")
    print(f"Cost measure on {'TRUNCATED' if args.truncated else 'RAW'} allowed"
          + ("  |  network integrity on the EHR PICK-LIST (the wrong answer)"
             if args.ehr_oon else "") + "\n")
    show = df[["rank", "facility_name", "member_months", "cost_ae",
               "ed_per_1000", "a1c_rate", "true_oon", "no_show",
               "composite", "payout"]].copy()
    show["member_months"] = show["member_months"].map("{:,.0f}".format)
    show["cost_ae"] = show["cost_ae"].map("{:.3f}".format)
    show["ed_per_1000"] = show["ed_per_1000"].map("{:.1f}".format)
    for c in ("a1c_rate", "true_oon", "no_show"):
        show[c] = show[c].map("{:.1%}".format)
    show["composite"] = show["composite"].map("{:.1f}".format)
    show["payout"] = show["payout"].map("${:,.0f}".format)
    print(show.to_string(index=False))

    tot = df["actual_allowed"].sum()
    print(f"\nAttributed allowed, scored window: ${tot:,.0f}")
    print(f"Peer mean cost A/E: {df['actual_allowed'].sum() / df['expected_allowed'].sum():.3f}")
    if args.json:
        args.json.write_text(df.to_json(orient="records", indent=2))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
