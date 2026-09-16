#!/usr/bin/env python3
"""The ASO book of business, computed from the shipped mart.

    python Validation/aso_book.py
    python Validation/aso_book.py --json

Every figure ASO_ADMINISTRATIVE_SERVICES_PLAN.md quotes comes from here. It is
committed for the reason Validation/scorecard.py is committed: the provider
incentive plan once carried a scorecard produced by two throwaway scripts,
the dataset was rebuilt, and every figure went stale with nothing to catch it.

Nothing here is a Sigma substitute. It is the reference implementation the
workbook has to reproduce, and the thing that fails when the data moves under
the plan.

Six sections, one per claim the plan makes:

  1. the book        who the clients are and what they cost
  2. the fee error   PEPM billed on member-months, as a ratio and in dollars
  3. the mispricing  the renewal priced over a double-counted denominator
  4. stop-loss       recoveries entitled, received, and lost
  5. the funding     the week a re-driven extract moved real money
  6. the waterfall   billed to allowed to paid to net plan cost
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Generators"))

MART = ROOT / "Mart"

# PY2024 is complete. PY2025 is scored through September, the last month whose
# runout is complete - the same window the provider incentive plan uses, and
# for the same reason: a paid-basis month at the right edge of the extract is
# not a low month, it is an incomplete one.
PY2024 = (202401, 202412)
PY2025_YTD = (202501, 202509)


def read(name: str, **kw) -> pd.DataFrame:
    return pd.read_csv(MART / f"{name}.csv.gz", **kw)


def _win(df: pd.DataFrame, window) -> pd.DataFrame:
    lo, hi = window
    return df[df["year_month"].between(lo, hi)]


# ------------------------------------------------------------------ 1. the book

def book(settle: pd.DataFrame, window) -> pd.DataFrame:
    s = _win(settle, window)
    g = s.groupby("client_id", as_index=False).agg(
        member_months=("member_months", "sum"),
        naive_member_months=("naive_member_months", "sum"),
        contract_months=("subscriber_months", "sum"),
        paid_claims=("paid_claims_amount", "sum"),
        allowed=("allowed_amount", "sum"),
        billed=("billed_amount", "sum"),
        network_savings=("network_savings_amount", "sum"),
        member_liability=("member_liability_amount", "sum"),
        fees=("total_fee_amount", "sum"),
        isl_received=("isl_reimbursement_received_amount", "sum"),
        net_plan_cost=("net_plan_cost_amount", "sum"),
        expected_claims=("expected_claims_amount", "sum"),
    )
    g["paid_pmpm"] = (g["paid_claims"] / g["member_months"]).round(2)
    g["net_pmpm"] = (g["net_plan_cost"] / g["member_months"]).round(2)
    g["fee_pepm"] = (g["fees"] / g["contract_months"]).round(2)
    g["admin_load_pct"] = (100 * g["fees"] / g["paid_claims"]).round(2)
    g["lives_per_contract"] = (
        g["member_months"] / g["contract_months"]).round(3)
    g["variance"] = (g["paid_claims"] - g["expected_claims"]).round(2)
    g["variance_pct"] = (
        100 * g["variance"] / g["expected_claims"]).round(2)
    g["denominator_overstatement_pct"] = (
        100 * (g["naive_member_months"] / g["member_months"] - 1)).round(3)
    return g.sort_values("paid_claims", ascending=False)


# --------------------------------------------------------------- 2. the fee error

def fee_error(settle: pd.DataFrame, window) -> dict:
    """The administration fee on the wrong denominator.

    PEPM means per EMPLOYEE per month. Joining it to member-months prices the
    fee against lives, and the average contract in this book covers a bit more
    than two of them.
    """
    s = _win(settle, window)
    right = float(s["fee_admin_amount"].sum())
    wrong = float(s["fee_admin_amount_on_member_months"].sum())
    return {
        "admin_fee_correct": round(right, 2),
        "admin_fee_on_member_months": round(wrong, 2),
        "overstatement_dollars": round(wrong - right, 2),
        "overstatement_factor": round(wrong / right, 4) if right else None,
        "lives_per_contract": round(
            float(s["member_months"].sum() / s["subscriber_months"].sum()), 4),
        "total_fees_correct": round(float(s["total_fee_amount"].sum()), 2),
        "total_fees_if_admin_wrong": round(
            float(s["total_fee_amount"].sum()) + (wrong - right), 2),
    }


# -------------------------------------------------------------- 3. the mispricing

def mispricing(contract: pd.DataFrame, settle: pd.DataFrame) -> dict:
    """The renewal priced over the enrollment feed's own denominator.

    The consequence is stated as a FUNDING SHORTFALL rather than as a variance,
    because that is what it is. A budget rate is the price the plan sponsor
    collects and accrues against; a rate set 12% below what the client's own
    experience supports means the plan collected 12% less than it should have,
    whichever way the claims then landed. Framing it as a variance direction
    invites the argument that the client came in under budget anyway - which
    it may have, on a budget that was never adequate.
    """
    ct = contract[contract["rate_basis"] == "PRIOR_YEAR_PAID_EXPERIENCE"].copy()
    ct["rate_miss_pct"] = (
        100 * (1 - ct["expected_claims_pmpm"]
               / ct["expected_claims_pmpm_on_true_denominator"])).round(3)
    worst = ct.sort_values("rate_miss_pct", ascending=False).iloc[0]
    client, year = worst["client_id"], int(worst["contract_year"])

    s = _win(settle[settle["client_id"] == client], PY2025_YTD)
    mmths = float(s["member_months"].sum())
    paid = float(s["paid_claims_amount"].sum())
    as_set = float(worst["expected_claims_pmpm"])
    repriced = float(worst["expected_claims_pmpm_on_true_denominator"])
    return {
        "client_id": client,
        "contract_year": year,
        "rate_as_set_pmpm": round(as_set, 2),
        "rate_on_true_denominator_pmpm": round(repriced, 2),
        "rate_miss_pct": round(float(worst["rate_miss_pct"]), 3),
        "prior_year_naive_member_months": round(
            float(worst["prior_year_naive_member_months"]), 2),
        "prior_year_true_member_months": round(
            float(worst["prior_year_true_member_months"]), 2),
        "prior_year_overstatement_pct": round(
            100 * (float(worst["prior_year_naive_member_months"])
                   / float(worst["prior_year_true_member_months"]) - 1), 3),
        "scored_window": f"{PY2025_YTD[0]}..{PY2025_YTD[1]}",
        "member_months_scored": round(mmths, 2),
        "actual_paid": round(paid, 2),
        "actual_pmpm": round(paid / mmths, 2) if mmths else None,
        # The variance as the client was shown it, and against a rate set
        # over the right denominator. Negative is favourable.
        "variance_as_reported": round(paid - as_set * mmths, 2),
        "variance_if_repriced": round(paid - repriced * mmths, 2),
        # The money the plan never collected, which is the actual damage.
        "budget_shortfall": round((repriced - as_set) * mmths, 2),
        # Isolation. A denominator error spread evenly across a book is a
        # scaling factor nobody has to find.
        "worst_other_client_miss_pct": round(float(
            ct[ct["client_id"] != client]["rate_miss_pct"].abs().max()), 4),
        "clients_priced_on_experience": int(ct["client_id"].nunique()),
    }


# ----------------------------------------------------------------- 4. stop-loss

def stop_loss(claimant: pd.DataFrame) -> dict:
    c = claimant
    late = c[c["filing_status"] == "DENIED_LATE_FILING"]
    collapsed = c[pd.to_numeric(
        c["member_ids_on_durable_key"], errors="coerce").fillna(1) > 1]
    lasered = c[c["is_lasered"].astype(str).str.lower() == "true"]
    return {
        "filings": int(len(c)),
        "clients_with_filings": int(c["client_id"].nunique()),
        "entitled": round(float(c["reimbursement_entitled_amount"].sum()), 2),
        "received": round(float(c["reimbursement_received_amount"].sum()), 2),
        "shortfall": round(
            float(c["reimbursement_shortfall_amount"].sum()), 2),
        "late_filings": int(len(late)),
        "late_filing_dollars_lost": round(
            float(late["reimbursement_entitled_amount"].sum()), 2),
        "collapsed_identity_filings": int(len(collapsed)),
        "collapsed_identity_dollars": round(
            float(collapsed["reimbursement_entitled_amount"].sum()), 2),
        "lasered_filings": int(len(lasered)),
        "by_status": c.groupby("filing_status").agg(
            n=("aso_stop_loss_claimant_key", "size"),
            entitled=("reimbursement_entitled_amount", "sum"),
            received=("reimbursement_received_amount", "sum"),
        ).round(2).reset_index().to_dict("records"),
    }


# ------------------------------------------------------------------- 5. funding

def funding(fw: pd.DataFrame) -> dict:
    over = fw[fw["overfunded_amount"] > 1.0]
    worst = over.sort_values("overfunded_amount", ascending=False)
    return {
        "funding_weeks": int(len(fw)),
        "total_drawn": round(float(fw["claims_funded_amount"].sum()), 2),
        "total_reconciled": round(float(fw["reconciled_paid_amount"].sum()), 2),
        "overfunded_weeks": int(len(over)),
        "overfunded_dollars": round(float(over["overfunded_amount"].sum()), 2),
        "overfunded_claim_lines": int(over["overfunded_claim_lines"].sum()),
        "worst_weeks": worst.head(6)[
            ["client_id", "funding_week_end", "claims_funded_amount",
             "reconciled_paid_amount", "overfunded_amount",
             "overfunded_claim_lines"]].round(2).to_dict("records"),
        "short_funded_weeks": int(
            (fw["funding_status"] == "SHORT_FUNDED").sum()),
        "late_wire_weeks": int((fw["funding_status"] == "FUNDED_LATE").sum()),
    }


# ----------------------------------------------------------------- 6. waterfall

def waterfall(settle: pd.DataFrame, window) -> dict:
    s = _win(settle, window)
    billed = float(s["billed_amount"].sum())
    allowed = float(s["allowed_amount"].sum())
    paid = float(s["paid_claims_amount"].sum())
    return {
        "billed": round(billed, 2),
        "network_savings": round(float(s["network_savings_amount"].sum()), 2),
        "allowed": round(allowed, 2),
        "member_liability": round(float(s["member_liability_amount"].sum()), 2),
        "cob": round(float(s["cob_amount"].sum()), 2),
        "paid_claims": round(paid, 2),
        "isl_received": round(
            float(s["isl_reimbursement_received_amount"].sum()), 2),
        "fees": round(float(s["total_fee_amount"].sum()), 2),
        "net_plan_cost": round(float(s["net_plan_cost_amount"].sum()), 2),
        "network_discount_pct": round(100 * (1 - allowed / billed), 2),
        "ibnr_estimate": round(float(s["ibnr_estimate_amount"].sum()), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    settle = read("fct_aso_settlement_month")
    contract = read("aso_client_contract")
    claimant = read("fct_aso_stop_loss_claimant")
    fw = read("fct_aso_funding_week")
    grp = read("dim_employer_group")

    out = {
        "clients": int(grp[grp["funding_type"] == "ASO"]["client_id"].nunique()),
        "groups": int(grp[grp["funding_type"] == "ASO"]["group_id"].nunique()),
        "book_2024": book(settle, PY2024).round(2).to_dict("records"),
        "book_2025_ytd": book(settle, PY2025_YTD).round(2).to_dict("records"),
        "fee_error_2024": fee_error(settle, PY2024),
        "mispricing": mispricing(contract, settle),
        "stop_loss": stop_loss(claimant),
        "funding": funding(fw),
        "waterfall_2024": waterfall(settle, PY2024),
    }

    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0

    pd.set_option("display.width", 220)
    names = dict(zip(grp["client_id"], grp["client_name"]))

    print(f"\nASO book: {out['clients']} self-funded clients "
          f"across {out['groups']} enrollment groups\n")
    b = book(settle, PY2024)
    b["client"] = b["client_id"].map(names)
    print("--- PY2024, complete ---")
    print(b[["client", "member_months", "contract_months",
             "lives_per_contract", "paid_claims", "paid_pmpm", "fees",
             "fee_pepm", "admin_load_pct", "net_pmpm", "variance_pct"]]
          .to_string(index=False))

    f = out["fee_error_2024"]
    print(f"\n--- the PEPM/PMPM error, PY2024 ---")
    print(f"  admin fee, correct (contract-months) : "
          f"${f['admin_fee_correct']:>14,.2f}")
    print(f"  admin fee, on member-months          : "
          f"${f['admin_fee_on_member_months']:>14,.2f}")
    print(f"  overstatement                        : "
          f"${f['overstatement_dollars']:>14,.2f}  "
          f"({f['overstatement_factor']:.3f}x)")
    print(f"  lives per contract                   : "
          f"{f['lives_per_contract']:>15.3f}")

    m = out["mispricing"]
    print(f"\n--- the renewal priced over a double-counted denominator ---")
    print(f"  client                       : {m['client_id']} "
          f"({names.get(m['client_id'])}), {m['contract_year']}")
    print(f"  prior-year member-months     : "
          f"{m['prior_year_naive_member_months']:,.0f} from the enrollment "
          f"feed, {m['prior_year_true_member_months']:,.0f} true "
          f"(+{m['prior_year_overstatement_pct']:.2f}%)")
    print(f"  rate as set                  : ${m['rate_as_set_pmpm']:,.2f} PMPM")
    print(f"  rate on the true denominator : "
          f"${m['rate_on_true_denominator_pmpm']:,.2f} PMPM "
          f"({m['rate_miss_pct']:.2f}% below truth)")
    print(f"  actual, {m['scored_window']}        : "
          f"${m['actual_pmpm']:,.2f} PMPM on "
          f"{m['member_months_scored']:,.0f} member-months")
    print(f"  variance as reported         : "
          f"${m['variance_as_reported']:,.2f}  (negative is favourable)")
    print(f"  variance against a sound rate: "
          f"${m['variance_if_repriced']:,.2f}")
    print(f"  BUDGET NEVER COLLECTED       : "
          f"${m['budget_shortfall']:,.2f}")
    print(f"  worst other client's miss    : "
          f"{m['worst_other_client_miss_pct']:.3f}%  "
          f"(of {m['clients_priced_on_experience']} priced on experience)")

    s = out["stop_loss"]
    print(f"\n--- specific stop-loss ---")
    print(f"  filings                      : {s['filings']:,} across "
          f"{s['clients_with_filings']} clients")
    print(f"  entitled                     : ${s['entitled']:,.2f}")
    print(f"  received                     : ${s['received']:,.2f}")
    print(f"  shortfall                    : ${s['shortfall']:,.2f}")
    print(f"  declined, filed late         : {s['late_filings']} filings, "
          f"${s['late_filing_dollars_lost']:,.2f} the CLIENT absorbs")
    print(f"  on a collapsed identity      : "
          f"{s['collapsed_identity_filings']} filings, "
          f"${s['collapsed_identity_dollars']:,.2f} claimed on two people")

    u = out["funding"]
    print(f"\n--- weekly funding ---")
    print(f"  funding weeks                : {u['funding_weeks']:,}")
    print(f"  drawn                        : ${u['total_drawn']:,.2f}")
    print(f"  reconciled to the mart       : ${u['total_reconciled']:,.2f}")
    print(f"  over-funded                  : {u['overfunded_weeks']} weeks, "
          f"${u['overfunded_dollars']:,.2f} on "
          f"{u['overfunded_claim_lines']:,} claim lines that do not exist")
    for w in u["worst_weeks"][:4]:
        print(f"      {w['client_id']:<9} week ending {w['funding_week_end']}"
              f"  drew ${w['claims_funded_amount']:>12,.2f}  "
              f"owed ${w['reconciled_paid_amount']:>12,.2f}  "
              f"over ${w['overfunded_amount']:>11,.2f}")

    w = out["waterfall_2024"]
    print(f"\n--- PY2024 waterfall ---")
    for k in ("billed", "network_savings", "allowed", "member_liability",
              "cob", "paid_claims", "isl_received", "fees", "net_plan_cost",
              "ibnr_estimate"):
        print(f"  {k:<28} : ${w[k]:>16,.2f}")
    print(f"  {'network_discount_pct':<28} : {w['network_discount_pct']:>16.2f}%")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
