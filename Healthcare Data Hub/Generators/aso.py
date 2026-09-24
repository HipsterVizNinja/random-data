"""The ASO administration and finance system: fees, stop-loss, budget, funding.

A sixth source system, and it earns its place the way the other five do: it is
the only one that knows what the plan sponsor actually PAYS to have its plan
run, and what it gets back when a member blows through a stop-loss deductible.
Claims know the medical dollars. Enrollment knows the denominator. Neither of
them knows the fee schedule, the attachment point, or whether last Wednesday's
wire cleared.

Five tables, at four different grains, because these are four different things:

  aso_client_contract   client x contract year - the deal
  aso_fee_schedule      client x contract year x fee component - the price
  aso_stop_loss_policy  client x policy year - the risk transfer
  aso_budget_rate       client x contract year x coverage tier - the rate card
  aso_funding_request   client x funding week - the cash
  aso_stop_loss_filing  client x member x policy year - the recoveries

Three things in here are deliberately awkward, and each one is awkward in a way
a real ASO book is awkward:

  1. The administration fee is PER EMPLOYEE per month and the network fee is
     PER MEMBER per month. Two denominators, in one fee schedule, differing by
     a factor of about 2.1. Nothing in the data stops an analyst using the
     wrong one and the fee revenue then reads twice its true size.

  2. The renewal rate is DERIVED from prior-year experience over the
     enrollment feed's own denominator - which double counts overlapping
     spans. One client's spans overlap badly because it was loaded under two
     group ids through an acquisition, so its rate was set off a denominator
     roughly a sixth too large, and the deficit that follows looks like bad
     claims experience. It is not. It is arithmetic.

  3. Two clients renew off-cycle, in July and October. Coverage spans break at
     CALENDAR year boundaries because plan design is priced that way, so for
     those two clients the stop-loss policy year and the benefit year are
     different windows. A member-level recovery aggregated by calendar year is
     wrong for exactly two of nine clients.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

import config as C

CONTRACT_YEARS = (2023, 2024, 2025)

# The fee components, and the denominator each one is billed on. The basis
# column is the whole point of shipping this long rather than wide: a fee
# schedule with one row per component cannot hide which denominator applies.
FEE_COMPONENTS = [
    ("ADMIN", "Plan administration", "PEPM"),
    ("NETWORK_ACCESS", "Network access", "PMPM"),
    ("CARE_MGMT", "Care management and utilization review", "PMPM"),
    ("ISL_PREMIUM", "Specific stop-loss premium", "PMPM"),
    ("ASL_PREMIUM", "Aggregate stop-loss premium", "PMPM"),
    ("COBRA_ADMIN", "COBRA administration", "FLAT_MONTHLY"),
]

COVERAGE_TIERS = ("EE", "EE_SPOUSE", "EE_CHILD", "FAMILY")

# The two clients whose specific stop-loss coinsurance is not 100%. Electing
# 90% above the deductible buys a cheaper premium and leaves the client with a
# tenth of every catastrophic claim, which is a trade a CFO makes and a
# reporting layer usually forgets.
ISL_COINSURANCE_ELECTIONS = {"CL-TECH": 0.90, "CL-AG": 0.90}

# Stop-loss contract basis. "PAID_12_12" means claims INCURRED in the 12
# policy months and PAID within those same 12 months are covered; "12_15"
# extends the paid window by three months of runout. A client on 12/12 loses
# cover on any claim that adjudicates after the year closes, which for a
# December admission is most of it.
ISL_CONTRACT_BASIS = {
    "CL-MFG": "PAID_12_15", "CL-EDU": "PAID_12_15", "CL-MUN": "PAID_12_12",
    "CL-LOG": "PAID_12_12", "CL-TECH": "PAID_12_15", "CL-FIN": "PAID_12_15",
    "CL-HLTH": "PAID_12_15", "CL-KELL": "PAID_12_12", "CL-UTIL": "PAID_12_12",
}

# Lasered members: a known high-cost condition carved out at a raised
# deductible as the price of the carrier renewing at all.
LASER_CLIENTS = ("CL-LOG", "CL-UTIL")
LASER_DEDUCTIBLE_MULTIPLE = 2.5


# --------------------------------------------------------------- denominators

def _month_grid() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    months = pd.period_range(
        pd.Timestamp(C.SOURCE_START), pd.Timestamp(C.SOURCE_END), freq="M"
    )
    return (
        pd.to_datetime([p.start_time.date() for p in months]).to_numpy(),
        pd.to_datetime([p.end_time.date() for p in months]).to_numpy(),
        np.array([int(p.strftime("%Y%m")) for p in months]),
        np.array([p.days_in_month for p in months]),
    )


def naive_member_months(spans: pd.DataFrame) -> pd.DataFrame:
    """Member-months the way the enrollment extract yields them: by SUMMING.

    This is the wrong answer and it is here on purpose. It is the counterpart
    of build_member_months in eligibility.py - same month intersection, same
    day weighting - with the island union left out. Every overlapping span is
    therefore counted twice, and the error concentrates wherever spans
    overlap, which is one acquired client.

    A rate-setting analyst working from the enrollment feed produces exactly
    this number. Shipping it beside the correct one is what turns "your
    denominator is wrong" from an assertion into a subtraction.
    """
    m_start, m_end, m_key, m_days = _month_grid()
    s = spans[["member_id", "group_id", "span_start_date", "span_end_date"]].copy()
    start = pd.to_datetime(s["span_start_date"]).to_numpy()[:, None]
    end = pd.to_datetime(s["span_end_date"]).to_numpy()[:, None]
    lo = np.maximum(start, m_start[None, :])
    hi = np.minimum(end, m_end[None, :])
    days = ((hi - lo).astype("timedelta64[D]").astype(int) + 1).clip(min=0)
    ri, rm = np.nonzero(days)
    out = pd.DataFrame({
        "group_id": s["group_id"].to_numpy()[ri],
        "year_month": m_key[rm],
        "naive_member_months": days[ri, rm] / m_days[rm],
    })
    return out.groupby(["group_id", "year_month"], as_index=False).sum()


def coverage_tier_months(mm: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    """Contract-months by coverage tier, at subscriber x month.

    The PEPM denominator is CONTRACTS, not lives, so it has to be counted on
    the subscriber. person_code 01 is the subscriber, 02 the spouse, 03 and up
    the children, which is what makes the tier recoverable at all:

      01 alone            -> EE
      01 + 02             -> EE_SPOUSE
      01 + 03..           -> EE_CHILD
      01 + 02 + 03..      -> FAMILY

    A contract-month is credited only where the SUBSCRIBER was covered. A
    dependent enrolled in a month the subscriber was not is a data problem,
    not a contract, and counting it would inflate the fee denominator.
    """
    who = members[["member_id", "subscriber_id", "person_code"]]
    m = mm.merge(who, on="member_id", how="inner")
    m["is_subscriber"] = m["person_code"] == "01"
    m["is_spouse"] = m["person_code"] == "02"
    m["is_child"] = m["person_code"].isin(["03", "04", "05", "06", "07", "08"])

    # Grouped by GROUP as well as subscriber, because a household can
    # legitimately straddle two groups: a member who turns 65 leaves the
    # employer plan for individual Medicare Advantage while their family
    # stays. Collapsing on subscriber alone would attribute that household's
    # whole contract to whichever group happened to sort first.
    fam = m.groupby(["group_id", "subscriber_id", "year_month"],
                    as_index=False).agg(
        has_sub=("is_subscriber", "max"),
        has_spouse=("is_spouse", "max"),
        has_child=("is_child", "max"),
        subscriber_months=("member_months", "max"),
    )
    # A contract-month is credited only where the SUBSCRIBER was covered in
    # that group. A dependent enrolled in a month the subscriber was not is a
    # data problem, not a contract, and counting it inflates every
    # per-employee fee in the book.
    fam = fam[fam["has_sub"]].copy()
    fam["coverage_tier"] = np.select(
        [fam["has_spouse"] & fam["has_child"],
         fam["has_spouse"] & ~fam["has_child"],
         ~fam["has_spouse"] & fam["has_child"]],
        ["FAMILY", "EE_SPOUSE", "EE_CHILD"], default="EE")
    return fam[["group_id", "year_month", "coverage_tier", "subscriber_months"]]


# ----------------------------------------------------------------- the tables

def build_aso(
    run: C.RunConfig,
    tables: dict[str, pd.DataFrame],
    members: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Build every ASO table.

    Runs AFTER the anomaly stage, and that ordering is load-bearing. The
    funding system draws against the adjudication extract as it arrived, so a
    week whose extract was re-driven funds the duplicates. Building funding
    from a clean claim feed would remove the only consequence of that defect
    that anybody outside the data team ever feels.
    """
    rng = run.rng("aso")
    groups = tables["elig_employer_group"]
    spans = tables["elig_eligibility_span"]
    mm = tables["fct_member_month"]
    lines = tables["clm_claim_line"]

    aso_groups = groups[groups["funding_type"] == "ASO"]
    clients = (
        aso_groups[["client_id", "client_name", "sector", "size_tier",
                    "renewal_month", "client_since_date", "broker_name"]]
        .sort_values("client_id")
        # One row per client. Kellerman contributes two group ids and one
        # contract; taking the first sorted row keeps the SMALL size tier it
        # was actually priced at rather than the zero-weight successor's.
        .drop_duplicates("client_id")
        .reset_index(drop=True)
    )
    group_to_client = dict(zip(groups["group_id"], groups["client_id"]))

    # ---- denominators, both of them
    mm = mm.copy()
    mm["year_month"] = pd.to_numeric(mm["year_month"])
    mm["member_months"] = pd.to_numeric(mm["member_months"])
    mm["client_id"] = mm["group_id"].map(group_to_client)
    true_mm = (
        mm.groupby(["client_id", "year_month"], as_index=False)
        .agg(member_months=("member_months", "sum"))
    )
    naive = naive_member_months(spans)
    naive["client_id"] = naive["group_id"].map(group_to_client)
    naive_mm = (
        naive.groupby(["client_id", "year_month"], as_index=False)
        .agg(naive_member_months=("naive_member_months", "sum"))
    )
    tiers = coverage_tier_months(mm, members)
    tiers["client_id"] = tiers["group_id"].map(group_to_client)
    tier_mm = (
        tiers.groupby(["client_id", "year_month", "coverage_tier"], as_index=False)
        .agg(subscriber_months=("subscriber_months", "sum"))
    )

    # ---- claims, attributed to the client that covered the member ON THE
    # SERVICE DATE. This is an as-of join and it has to be: a member who
    # changes employer mid-year takes their claims with them, and attributing
    # the whole year to whichever client covered them in December moves real
    # money between two clients' settlements.
    L = lines.copy()
    for c in ("paid_amount", "allowed_amount", "billed_amount",
              "deductible_amount", "copay_amount", "coinsurance_amount",
              "cob_amount", "contractual_writeoff_amount"):
        L[c] = pd.to_numeric(L[c], errors="coerce").fillna(0.0)
    L["service_year_month"] = (
        pd.to_datetime(L["service_date"]).dt.strftime("%Y%m").astype(int))
    asof = mm[["member_id", "year_month", "client_id"]].rename(
        columns={"year_month": "service_year_month"})
    L = L.merge(asof, on=["member_id", "service_year_month"], how="left")
    L["client_id"] = L["client_id"].fillna("UNATTRIBUTED")
    aso_lines = L[L["client_id"].isin(set(clients["client_id"]))].copy()

    # Prior-year experience on an INCURRED basis: claims grouped by the year
    # they were SERVICED, over member-months for that same year.
    #
    # It was paid-year dollars over service-year member-months, which is two
    # different bases in one ratio. The first year of any data window has no
    # inflow from the year before it and loses its own tail to the year after,
    # so a paid-year numerator understated 2023 by roughly 8% for every client
    # at once - a book-wide artifact sitting on top of the one client-specific
    # defect this layer exists to show.
    #
    # The simplification, named rather than hidden: the rate is priced as
    # though the prior year were fully developed on the October the rate is
    # set, which credits an underwriter with three months of runout they do
    # not have. Modeling that lag honestly needs a completion factor applied
    # to a partial year, and it would move every rate in the same direction by
    # the same amount, which is the confounder just removed.
    paid_by_cy = (
        aso_lines.assign(service_year=aso_lines["service_year_month"] // 100)
        .groupby(["client_id", "service_year"], as_index=False)
        .agg(paid_amount=("paid_amount", "sum"))
    )

    # ---- the contract, the fees, the policy, the rate card, the cash
    # ---- who gets lasered.
    #
    # A laser is not applied to whoever happens to be the biggest claimant in
    # a given year: the carrier names a MEMBER with a known condition at the
    # renewal that follows the year it saw, and the carve-out then follows
    # that member. Selecting per year instead would mean the exclusion moved
    # around, which is not a thing that happens and which would make the
    # recovery table read as noise.
    laser_member = _laser_members(aso_lines)

    contract = _contracts(clients, true_mm, naive_mm, paid_by_cy)
    fees = _fee_schedule(clients, contract)
    policy = _stop_loss_policy(clients, contract, laser_member)
    rates = _budget_rates(contract, tier_mm)
    funding = _funding_requests(rng, clients, aso_lines)
    # The eligibility-side identity map. The over-match lives here: about
    # thirty master person ids each carry two genuinely distinct member ids,
    # and any report built on the resolved identity sums both of them.
    xp = tables["xwalk_patient"]
    identity = xp[xp["source_system"] == "MERIDIAN_ELIG"][
        ["source_patient_id", "master_person_id"]
    ].rename(columns={"source_patient_id": "member_id"})
    filings = _stop_loss_filings(rng, policy, aso_lines, identity)

    return {
        "aso_client_contract": contract,
        "aso_fee_schedule": fees,
        "aso_stop_loss_policy": policy,
        "aso_budget_rate": rates,
        "aso_funding_request": funding,
        "aso_stop_loss_filing": filings,
    }


def _contracts(clients, true_mm, naive_mm, paid_by_cy) -> pd.DataFrame:
    """Client x contract year, including the derived expected-claims PMPM.

    The rate for year Y is set from year Y-1 paid claims over year Y-1
    member-months, trended and loaded for margin. Paid basis rather than
    incurred, because a paid-basis experience report is what a TPA actually
    hands underwriting at renewal and it needs no completion factor to be
    honest about.

    The denominator used is the NAIVE one, on purpose. That is the number the
    enrollment extract yields and the number a rate-setting analyst has.
    Shipping both denominators on the same row is what makes the consequence
    subtractable instead of arguable.
    """
    t = true_mm.copy(); t["contract_year"] = t["year_month"] // 100
    t = t.groupby(["client_id", "contract_year"], as_index=False).sum(
        numeric_only=True)[["client_id", "contract_year", "member_months"]]
    nv = naive_mm.copy(); nv["contract_year"] = nv["year_month"] // 100
    nv = nv.groupby(["client_id", "contract_year"], as_index=False).sum(
        numeric_only=True)[["client_id", "contract_year", "naive_member_months"]]
    paid = paid_by_cy.rename(columns={"service_year": "contract_year"})

    rows = []
    key = 1
    for cl in clients.itertuples():
        for year in CONTRACT_YEARS:
            prior = year - 1
            pm = paid[(paid.client_id == cl.client_id)
                      & (paid.contract_year == prior)]["paid_amount"]
            nm = nv[(nv.client_id == cl.client_id)
                    & (nv.contract_year == prior)]["naive_member_months"]
            tm = t[(t.client_id == cl.client_id)
                   & (t.contract_year == prior)]["member_months"]
            have_prior = len(pm) and len(nm) and float(nm.iloc[0]) > 0
            if have_prior:
                basis = "PRIOR_YEAR_PAID_EXPERIENCE"
                pmpm_as_set = float(pm.iloc[0]) / float(nm.iloc[0])
                pmpm_true = (float(pm.iloc[0]) / float(tm.iloc[0])
                             if len(tm) and float(tm.iloc[0]) > 0 else None)
            else:
                # 2023 has no prior year inside the source window.
                basis = "SEEDED_SECTOR_LOAD"
                load = C.ASO_SECTOR_LOAD.get(cl.sector, 1.0)
                pmpm_as_set = C.ASO_SEED_EXPECTED_PMPM * load
                pmpm_true = pmpm_as_set
            factor = (1.0 + C.ASO_RENEWAL_TREND) * (1.0 + C.ASO_RATE_MARGIN)
            expected = round(pmpm_as_set * factor, 2)
            expected_true = (round(pmpm_true * factor, 2)
                             if pmpm_true is not None else None)
            rows.append({
                "aso_client_contract_key": key,
                "client_id": cl.client_id,
                "client_name": cl.client_name,
                "contract_year": year,
                "funding_type": "ASO",
                "sector": cl.sector,
                "size_tier": cl.size_tier,
                "renewal_month": cl.renewal_month,
                "contract_effective_date":
                    date(year, cl.renewal_month, 1).isoformat(),
                "contract_status": "ACTIVE" if year < 2025 else "IN_FLIGHT",
                "client_since_date": cl.client_since_date,
                "broker_name": cl.broker_name,
                "rate_basis": basis,
                "trend_assumption_pct": round(C.ASO_RENEWAL_TREND * 100, 2),
                "margin_pct": round(C.ASO_RATE_MARGIN * 100, 2),
                # The rate as it was actually set, over the denominator the
                # analyst actually had.
                "expected_claims_pmpm": expected,
                # And the same arithmetic over the correct denominator. The
                # gap between these two columns IS the finding.
                "expected_claims_pmpm_on_true_denominator": expected_true,
                "prior_year_naive_member_months":
                    round(float(nm.iloc[0]), 2) if have_prior else None,
                "prior_year_true_member_months":
                    round(float(tm.iloc[0]), 2) if (have_prior and len(tm)) else None,
            })
            key += 1
    return pd.DataFrame(rows)


def _fee_schedule(clients, contract) -> pd.DataFrame:
    """Client x contract year x fee component, long.

    Long rather than wide so the BASIS travels on the row. A wide fee table
    with admin_fee_pepm beside network_fee_pmpm next to each other invites
    exactly one join to member-months and one wrong answer.
    """
    tier_by_client = dict(zip(clients["client_id"], clients["size_tier"]))
    renewal = dict(zip(clients["client_id"], clients["renewal_month"]))
    rows = []
    key = 1
    for row in contract.itertuples():
        st = tier_by_client[row.client_id]
        isl_ded = C.ASO_ISL_DEDUCTIBLE[st]
        amounts = {
            "ADMIN": C.ASO_ADMIN_FEE_PEPM[st],
            "NETWORK_ACCESS": C.ASO_NETWORK_ACCESS_FEE_PMPM[st],
            "CARE_MGMT": C.ASO_CARE_MGMT_FEE_PMPM[st],
            "ISL_PREMIUM": C.ASO_ISL_PREMIUM_PMPM[isl_ded],
            "ASL_PREMIUM": C.ASO_ASL_PREMIUM_PMPM[st],
            "COBRA_ADMIN": C.ASO_COBRA_ADMIN_FEE_MONTHLY,
        }
        # Fees step up each contract year with the same trend the rate carries.
        step = (1.0 + C.ASO_RENEWAL_TREND * 0.35) ** (row.contract_year - 2023)
        rm = renewal[row.client_id]
        for code, name, basis in FEE_COMPONENTS:
            rows.append({
                "aso_fee_schedule_key": key,
                "client_id": row.client_id,
                "contract_year": row.contract_year,
                "fee_code": code,
                "fee_name": name,
                "fee_basis": basis,
                "fee_amount": round(amounts[code] * step, 2),
                # Off-cycle clients re-price in their renewal month, not in
                # January, so the fee has an effective date and not just a
                # year. A monthly fee roll-up that ignores this bills the new
                # rate from January for two of nine clients.
                "effective_date": date(row.contract_year, rm, 1).isoformat(),
                "is_pass_through": code in ("ISL_PREMIUM", "ASL_PREMIUM"),
            })
            key += 1
    return pd.DataFrame(rows)


def _laser_members(aso_lines) -> dict[str, str]:
    """The single largest 2023 claimant for each laser client.

    2023, because the carve-out is negotiated at the 2024 renewal off the
    experience the carrier had in front of it. Using the whole window would
    let the laser be chosen with knowledge of years the carrier had not seen.
    """
    y23 = aso_lines[
        aso_lines["client_id"].isin(LASER_CLIENTS)
        & (pd.to_datetime(aso_lines["service_date"]).dt.year == 2023)
    ]
    if y23.empty:
        return {}
    tot = y23.groupby(["client_id", "member_id"], as_index=False).agg(
        paid=("paid_amount", "sum"))
    top = tot.sort_values(["client_id", "paid", "member_id"],
                          ascending=[True, False, True]).drop_duplicates("client_id")
    return dict(zip(top["client_id"], top["member_id"]))


def _stop_loss_policy(clients, contract, laser_member) -> pd.DataFrame:
    """Client x policy year. The risk transfer, with its own year boundaries.

    The policy year starts in the client's renewal month, which for two
    clients is not January. The ISL deductible accumulates over THAT window,
    so a member-level recovery aggregated by calendar year is wrong for those
    two clients and right for the other seven - the shape of error that gets
    signed off because it reconciles almost everywhere.
    """
    tier_by_client = dict(zip(clients["client_id"], clients["size_tier"]))
    renewal = dict(zip(clients["client_id"], clients["renewal_month"]))
    exp_by = {(r.client_id, r.contract_year): r.expected_claims_pmpm
              for r in contract.itertuples()}
    rows = []
    key = 1
    for cl in sorted(clients["client_id"]):
        st = tier_by_client[cl]
        ded = C.ASO_ISL_DEDUCTIBLE[st]
        rm = renewal[cl]
        for year in CONTRACT_YEARS:
            start = date(year, rm, 1)
            end = date(year + 1, rm, 1) - timedelta(days=1)
            expected = exp_by.get((cl, year), C.ASO_SEED_EXPECTED_PMPM)
            # Lasered from the 2024 renewal onward, never retroactively.
            lasered = laser_member.get(cl) if year >= 2024 else None
            has_laser = lasered is not None
            rows.append({
                "aso_stop_loss_policy_key": key,
                "client_id": cl,
                "policy_year": year,
                "policy_year_start_date": start.isoformat(),
                "policy_year_end_date": end.isoformat(),
                "policy_year_label": f"{start.isoformat()}..{end.isoformat()}",
                "carrier_name": "Ridgeline Reinsurance",
                "policy_number": f"RR-{cl.replace('CL-', '')}-{year}",
                "isl_deductible": ded,
                "isl_coinsurance_pct": round(
                    ISL_COINSURANCE_ELECTIONS.get(cl, 1.00), 4),
                "isl_contract_basis": ISL_CONTRACT_BASIS.get(cl, "PAID_12_12"),
                "isl_filing_deadline_date": (
                    end + timedelta(days=C.ASO_ISL_FILING_DEADLINE_DAYS)
                ).isoformat(),
                "has_aggregate_stop_loss": True,
                "asl_attachment_factor": C.ASO_ASL_ATTACHMENT_FACTOR,
                "asl_attachment_pmpm": round(
                    expected * C.ASO_ASL_ATTACHMENT_FACTOR, 2),
                "asl_corridor_pct": round(
                    (C.ASO_ASL_ATTACHMENT_FACTOR - 1.0) * 100, 2),
                "asl_monthly_accommodation": cl in ("CL-MUN", "CL-KELL"),
                "has_lasered_member": has_laser,
                "lasered_member_id": lasered,
                "laser_deductible": (round(ded * LASER_DEDUCTIBLE_MULTIPLE, 2)
                                     if has_laser else None),
            })
            key += 1
    return pd.DataFrame(rows)


def _budget_rates(contract, tier_mm) -> pd.DataFrame:
    """Client x contract year x coverage tier. The rate card.

    The employee-only rate is SOLVED so that the tiered rates, billed against
    the projected contract mix, raise the expected claims the contract states:

        sum over tiers of  factor(t) x contract_months(t) x base
          = expected_claims_pmpm x member_months

    which is how rate tiering actually works and which makes the rate card
    reconcile to the contract by construction rather than by coincidence. The
    projected mix here is the prior year's actual mix, so where enrollment mix
    drifts the rates go slightly inadequate - a real and usually unnoticed
    source of ASO deficit, and one the mart can now show.
    """
    tm = tier_mm.copy()
    tm["contract_year"] = tm["year_month"] // 100
    mix = tm.groupby(["client_id", "contract_year", "coverage_tier"],
                     as_index=False).agg(
        subscriber_months=("subscriber_months", "sum"))
    rows = []
    key = 1
    for row in contract.itertuples():
        cy = (row.client_id, row.contract_year)
        m = mix[(mix.client_id == row.client_id)
                & (mix.contract_year == row.contract_year)]
        if m.empty:
            continue
        weighted = float(
            (m["coverage_tier"].map(C.ASO_TIER_FACTORS) * m["subscriber_months"]).sum()
        )
        # Lives behind those contracts, from the tier factors' own definition
        # of a contract's size. Using member-months here instead would make
        # the solve circular.
        if weighted <= 0:
            continue
        member_months_projected = float(
            (m["coverage_tier"].map({"EE": 1.0, "EE_SPOUSE": 2.0,
                                     "EE_CHILD": 2.1, "FAMILY": 3.4})
             * m["subscriber_months"]).sum()
        )
        base = row.expected_claims_pmpm * member_months_projected / weighted
        for tier in COVERAGE_TIERS:
            sm = m[m.coverage_tier == tier]["subscriber_months"]
            rows.append({
                "aso_budget_rate_key": key,
                "client_id": row.client_id,
                "contract_year": row.contract_year,
                "coverage_tier": tier,
                "tier_factor": C.ASO_TIER_FACTORS[tier],
                "budget_rate_pepm": round(base * C.ASO_TIER_FACTORS[tier], 2),
                "rate_set_date": date(row.contract_year - 1, 10, 15).isoformat(),
                "projected_contract_months": round(
                    float(sm.iloc[0]) if len(sm) else 0.0, 2),
                "rate_basis": row.rate_basis,
            })
            key += 1
    return pd.DataFrame(rows)


def _funding_requests(rng, clients, aso_lines) -> pd.DataFrame:
    """Client x funding week. The cash, and the only place it appears.

    Weekly draw, Wednesday-dated, covering the seven days ending that
    Wednesday, summed over claims whose PAID date falls in the window. Built
    from the adjudication extract as landed, so the week whose extract was
    re-driven funds its duplicates - and the reconciliation against the
    de-duplicated mart is the variance that shows up.
    """
    L = aso_lines[["client_id", "paid_date", "paid_amount", "claim_line_number"]].copy()
    L["paid"] = pd.to_datetime(L["paid_date"])
    # Week ending Wednesday: shift so Thursday starts the week.
    offset = (L["paid"].dt.weekday - C.ASO_FUNDING_DAY_OF_WEEK) % 7
    L["week_end"] = L["paid"] + pd.to_timedelta(6 - offset, unit="D")
    agg = L.groupby(["client_id", "week_end"], as_index=False).agg(
        claims_funded_amount=("paid_amount", "sum"),
        claim_lines_funded=("claim_line_number", "size"))
    agg = agg.sort_values(["client_id", "week_end"]).reset_index(drop=True)

    n = len(agg)
    lo, hi = C.ASO_WIRE_LAG_DAYS
    lag = rng.integers(lo, hi + 1, size=n)
    late = rng.random(n) < C.ASO_LATE_WIRE_RATE
    short = rng.random(n) < C.ASO_SHORT_FUND_RATE
    short_pct = np.where(short, rng.uniform(0.82, 0.985, size=n), 1.0)

    agg["request_date"] = agg["week_end"].dt.date.astype(str)
    agg["funding_week_start"] = (
        agg["week_end"] - pd.Timedelta(days=6)).dt.date.astype(str)
    agg["funding_week_end"] = agg["week_end"].dt.date.astype(str)
    agg["requested_amount"] = agg["claims_funded_amount"].round(2)
    agg["wire_received_date"] = (
        agg["week_end"] + pd.to_timedelta(lag + np.where(late, 4, 0), unit="D")
    ).dt.date.astype(str)
    agg["wire_amount"] = (agg["requested_amount"] * short_pct).round(2)
    agg["variance_amount"] = (
        agg["wire_amount"] - agg["requested_amount"]).round(2)
    agg["funding_status"] = np.select(
        [short, late], ["SHORT_FUNDED", "FUNDED_LATE"], default="FUNDED")
    agg["days_to_wire"] = lag + np.where(late, 4, 0)
    agg = agg.drop(columns=["week_end"])
    agg.insert(0, "aso_funding_request_key", np.arange(1, len(agg) + 1))
    return agg


def _stop_loss_filings(rng, policy, aso_lines, identity) -> pd.DataFrame:
    """Client x member x policy year. What was filed, and what came back.

    Accumulation runs over the POLICY year, which for two clients is not the
    calendar year, and claims are tested against the contract's paid window -
    so a 12/12 client loses cover on a December claim that adjudicated in
    February. That is the contract working as written, not a gap in the data.

    Two planted problems, both realistic and both expensive:

      - Filings assembled from the TPA's resolved-identity large claimant
        report carry an amount summed across every member id behind one
        master person id. Where the master data management run OVER-matched -
        twins, a Jr/Sr pair - that is two different people's claims on one
        stop-loss filing. The filing basis is on the row and the amount ties
        to the resolved identity perfectly. Nothing announces that the
        identity is wrong; the only way to find it is to notice that a
        durable key carries two member ids.
      - Filings submitted after the deadline are declined, and the CLIENT
        absorbs the claim. A report of recoveries a plan was entitled to will
        never show it.
    """
    pol = policy.copy()
    pol["start"] = pd.to_datetime(pol["policy_year_start_date"])
    pol["end"] = pd.to_datetime(pol["policy_year_end_date"])

    L = aso_lines[["client_id", "member_id", "service_date", "paid_date",
                   "paid_amount"]].copy()
    L["service"] = pd.to_datetime(L["service_date"])
    L["paid"] = pd.to_datetime(L["paid_date"])
    L = L.merge(identity, on="member_id", how="left")

    # Which master person ids collapse more than one member id.
    per_identity = identity.groupby("master_person_id")["member_id"].nunique()
    overmatched = set(per_identity[per_identity > 1].index)

    rows = []
    key = 1
    for p in pol.itertuples():
        sub = L[(L.client_id == p.client_id)
                & (L.service >= p.start) & (L.service <= p.end)]
        if sub.empty:
            continue
        # Paid window: 12/12 closes with the policy year, 12/15 allows three
        # months of runout before cover lapses.
        paid_cutoff = (p.end + pd.DateOffset(months=3)
                       if p.isl_contract_basis == "PAID_12_15" else p.end)
        covered = sub[sub.paid <= paid_cutoff]

        acc = covered.groupby("member_id", as_index=False).agg(
            covered_paid_amount=("paid_amount", "sum"))
        total = sub.groupby("member_id", as_index=False).agg(
            policy_year_paid_amount=("paid_amount", "sum"))
        acc = total.merge(acc, on="member_id", how="left").fillna(
            {"covered_paid_amount": 0.0})
        acc = acc.merge(identity, on="member_id", how="left")

        # ---- the resolved-identity roll-up, for over-matched identities only
        res = acc[acc["master_person_id"].isin(overmatched)]
        res = res.groupby("master_person_id", as_index=False).agg(
            covered_paid_amount=("covered_paid_amount", "sum"),
            policy_year_paid_amount=("policy_year_paid_amount", "sum"),
            member_id=("member_id", "min"),
            member_ids_rolled_up=("member_id", "size"))
        res = res[(res["covered_paid_amount"] > p.isl_deductible)
                  & (res["member_ids_rolled_up"] > 1)]
        res["filing_identity_basis"] = "MASTER_PERSON_ID"

        # ---- everyone else, on the identifier the claims system carried
        suppressed = set()
        if not res.empty:
            ids = set(res["master_person_id"])
            suppressed = set(acc[acc["master_person_id"].isin(ids)]["member_id"])
        mem = acc[(acc["covered_paid_amount"] > p.isl_deductible)
                  & (~acc["member_id"].isin(suppressed))].copy()
        mem["filing_identity_basis"] = "MEMBER_ID"
        mem["member_ids_rolled_up"] = 1

        cols = ["member_id", "covered_paid_amount", "policy_year_paid_amount",
                "filing_identity_basis", "member_ids_rolled_up"]
        crossed = pd.concat(
            [mem[cols], res[cols]], ignore_index=True
        ).sort_values("member_id").reset_index(drop=True)
        if crossed.empty:
            continue

        # ---- the laser, applied to the NAMED member and nobody else
        is_lasered = (
            crossed["member_id"] == p.lasered_member_id
            if p.has_lasered_member else pd.Series(False, index=crossed.index)
        ).to_numpy()
        eff_ded = np.where(is_lasered, float(p.laser_deductible or 0.0),
                           float(p.isl_deductible))
        over = np.maximum(
            crossed["covered_paid_amount"].to_numpy() - eff_ded, 0.0)

        # A filing is only made where something is actually recoverable. A
        # lasered member who clears the ordinary deductible but not the
        # carve-out generates no filing at all, which is exactly what the
        # carrier bought - and the claim then sits in the client's own costs
        # with no recovery row anywhere to explain it.
        keep = over > 0
        crossed = crossed[keep].reset_index(drop=True)
        if crossed.empty:
            continue
        is_lasered, eff_ded, over = is_lasered[keep], eff_ded[keep], over[keep]
        n = len(crossed)
        entitled = np.round(over * float(p.isl_coinsurance_pct), 2)

        late = rng.random(n) < 0.055
        filed_offset = np.where(
            late,
            rng.integers(C.ASO_ISL_FILING_DEADLINE_DAYS + 5,
                         C.ASO_ISL_FILING_DEADLINE_DAYS + 70, size=n),
            rng.integers(12, C.ASO_ISL_FILING_DEADLINE_DAYS - 10, size=n),
        )
        status = np.where(
            late, "DENIED_LATE_FILING",
            np.where(p.policy_year == 2025, "PENDING", "REIMBURSED"))
        received = np.where(status == "REIMBURSED", entitled, 0.0)

        for i, r in enumerate(crossed.itertuples()):
            rows.append({
                "aso_stop_loss_filing_key": key,
                "client_id": p.client_id,
                "policy_year": p.policy_year,
                "policy_year_label": p.policy_year_label,
                "policy_number": p.policy_number,
                "member_id": r.member_id,
                "filing_identity_basis": r.filing_identity_basis,
                "member_ids_rolled_up": int(r.member_ids_rolled_up),
                "isl_deductible": float(p.isl_deductible),
                "effective_isl_deductible": round(float(eff_ded[i]), 2),
                "is_lasered": bool(is_lasered[i]),
                "isl_coinsurance_pct": float(p.isl_coinsurance_pct),
                "policy_year_paid_amount": round(
                    float(r.policy_year_paid_amount), 2),
                "covered_paid_amount": round(float(r.covered_paid_amount), 2),
                "amount_over_deductible": round(float(over[i]), 2),
                "reimbursement_entitled_amount": float(entitled[i]),
                "filed_date": (
                    p.end.date() + timedelta(days=int(filed_offset[i]))
                ).isoformat(),
                "filing_deadline_date": p.isl_filing_deadline_date,
                "filing_status": str(status[i]),
                "reimbursement_received_amount": round(float(received[i]), 2),
            })
            key += 1
    return pd.DataFrame(rows)
