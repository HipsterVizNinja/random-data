#!/usr/bin/env python3
"""Build the conformed and dimensional layer from the raw source files.

    python Build/build_mart.py

This is the layer that turns five source systems into something a BI tool can
sit on. The transformations it performs are the substance of the demo, so each
one is named and commented rather than chained silently:

  conform   - type, trim, and normalize every coded column; resolve the three
              sex encodings and the encounter-type drift into one vocabulary
  resolve   - apply the patient and provider crosswalks, sending unmatched
              keys to the -1 Unknown member and recording WHY
  dimension - build the conformed dimensions, including both type-2 ones
  fact      - build the facts, with surrogate keys and resolution-status
              companions on every foreign key
  serve     - one wide, bridge-free view that is safe to sum

The equivalent Snowflake SQL lives in SQL/. Both are maintained as two
expressions of the same transform: this one runs locally with no engine, that
one runs after a COPY INTO.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Generators"))

import config as C  # noqa: E402
import write as W  # noqa: E402

RAW = ROOT / "Source Data"
MART = ROOT / "Mart"

# Unknown and Not Applicable members exist on every dimension so that facts
# stay inner-joinable while broken keys stay countable.
UNKNOWN_KEY = -1
NOT_APPLICABLE_KEY = -2

# The three source encodings for sex, resolved into one vocabulary.
SEX_CONFORM = {
    "M": "M", "F": "F", "U": "U",
    "1": "M", "2": "F", "9": "U",
    "Male": "M", "Female": "F", "Unknown": "U",
}

# Encounter type drifts by site. 'AMB' is deliberately absent from the
# crosswalk seed, so it lands as UNKNOWN until someone profiles the values.
ENCOUNTER_TYPE_CONFORM = {
    "OFFICE": "AMBULATORY",
    "OFFICE VISIT": "AMBULATORY",
    "URGENT": "URGENT_CARE",
    "ED": "EMERGENCY",
    "INPATIENT": "INPATIENT",
}


def read(folder: str, name: str) -> pd.DataFrame:
    path = RAW / folder / f"{name}.csv.gz"
    if not path.exists():
        raise FileNotFoundError(f"{path} - run Generators/build.py first")
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])


def numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def boolean(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = df[c].map({"True": True, "False": False}).astype("boolean")
    return df


def log(msg, t0):
    print(f"  [{time.time() - t0:6.1f}s] {msg}", flush=True)


# ----------------------------------------------------------------- dimensions

def build_dimensions(t0) -> dict[str, pd.DataFrame]:
    out = {}

    date = read("raw_ref", "ref_date")
    date = numeric(date, ["date_key", "calendar_year", "calendar_month",
                          "year_month", "claims_completeness_factor"])
    date = boolean(date, ["is_weekend", "is_holiday", "is_month_end",
                          "claims_runout_complete_flag", "is_in_source_window",
                          "is_in_analysis_window"])
    out["dim_date"] = date

    for src, name in [("ref_diagnosis", "dim_diagnosis"),
                      ("ref_procedure", "dim_procedure"),
                      ("ref_service_place", "dim_service_place"),
                      ("ref_drg", "dim_drg"),
                      ("ref_claim_status", "dim_claim_status"),
                      ("ref_service_line", "dim_service_line")]:
        out[name] = read("raw_ref", src)

    out["dim_facility"] = read("raw_ref", "ref_facility")
    out["dim_coverage_plan"] = read("raw_elig", "elig_coverage_plan")

    # ---- dim_member. Type 1 on demographics; the type-2 attributes that
    # actually change (plan, site, risk band) are carried on member-month.
    mem = read("raw_elig", "elig_member")
    mem["sex_conformed"] = mem["sex"].map(SEX_CONFORM)
    unmapped = mem["sex_conformed"].isna().sum()
    if unmapped:
        print(f"    WARNING: {unmapped} unmapped sex values")
    mem["sex_source_value"] = mem["sex"]
    mem = mem.drop(columns=["sex"]).rename(columns={"sex_conformed": "sex"})
    xp = read("Mart_xwalk", "xwalk_patient") if False else pd.read_csv(
        MART / "xwalk_patient.csv.gz", dtype=str, keep_default_na=False,
        na_values=[""])
    elig_x = xp[xp.source_system == "MERIDIAN_ELIG"][
        ["source_patient_id", "master_person_id"]
    ].rename(columns={"source_patient_id": "member_id"})
    mem = mem.merge(elig_x, on="member_id", how="left")
    mem = mem.rename(columns={"master_person_id": "member_durable_key"})
    mem = mem.sort_values("member_id").reset_index(drop=True)
    mem.insert(0, "member_key", np.arange(1, len(mem) + 1))
    out["dim_member"] = _with_unknown_rows(mem, "member_key",
                                           {"member_id": "UNKNOWN"})

    # ---- dim_provider, already type 2 from the credentialing source
    prov = read("raw_ref", "ref_provider")
    prov = boolean(prov, ["is_pcp", "is_current"])
    out["dim_provider"] = _with_unknown_rows(prov, "provider_key",
                                             {"npi": "UNKNOWN"})
    out["dim_provider_current"] = prov[prov["is_current"] == True].copy()  # noqa: E712

    out["dim_master_person"] = pd.read_csv(
        MART / "dim_master_person.csv.gz", dtype=str,
        keep_default_na=False, na_values=[""])
    log(f"dimensions: {len(out)} tables", t0)
    return out


def _with_unknown_rows(df: pd.DataFrame, key_col: str, fill: dict) -> pd.DataFrame:
    """Prepend the -1 Unknown and -2 Not Applicable members.

    Facts resolve unmatched keys to -1 and carry a resolution-status column, so
    the mart stays inner-joinable AND the defect stays countable. The trap then
    becomes an analyst who ignores the -1 bucket, which is the realistic
    failure mode anyway.
    """
    rows = []
    for k, label in ((UNKNOWN_KEY, "UNKNOWN"), (NOT_APPLICABLE_KEY, "NOT_APPLICABLE")):
        r = {c: None for c in df.columns}
        r[key_col] = k
        for c, v in fill.items():
            r[c] = label
        rows.append(r)
    # Build the sentinel frame with the target dtypes already in place.
    # Concatenating an all-NA frame lets pandas re-infer dtypes and emits a
    # deprecation warning, so the columns are cast up front instead.
    special = pd.DataFrame(rows).astype(
        {c: df[c].dtype for c in df.columns if c != key_col and df[c].dtype == object}
    )
    return pd.concat([special, df], ignore_index=True)


# ---------------------------------------------------------------------- facts

def build_facts(dims: dict, t0) -> dict[str, pd.DataFrame]:
    out = {}

    xp = pd.read_csv(MART / "xwalk_patient.csv.gz", dtype=str,
                     keep_default_na=False, na_values=[""])
    ehr_x = xp[xp.source_system == "CARELINE_EHR"][
        ["source_patient_id", "master_person_id", "match_method", "match_score"]
    ].rename(columns={"source_patient_id": "mrn"})

    member = dims["dim_member"][["member_key", "member_id", "member_durable_key"]]
    prov_cur = dims["dim_provider_current"][["provider_key", "provider_master_id"]]

    # ---- claim lines
    L = read("raw_clm", "clm_claim_line")
    L = numeric(L, ["claim_line_key", "claim_line_number", "adjudication_seq",
                    "units", "billed_amount", "allowed_amount", "paid_amount",
                    "deductible_amount", "copay_amount", "coinsurance_amount",
                    "cob_amount", "contractual_writeoff_amount",
                    "paid_lag_days", "net_sign"])
    L = boolean(L, ["is_current_version", "is_reversal", "is_orphan_reversal",
                    "is_out_of_network"])

    L = L.merge(member, on="member_id", how="left")
    L["member_resolution_status"] = np.where(
        L["member_key"].notna(), "MATCHED", "ORPHAN_SOURCE_VALUE")
    L["member_key"] = L["member_key"].fillna(UNKNOWN_KEY).astype(int)

    # Servicing provider is where the orphan keys live, so the resolution
    # status here is the column that makes anomaly A12 countable.
    L = L.merge(
        prov_cur.rename(columns={"provider_key": "servicing_provider_key",
                                 "provider_master_id": "servicing_provider_master_id"}),
        on="servicing_provider_master_id", how="left")
    L["servicing_provider_resolution_status"] = np.select(
        [L["servicing_provider_master_id"].isna(),
         L["servicing_provider_key"].notna()],
        ["SOURCE_NULL", "MATCHED"], default="ORPHAN_SOURCE_VALUE")
    L["servicing_provider_key"] = L["servicing_provider_key"].fillna(
        UNKNOWN_KEY).astype(int)

    L["service_date_key"] = (
        pd.to_datetime(L["service_date"]).dt.strftime("%Y%m%d").astype(int))
    L["paid_date_key"] = (
        pd.to_datetime(L["paid_date"]).dt.strftime("%Y%m%d").astype(int))
    L["service_year_month"] = (
        pd.to_datetime(L["service_date"]).dt.strftime("%Y%m").astype(int))

    # ---- de-duplicate on the BUSINESS key, keeping the earliest load batch.
    # A uniqueness test on claim_line_key would have passed on the raw file:
    # the duplicates carry distinct surrogate keys. The business key is what
    # was violated, and it is what has to be de-duplicated on.
    before = len(L)
    L = L.sort_values(["claim_number", "claim_line_number", "adjudication_seq",
                       "source_load_batch_id"])
    L["_dupe_rank"] = L.groupby(
        ["claim_number", "claim_line_number", "adjudication_seq", "net_sign"]
    ).cumcount()
    dupes_removed = int((L["_dupe_rank"] > 0).sum())
    L = L[L["_dupe_rank"] == 0].drop(columns=["_dupe_rank"])
    print(f"    de-duplicated {dupes_removed:,} claim lines "
          f"({before:,} -> {len(L):,}) on the business key")
    out["fct_claim_line"] = L.reset_index(drop=True)

    # ---- claim headers
    H = read("raw_clm", "clm_claim_header")
    H = numeric(H, ["claim_header_key", "adjudication_seq", "line_count",
                    "total_billed_amount", "total_allowed_amount",
                    "total_claim_paid_amount", "length_of_stay_days", "net_sign"])
    H = boolean(H, ["is_current_version", "is_reversal", "is_orphan_reversal",
                    "is_out_of_network"])
    H = H.merge(member, on="member_id", how="left")
    H["member_key"] = H["member_key"].fillna(UNKNOWN_KEY).astype(int)
    H["service_year_month"] = (
        pd.to_datetime(H["service_from_date"]).dt.strftime("%Y%m").astype(int))
    out["fct_claim_header"] = H

    out["br_claim_diagnosis"] = read("raw_clm", "clm_claim_diagnosis")

    # ---- encounters, resolved through the crosswalk. THIS is the three-hop
    # join the hub exists to make possible, and it loses the unmatched share.
    E = read("raw_ehr", "ehr_encounter")
    E = numeric(E, ["length_of_stay_days"])
    E["encounter_type_conformed"] = E["encounter_type_source"].map(
        ENCOUNTER_TYPE_CONFORM).fillna("UNKNOWN")
    unmapped_types = sorted(
        set(E.loc[E["encounter_type_conformed"] == "UNKNOWN",
                  "encounter_type_source"].dropna().unique()))
    if unmapped_types:
        print(f"    encounter_type values with no mapping: {unmapped_types} "
              f"({(E['encounter_type_conformed'] == 'UNKNOWN').mean():.2%} of rows)")
    E = E.merge(ehr_x, on="mrn", how="left")
    E = E.rename(columns={"master_person_id": "member_durable_key"})
    # Survivorship: ONE surviving member_key per resolved person.
    #
    # The over-match collapses a handful of durable keys onto two member IDs,
    # so a plain join here fans an encounter out into two rows and quietly
    # breaks the grain of the fact. That is not what an over-match does in
    # reality - the encounter still happened once - so the crosswalk resolves
    # to the surviving record, lowest member_key, exactly as an MDM survivorship
    # rule would. The defect stays visible where it belongs, in the COST
    # distribution, without corrupting the encounter count on the way there.
    survivor = (dims["dim_member"][["member_key", "member_durable_key"]]
                .dropna(subset=["member_durable_key"])
                .sort_values("member_key")
                .drop_duplicates("member_durable_key", keep="first"))
    E = E.merge(survivor, on="member_durable_key", how="left")
    E["member_resolution_status"] = np.select(
        [E["match_method"] == "UNMATCHED", E["member_key"].notna()],
        ["UNMATCHED_IN_CROSSWALK", "MATCHED"], default="ORPHAN_SOURCE_VALUE")
    E["member_key"] = E["member_key"].fillna(UNKNOWN_KEY).astype(int)
    E["encounter_date_key"] = (
        pd.to_datetime(E["encounter_date"]).dt.strftime("%Y%m%d").astype(int))

    # Resolve the renumbered hospital through the facility crosswalk, so one
    # physical site does not split in two mid-2024.
    fx = read("raw_ref", "ref_facility_crosswalk")
    E = E.merge(fx[["ehr_dept_id", "facility_id", "site_code"]].rename(
        columns={"site_code": "resolved_site_code"}),
        on="ehr_dept_id", how="left")
    out["fct_encounter"] = E

    out["br_encounter_diagnosis"] = read("raw_ehr", "ehr_encounter_diagnosis")
    out["fct_lab_result"] = read("raw_ehr", "ehr_lab_result")

    # ---- referrals and the referral-outcome bridge
    R = read("raw_ehr", "ehr_referral_order")
    R = numeric(R, ["days_to_closure"])
    R = R.merge(ehr_x[["mrn", "master_person_id"]], on="mrn", how="left")
    R = R.rename(columns={"master_person_id": "member_durable_key"})
    R["placed_date_key"] = (
        pd.to_datetime(R["placed_date"]).dt.strftime("%Y%m%d").astype(int))
    out["fct_referral"] = R
    out["fct_referral_outcome"] = _referral_outcome(R, L, t0)

    out["fct_member_month"] = pd.read_csv(
        MART / "fct_member_month.csv.gz", dtype=str,
        keep_default_na=False, na_values=[""])
    out["fct_eligibility_span"] = read("raw_elig", "elig_eligibility_span")
    out["vbc_attribution_month"] = read("raw_vbc", "vbc_attribution_month")

    # The restatement delta belongs in the mart, not only in the landing zone.
    # It is the ONLY way to reconstruct an earlier roster version, so leaving
    # it upstream means every "what did we think in September" question turns
    # into a source-file archaeology exercise.
    out["vbc_attribution_restatement"] = read(
        "raw_vbc", "vbc_attribution_restatement")
    out["vbc_roster_version"] = read("raw_vbc", "vbc_roster_version")
    out["vbc_contract_terms"] = read("raw_vbc", "vbc_contract_terms")
    out["vbc_benchmark"] = read("raw_vbc", "vbc_benchmark")
    out["br_provider_affiliation"] = read("raw_ref", "ref_provider_affiliation")
    log(f"facts: {len(out)} tables", t0)
    return out


def _referral_outcome(R: pd.DataFrame, L: pd.DataFrame, t0) -> pd.DataFrame:
    """Referral to confirming event, as an auditable bridge table.

    Confirmation is a FIRST-CLASS modeled metric with a rule version on every
    row, not ad-hoc SQL in a workbook. Two independent confirmation sources
    are checked - a professional claim and a completed appointment - because
    if the only evidence were the claims join, the first skeptic blames the
    match rate and the finding dies.
    """
    window_days = 90
    appt = read("raw_pm", "pm_appointment")
    appt_ok = appt[appt["appointment_status"].isin(["COMPLETED", "ARRIVED"])]
    by_ref_appt = set(appt_ok["referral_id"].dropna())

    # Claim confirmation: a claim for that member at the destination site
    # within the window after the referral was placed.
    lc = L[["member_durable_key", "service_site_code", "service_date"]].dropna(
        subset=["member_durable_key"]).copy()
    lc["service_date"] = pd.to_datetime(lc["service_date"])
    r = R[["referral_id", "member_durable_key", "destination_site_code",
           "placed_date"]].dropna(subset=["member_durable_key"]).copy()
    r["placed_date"] = pd.to_datetime(r["placed_date"])
    j = r.merge(
        lc, left_on=["member_durable_key", "destination_site_code"],
        right_on=["member_durable_key", "service_site_code"], how="inner")
    j = j[(j["service_date"] >= j["placed_date"])
          & (j["service_date"] <= j["placed_date"] + pd.Timedelta(days=window_days))]
    by_ref_claim = set(j["referral_id"].unique())

    has_claim = R["referral_id"].isin(by_ref_claim)
    has_appt = R["referral_id"].isin(by_ref_appt)
    confirm_source = np.select(
        [has_claim & has_appt, has_claim, has_appt],
        ["BOTH", "CLAIM", "APPOINTMENT"], default="NONE")
    out = pd.DataFrame({
        "referral_id": R["referral_id"],
        "member_durable_key": R["member_durable_key"],
        "referring_site_code": R["referring_site_code"],
        "destination_site_code": R["destination_site_code"],
        "placed_date": R["placed_date"],
        "referral_status": R["referral_status"],
        "days_to_closure": R["days_to_closure"],
        "closure_actor_type": R["closure_actor_type"],
        "confirm_source": confirm_source,
        "is_confirmed": confirm_source != "NONE",
        "match_rule_version": f"v1-window{window_days}d",
        "confidence": np.select(
            [confirm_source == "BOTH", confirm_source == "CLAIM",
             confirm_source == "APPOINTMENT"],
            [0.99, 0.90, 0.80], default=0.0),
    })
    log(f"referral outcome bridge: {out['is_confirmed'].mean():.1%} confirmed", t0)
    return out


# ---------------------------------------------------------------------- serve

def build_serving(dims: dict, facts: dict, t0) -> dict[str, pd.DataFrame]:
    """One wide, bridge-free view that is safe to sum.

    Claim line joined to every type-1-ish dimension, one row per claim line,
    no bridges. This is what gets an analyst productive in five minutes. It is
    ONLY safe to sum because the diagnosis bridge was deliberately kept out of
    it - and saying that out loud during the demo is itself the lesson.
    """
    L = facts["fct_claim_line"]
    keep = [
        "claim_line_key", "claim_number", "claim_line_number", "adjudication_seq",
        "member_key", "member_durable_key", "member_id", "claim_type",
        "claim_role", "source_kind", "encounter_id", "service_date",
        "service_date_key", "service_year_month", "paid_date", "paid_lag_days",
        "service_site_code", "is_out_of_network", "procedure_code", "code_system",
        "service_category", "pos_code", "revenue_code", "modifier_1", "units",
        "servicing_provider_key", "servicing_provider_resolution_status",
        "billed_amount", "allowed_amount", "paid_amount", "deductible_amount",
        "copay_amount", "coinsurance_amount", "cob_amount",
        "contractual_writeoff_amount", "denial_code", "is_current_version",
        "is_reversal", "is_orphan_reversal", "net_sign", "source_load_batch_id",
    ]
    wide = L[[c for c in keep if c in L.columns]].copy()

    fac = dims["dim_facility"][["site_code", "facility_name", "facility_type",
                                "region", "service_line_group"]]
    wide = wide.merge(fac, left_on="service_site_code", right_on="site_code",
                      how="left").drop(columns=["site_code"])
    proc = dims["dim_procedure"][["procedure_code", "procedure_description"]]
    wide = wide.merge(proc, on="procedure_code", how="left")
    plan = facts["fct_member_month"][["member_id", "line_of_business"]].drop_duplicates(
        "member_id")
    wide = wide.merge(plan, on="member_id", how="left")
    log(f"serving view: {len(wide):,} rows, {len(wide.columns)} columns", t0)
    return {"vw_claim_line_enriched": wide}


# ------------------------------------------------- truncation and completeness

# Lag buckets beyond this are lumped into the tail. Paid lag is lognormal
# around a 23-day median, so development past a year is a handful of rows.
MAX_LAG_MONTHS = 12


def _month_diff(a: pd.Series, b: pd.Series) -> pd.Series:
    """Whole months between two YYYYMM integer series."""
    return (a // 100 - b // 100) * 12 + (a % 100 - b % 100)


def build_contract_layer(dims: dict, facts: dict, t0) -> dict[str, pd.DataFrame]:
    """High-cost truncation and the claims development triangle.

    Both of these were previously things an analyst had to re-derive in a
    workbook formula, which is exactly the fragmentation this project argues
    against: three analysts write three truncation thresholds and the hub has
    no opinion. Modeling them here makes them auditable and makes them tie.
    """
    out = {}
    L = facts["fct_claim_line"]
    terms = facts["vbc_contract_terms"]

    # ---- high-cost truncation, at member x performance year.
    #
    # Truncation is an ANNUAL, MEMBER-LEVEL cap: a contract caps what any one
    # member can contribute to the settlement so that a single catastrophic
    # case cannot decide a performance year. Applying it per claim line - the
    # obvious shortcut - caps nothing, because no single line reaches $100k.
    thresholds = {
        r.line_of_business: float(r.high_cost_truncation_threshold)
        for r in terms.drop_duplicates("line_of_business").itertuples()
    }
    lob = facts["fct_member_month"][
        ["member_id", "year_month", "line_of_business"]].copy()
    lob["performance_year"] = pd.to_numeric(lob["year_month"]) // 100
    lob = lob.drop_duplicates(["member_id", "performance_year"])[
        ["member_id", "performance_year", "line_of_business"]]

    cur = L[L["is_current_version"].fillna(False)].copy()
    cur["performance_year"] = cur["service_year_month"] // 100
    my = cur.groupby(
        ["member_id", "member_durable_key", "performance_year"], as_index=False
    ).agg(claim_lines=("claim_line_key", "size"),
          allowed_amount=("allowed_amount", "sum"),
          paid_amount=("paid_amount", "sum"))
    my = my.merge(lob, on=["member_id", "performance_year"], how="left")
    my["line_of_business"] = my["line_of_business"].fillna("COMMERCIAL")
    my["truncation_threshold"] = my["line_of_business"].map(thresholds).astype(float)
    my["allowed_amount_truncated"] = np.minimum(
        my["allowed_amount"], my["truncation_threshold"])
    my["truncation_excess"] = (
        my["allowed_amount"] - my["allowed_amount_truncated"]).round(2)
    my["is_truncated"] = my["truncation_excess"] > 0
    my["allowed_amount"] = my["allowed_amount"].round(2)
    my["allowed_amount_truncated"] = my["allowed_amount_truncated"].round(2)
    my["paid_amount"] = my["paid_amount"].round(2)
    my = my.sort_values(["member_id", "performance_year"]).reset_index(drop=True)
    my.insert(0, "member_year_cost_key", np.arange(1, len(my) + 1))
    out["fct_member_year_cost"] = my

    # ---- push the truncation back down to the line, pro rata.
    #
    # A member-year table cannot answer "truncated spend by month and site",
    # which is most of what a settlement workbook wants. Allocating the cap
    # proportionally across the member's lines for that year is a MODELING
    # CHOICE and is named as one: it spreads the excess evenly rather than
    # attributing it to the specific catastrophic claim. It has the property
    # that matters - the line column sums exactly to the member-year column.
    ratio = my[["member_id", "performance_year",
                "allowed_amount", "allowed_amount_truncated"]].copy()
    ratio["truncation_ratio"] = np.where(
        ratio["allowed_amount"] > 0,
        ratio["allowed_amount_truncated"] / ratio["allowed_amount"], 1.0)
    L["performance_year"] = L["service_year_month"] // 100
    L = L.merge(ratio[["member_id", "performance_year", "truncation_ratio"]],
                on=["member_id", "performance_year"], how="left")
    L["truncation_ratio"] = L["truncation_ratio"].fillna(1.0)
    L["allowed_amount_truncated"] = (
        L["allowed_amount"] * L["truncation_ratio"]).round(2)
    facts["fct_claim_line"] = L.drop(columns=["truncation_ratio"])
    n_trunc = int(my["is_truncated"].sum())
    log(f"truncation: {n_trunc:,} member-years capped, "
        f"${my['truncation_excess'].sum():,.0f} excess removed", t0)

    # ---- the claims development triangle.
    #
    # dim_date ships a claims_completeness_factor, but it was ASSERTED by the
    # generator rather than measured from the data. In a project whose whole
    # claim is that every figure is measured, a planted constant doing the most
    # consequential job on the page is the odd one out. This derives the same
    # factor by chain-ladder from the paid dates actually present, so the
    # runout control demonstrates its own completeness rather than trusting a
    # number somebody typed.
    tri = cur[["service_year_month", "paid_date", "allowed_amount",
               "paid_amount", "claim_line_key"]].copy()
    tri["paid_year_month"] = (
        pd.to_datetime(tri["paid_date"]).dt.strftime("%Y%m").astype(int))
    tri["lag_months"] = _month_diff(
        tri["paid_year_month"], tri["service_year_month"]).clip(0, MAX_LAG_MONTHS)
    grid = tri.groupby(["service_year_month", "lag_months"], as_index=False).agg(
        claim_lines=("claim_line_key", "size"),
        allowed_amount=("allowed_amount", "sum"),
        paid_amount=("paid_amount", "sum"))

    # Dense grid: a lag with no claims is a zero, not a missing row, or the
    # cumulative development is wrong wherever a month happens to be quiet.
    months = sorted(grid["service_year_month"].unique())
    full = pd.MultiIndex.from_product(
        [months, range(MAX_LAG_MONTHS + 1)],
        names=["service_year_month", "lag_months"]).to_frame(index=False)
    grid = full.merge(grid, on=["service_year_month", "lag_months"], how="left")
    grid[["claim_lines", "allowed_amount", "paid_amount"]] = grid[
        ["claim_lines", "allowed_amount", "paid_amount"]].fillna(0)
    grid = grid.sort_values(["service_year_month", "lag_months"])
    for c in ("claim_lines", "allowed_amount", "paid_amount"):
        grid[f"cumulative_{c}"] = grid.groupby("service_year_month")[c].cumsum()

    # A cell is observable only if its WHOLE development period had elapsed by
    # the paid-through date - the end of month (service month + lag), not its
    # start. This is the part that is easy to get wrong and silently ruinous:
    # counting a lag period the extract only half covers puts a partial month
    # of payments next to full ones, and the chain ladder then reads the
    # missing half as a real slowdown. It is the same error as trending a
    # measure to its right edge, one level down.
    paid_through = pd.Timestamp(C.PAID_THROUGH)
    abs_month = (grid["service_year_month"] // 100) * 12 + (
        grid["service_year_month"] % 100) - 1 + grid["lag_months"]
    lag_month_end = pd.to_datetime(pd.DataFrame({
        "year": abs_month // 12, "month": abs_month % 12 + 1, "day": 1,
    })) + pd.offsets.MonthEnd(0)
    grid["is_observable"] = lag_month_end <= paid_through

    grid["completion_factor_derived"] = _chain_ladder(grid)
    grid = grid.reset_index(drop=True)
    grid.insert(0, "lag_triangle_key", np.arange(1, len(grid) + 1))
    out["fct_claims_lag_triangle"] = grid

    # ---- hang the derived factor on dim_date beside the asserted one, so the
    # two can be compared rather than one silently replacing the other.
    ult = (grid[grid["is_observable"]]
           .sort_values(["service_year_month", "lag_months"])
           .groupby("service_year_month").tail(1)
           [["service_year_month", "completion_factor_derived"]])
    d = dims["dim_date"]
    d = d.merge(ult.rename(columns={"service_year_month": "year_month"}),
                on="year_month", how="left")
    # Months outside the claims window get 0.0, matching the convention the
    # asserted factor already uses. Filling them with 1.0 would state that a
    # month with no claims in it is fully developed, which reads as "complete"
    # to every filter on the page.
    first, last = min(months), max(months)
    inside = d["year_month"].between(first, last)
    d["completion_factor_derived"] = np.where(
        inside, d["completion_factor_derived"].fillna(1.0), 0.0).round(4)
    dims["dim_date"] = d
    log(f"lag triangle: {len(grid):,} cells over {len(months)} service months", t0)
    return out


def _chain_ladder(grid: pd.DataFrame) -> np.ndarray:
    """Completion factor at each lag, by age-to-age development factors.

    The standard actuarial construction, and it is the honest one: age-to-age
    factors are taken only over service months mature enough to have BOTH
    development periods observed, then chained backwards from ultimate. A
    factor computed across immature months measures the immaturity.
    """
    obs = grid[grid["is_observable"]]
    factors = {}
    for d in range(MAX_LAG_MONTHS):
        a = obs[obs["lag_months"] == d].set_index("service_year_month")[
            "cumulative_allowed_amount"]
        b = obs[obs["lag_months"] == d + 1].set_index("service_year_month")[
            "cumulative_allowed_amount"]
        both = a.index.intersection(b.index)
        denom = float(a.reindex(both).sum())
        factors[d] = float(b.reindex(both).sum()) / denom if denom > 0 else 1.0

    # Completion at lag d is the reciprocal of everything still to develop.
    completion = {}
    for d in range(MAX_LAG_MONTHS + 1):
        tail = 1.0
        for k in range(d, MAX_LAG_MONTHS):
            tail *= max(factors.get(k, 1.0), 1e-9)
        completion[d] = round(min(1.0 / tail, 1.0), 6)
    return grid["lag_months"].map(completion).to_numpy()


# ------------------------------------------------------------------ ASO layer

# Fee components whose denominator is CONTRACTS rather than lives. Keeping
# this as a set rather than a string comparison buried in an expression is
# deliberate: the PEPM/PMPM distinction is the single most consequential
# arithmetic decision in the ASO layer and it should be visible.
PEPM_FEE_CODES = {"ADMIN"}
FLAT_FEE_CODES = {"COBRA_ADMIN"}


def build_aso_layer(dims: dict, facts: dict, t0) -> dict[str, pd.DataFrame]:
    """The self-funded book: the client dimension, the contract, and the money.

    Everything here is at CLIENT grain, not group grain, and that distinction
    is the first thing this layer exists to enforce. An ASO contract is
    written with a client; the enrollment feed carries group ids; and one
    client in this book holds two group ids either side of an acquisition. A
    settlement rolled up by group_id reports that client as two clients and
    gets the fee, the denominator and the stop-loss accumulation wrong for
    both of them.
    """
    out = {}

    # ---- dim_employer_group. The group is the enrollment system's unit and
    # the client is the contract's, so both live on the row and the app can
    # join either way without re-deriving the mapping.
    grp = read("raw_elig", "elig_employer_group")
    grp = numeric(grp, ["enrollment_weight", "renewal_month"])
    grp = boolean(grp, ["is_acquired"])
    grp = grp.sort_values("group_id").reset_index(drop=True)
    grp.insert(0, "employer_group_key", np.arange(1, len(grp) + 1))
    out["dim_employer_group"] = _with_unknown_rows(
        grp, "employer_group_key", {"group_id": "UNKNOWN"})

    group_to_client = dict(zip(grp["group_id"], grp["client_id"]))
    aso_clients = set(grp[grp["funding_type"] == "ASO"]["client_id"])

    # ---- the contract layer, passed through and typed
    contract = numeric(read("raw_aso", "aso_client_contract"),
                       ["contract_year", "renewal_month",
                        "trend_assumption_pct", "margin_pct",
                        "expected_claims_pmpm",
                        "expected_claims_pmpm_on_true_denominator",
                        "prior_year_naive_member_months",
                        "prior_year_true_member_months"])
    out["aso_client_contract"] = contract
    fees = numeric(read("raw_aso", "aso_fee_schedule"),
                   ["contract_year", "fee_amount"])
    fees = boolean(fees, ["is_pass_through"])
    out["aso_fee_schedule"] = fees
    policy = numeric(read("raw_aso", "aso_stop_loss_policy"),
                     ["policy_year", "isl_deductible", "isl_coinsurance_pct",
                      "asl_attachment_factor", "asl_attachment_pmpm",
                      "asl_corridor_pct", "laser_deductible"])
    policy = boolean(policy, ["has_aggregate_stop_loss",
                              "asl_monthly_accommodation", "has_lasered_member"])
    out["aso_stop_loss_policy"] = policy
    rates = numeric(read("raw_aso", "aso_budget_rate"),
                    ["contract_year", "tier_factor", "budget_rate_pepm",
                     "projected_contract_months"])
    out["aso_budget_rate"] = rates

    # ---- both denominators, at client x month.
    #
    # The correct one comes from fct_member_month, which is the only sanctioned
    # PMPM denominator in this mart. The naive one re-derives what the
    # enrollment extract yields when spans are SUMMED rather than unioned, and
    # it is here because the renewal rate in aso_client_contract was set over
    # it. A layer that shipped only the right answer could assert the rate was
    # mispriced; shipping both lets the app subtract.
    mm = facts["fct_member_month"].copy()
    mm["year_month"] = pd.to_numeric(mm["year_month"])
    mm["member_months"] = pd.to_numeric(mm["member_months"])
    mm["client_id"] = mm["group_id"].map(group_to_client)
    spans = facts["fct_eligibility_span"]

    sys.path.insert(0, str(ROOT / "Generators"))
    import aso as ASO  # noqa: E402  - the naive denominator is defined once
    naive = ASO.naive_member_months(spans)
    naive["client_id"] = naive["group_id"].map(group_to_client)
    naive_mm = naive.groupby(["client_id", "year_month"], as_index=False).agg(
        naive_member_months=("naive_member_months", "sum"))

    members = dims["dim_member"][["member_id", "subscriber_id", "person_code"]]
    members = members[members["member_id"].notna()]
    tiers = ASO.coverage_tier_months(mm, members)
    tiers["client_id"] = tiers["group_id"].map(group_to_client)
    tier_mm = tiers.groupby(
        ["client_id", "year_month", "coverage_tier"], as_index=False).agg(
        subscriber_months=("subscriber_months", "sum"))
    out["fct_aso_contract_month"] = _contract_month(tier_mm, rates)

    denom = (
        mm.groupby(["client_id", "year_month"], as_index=False)
        .agg(member_months=("member_months", "sum"),
             members=("member_id", "nunique"))
        .merge(naive_mm, on=["client_id", "year_month"], how="outer")
        .merge(
            tier_mm.groupby(["client_id", "year_month"], as_index=False)
            .agg(subscriber_months=("subscriber_months", "sum")),
            on=["client_id", "year_month"], how="left")
    )
    denom = denom[denom["client_id"].notna()]

    # ---- claims at client x month, on an as-of join to the covering client
    L = facts["fct_claim_line"]
    asof = mm[["member_id", "year_month", "client_id"]].rename(
        columns={"year_month": "service_year_month"})
    cl = L.merge(asof, on=["member_id", "service_year_month"], how="left")
    cl["client_id"] = cl["client_id"].fillna("UNATTRIBUTED")
    claims = cl.groupby(
        ["client_id", "service_year_month"], as_index=False).agg(
        claim_lines=("claim_line_key", "size"),
        billed_amount=("billed_amount", "sum"),
        allowed_amount=("allowed_amount", "sum"),
        paid_claims_amount=("paid_amount", "sum"),
        deductible_amount=("deductible_amount", "sum"),
        copay_amount=("copay_amount", "sum"),
        coinsurance_amount=("coinsurance_amount", "sum"),
        cob_amount=("cob_amount", "sum"),
        contractual_writeoff_amount=("contractual_writeoff_amount", "sum"),
    ).rename(columns={"service_year_month": "year_month"})

    out["fct_aso_settlement_month"] = _settlement_month(
        denom, claims, contract, fees, policy, dims["dim_date"], aso_clients)
    out["fct_aso_stop_loss_claimant"] = _stop_loss_claimant(
        dims, policy, group_to_client)
    out["fct_aso_funding_week"] = _funding_week(cl, aso_clients)
    log(f"aso layer: {len(out)} tables, "
        f"{len(out['fct_aso_settlement_month']):,} client-months", t0)
    return out


def _contract_month(tier_mm: pd.DataFrame, rates: pd.DataFrame) -> pd.DataFrame:
    """Client x month x coverage tier: contract-months and the budget they carry.

    This is the PEPM denominator, and it is a table rather than a column
    because the tier is what the rate card is priced on. Summing
    budget_rate_pepm across tiers without weighting by contract-months is the
    other half of the fee arithmetic this layer is built to make hard to get
    wrong.
    """
    t = tier_mm.copy()
    t["contract_year"] = t["year_month"] // 100
    r = rates[["client_id", "contract_year", "coverage_tier", "tier_factor",
               "budget_rate_pepm"]]
    t = t.merge(r, on=["client_id", "contract_year", "coverage_tier"], how="left")
    t["budget_amount"] = (
        t["subscriber_months"] * t["budget_rate_pepm"]).round(2)
    t["subscriber_months"] = t["subscriber_months"].round(4)
    t = t.sort_values(["client_id", "year_month", "coverage_tier"])
    t = t.reset_index(drop=True)
    t.insert(0, "aso_contract_month_key", np.arange(1, len(t) + 1))
    return t


def _settlement_month(denom, claims, contract, fees, policy, date_dim,
                      aso_clients) -> pd.DataFrame:
    """Client x month. The table the app sits on.

    Every fee is billed on the denominator its own basis names. PEPM
    components multiply CONTRACT-months, PMPM components multiply
    MEMBER-months, and the flat components are charged once a month. That is
    the whole trick, and it is done here once so no workbook has to do it
    fifteen times and get it right fourteen.

    Net plan cost is stated the way a plan sponsor experiences it:

        paid claims
      - specific stop-loss reimbursement actually received
      + administration, network, care management and stop-loss premium

    Reimbursement RECEIVED rather than entitled, on purpose. A filing that
    was declined for late submission is money the client did not get, and a
    settlement built on entitlement quietly hands it back.
    """
    d = denom.copy()
    d = d[d["client_id"].isin(aso_clients)]
    df = d.merge(claims, on=["client_id", "year_month"], how="left")
    money = ["claim_lines", "billed_amount", "allowed_amount",
             "paid_claims_amount", "deductible_amount", "copay_amount",
             "coinsurance_amount", "cob_amount", "contractual_writeoff_amount"]
    df[money] = df[money].fillna(0.0)
    df["contract_year"] = df["year_month"] // 100

    # ---- fees, each on its own denominator.
    #
    # The effective date matters and is not decoration: two clients re-price
    # in July and October, so a fee joined on contract_year alone bills their
    # new rate from January. The join is therefore on the latest schedule row
    # effective on or before the month.
    f = fees.copy()
    f["eff_ym"] = (pd.to_datetime(f["effective_date"])
                   .dt.strftime("%Y%m").astype(int))
    pieces = []
    for code in sorted(f["fee_code"].unique()):
        sub = f[f["fee_code"] == code][["client_id", "eff_ym", "fee_basis",
                                        "fee_amount"]]
        m = df[["client_id", "year_month"]].merge(sub, on="client_id", how="left")
        m = m[m["eff_ym"] <= m["year_month"]]
        m = (m.sort_values(["client_id", "year_month", "eff_ym"])
             .groupby(["client_id", "year_month"], as_index=False).tail(1))
        m = m.rename(columns={"fee_amount": f"rate_{code}",
                              "fee_basis": f"basis_{code}"})
        pieces.append(m[["client_id", "year_month", f"rate_{code}",
                         f"basis_{code}"]])
    for pc in pieces:
        df = df.merge(pc, on=["client_id", "year_month"], how="left")

    fee_cols = []
    for code in sorted(f["fee_code"].unique()):
        rate = df[f"rate_{code}"].fillna(0.0)
        if code in PEPM_FEE_CODES:
            amt = rate * df["subscriber_months"].fillna(0.0)
        elif code in FLAT_FEE_CODES:
            amt = rate * (df["member_months"].fillna(0.0) > 0).astype(float)
        else:
            amt = rate * df["member_months"].fillna(0.0)
        df[f"fee_{code.lower()}_amount"] = amt.round(2)
        fee_cols.append(f"fee_{code.lower()}_amount")
    df["total_fee_amount"] = df[fee_cols].sum(axis=1).round(2)

    # The same admin fee billed on the WRONG denominator. Shipped as a column
    # rather than left to a workbook, because the point of the ASO layer is
    # that the error is measurable, not that it is avoidable.
    df["fee_admin_amount_on_member_months"] = (
        df["rate_ADMIN"].fillna(0.0) * df["member_months"].fillna(0.0)).round(2)

    # ---- stop-loss recoveries, by the month the claim was serviced
    recov = _isl_by_month(policy)
    df = df.merge(recov, on=["client_id", "year_month"], how="left")
    for c in ("isl_reimbursement_entitled_amount",
              "isl_reimbursement_received_amount", "isl_filings"):
        df[c] = df[c].fillna(0.0)

    # ---- budget and expected claims
    ct = contract[["client_id", "contract_year", "expected_claims_pmpm",
                   "expected_claims_pmpm_on_true_denominator", "rate_basis"]]
    df = df.merge(ct, on=["client_id", "contract_year"], how="left")
    df["expected_claims_amount"] = (
        df["expected_claims_pmpm"] * df["member_months"]).round(2)
    df["expected_claims_amount_repriced"] = (
        df["expected_claims_pmpm_on_true_denominator"]
        * df["member_months"]).round(2)

    df["member_liability_amount"] = (
        df["deductible_amount"] + df["copay_amount"]
        + df["coinsurance_amount"]).round(2)
    df["network_savings_amount"] = df["contractual_writeoff_amount"].round(2)
    df["net_plan_cost_amount"] = (
        df["paid_claims_amount"] - df["isl_reimbursement_received_amount"]
        + df["total_fee_amount"]).round(2)
    df["claims_variance_amount"] = (
        df["paid_claims_amount"] - df["expected_claims_amount"]).round(2)
    df["paid_claims_pmpm"] = np.where(
        df["member_months"] > 0,
        (df["paid_claims_amount"] / df["member_months"]).round(2), np.nan)
    df["paid_claims_pmpm_naive_denominator"] = np.where(
        df["naive_member_months"] > 0,
        (df["paid_claims_amount"] / df["naive_member_months"]).round(2), np.nan)
    df["net_plan_cost_pmpm"] = np.where(
        df["member_months"] > 0,
        (df["net_plan_cost_amount"] / df["member_months"]).round(2), np.nan)
    df["admin_load_pct"] = np.where(
        df["paid_claims_amount"] > 0,
        (100 * df["total_fee_amount"] / df["paid_claims_amount"]).round(2),
        np.nan)

    # ---- completeness. Same guardrail the VBC layer uses, same reason: a
    # paid-basis month at the right edge of the window is not a low month, it
    # is an incomplete one, and a client shown a favourable December will ask
    # why it reversed in March.
    dd = date_dim[["year_month", "completion_factor_derived",
                   "claims_runout_complete_flag"]].drop_duplicates("year_month")
    dd["year_month"] = pd.to_numeric(dd["year_month"])
    df = df.merge(dd, on="year_month", how="left")
    cf = pd.to_numeric(df["completion_factor_derived"], errors="coerce")
    df["incurred_estimate_amount"] = np.where(
        cf > 0, (df["paid_claims_amount"] / cf).round(2),
        df["paid_claims_amount"])
    df["ibnr_estimate_amount"] = (
        df["incurred_estimate_amount"] - df["paid_claims_amount"]).round(2)

    for c in ("member_months", "naive_member_months", "subscriber_months"):
        df[c] = df[c].round(4)
    df["member_month_overstatement"] = (
        df["naive_member_months"] - df["member_months"]).round(4)
    df["funding_type"] = "ASO"
    df = df.drop(columns=[c for c in df.columns if c.startswith("basis_")])
    df = df.sort_values(["client_id", "year_month"]).reset_index(drop=True)
    df.insert(0, "aso_settlement_month_key", np.arange(1, len(df) + 1))
    return df


def _isl_by_month(policy: pd.DataFrame) -> pd.DataFrame:
    """Specific stop-loss recoveries spread to the months that caused them.

    A filing is a POLICY-YEAR event and the settlement fact is monthly, so the
    recovery has to be allocated. It is spread evenly across the policy year's
    months, and that is a modeling choice rather than a truth: the honest
    attribution would follow the catastrophic claim to its own month, which
    the filing table does not carry. The property that matters holds - the
    monthly column sums to the filing exactly - and the filing table is there
    for anyone who needs the real timing.
    """
    fil = pd.read_csv(RAW / "raw_aso" / "aso_stop_loss_filing.csv.gz",
                      dtype=str, keep_default_na=False, na_values=[""])
    fil = numeric(fil, ["policy_year", "reimbursement_entitled_amount",
                        "reimbursement_received_amount"])
    pol = policy[["client_id", "policy_year", "policy_year_start_date",
                  "policy_year_end_date"]]
    fil = fil.merge(pol, on=["client_id", "policy_year"], how="left")
    rows = []
    for r in fil.itertuples():
        months = pd.period_range(r.policy_year_start_date,
                                 r.policy_year_end_date, freq="M")
        n = len(months)
        if not n:
            continue
        for pr in months:
            rows.append({
                "client_id": r.client_id,
                "year_month": int(pr.strftime("%Y%m")),
                "isl_reimbursement_entitled_amount":
                    r.reimbursement_entitled_amount / n,
                "isl_reimbursement_received_amount":
                    r.reimbursement_received_amount / n,
                "isl_filings": 1.0 / n,
            })
    if not rows:
        return pd.DataFrame(columns=[
            "client_id", "year_month", "isl_reimbursement_entitled_amount",
            "isl_reimbursement_received_amount", "isl_filings"])
    agg = pd.DataFrame(rows).groupby(
        ["client_id", "year_month"], as_index=False).sum()
    for c in ("isl_reimbursement_entitled_amount",
              "isl_reimbursement_received_amount"):
        agg[c] = agg[c].round(2)
    agg["isl_filings"] = agg["isl_filings"].round(4)
    return agg


def _stop_loss_claimant(dims, policy, group_to_client) -> pd.DataFrame:
    """Client x member x policy year, with the durable key on every row.

    The durable key is the point. A filing built on the resolved identity
    sums every member id behind one master person, and where the master data
    management run over-matched - twins, a Jr/Sr pair - that is two people on
    one stop-loss claim. Nothing in the filing announces it. Carrying
    member_durable_key beside member_id is what makes the collapse countable:
    a durable key with two member ids on a filing is the defect, and it is
    one join away rather than a source-file archaeology exercise.
    """
    fil = pd.read_csv(RAW / "raw_aso" / "aso_stop_loss_filing.csv.gz",
                      dtype=str, keep_default_na=False, na_values=[""])
    fil = numeric(fil, ["policy_year", "member_ids_rolled_up",
                        "isl_deductible", "effective_isl_deductible",
                        "isl_coinsurance_pct", "policy_year_paid_amount",
                        "covered_paid_amount", "amount_over_deductible",
                        "reimbursement_entitled_amount",
                        "reimbursement_received_amount"])
    fil = boolean(fil, ["is_lasered"])

    mem = dims["dim_member"][["member_key", "member_id", "member_durable_key",
                             "line_of_business", "risk_score"]]
    fil = fil.merge(mem, on="member_id", how="left")
    fil["member_key"] = fil["member_key"].fillna(UNKNOWN_KEY)
    fil["member_resolution_status"] = np.where(
        fil["member_durable_key"].notna(), "MATCHED", "ORPHAN_SOURCE_VALUE")

    # How many member ids the mart itself sees behind this durable key. Not a
    # flag saying "this is wrong" - a count, which is what the data supports.
    behind = (mem[mem["member_durable_key"].notna()]
              .groupby("member_durable_key", as_index=False)
              .agg(member_ids_on_durable_key=("member_id", "nunique")))
    fil = fil.merge(behind, on="member_durable_key", how="left")
    fil["member_ids_on_durable_key"] = (
        fil["member_ids_on_durable_key"].fillna(1).astype(int))

    fil["reimbursement_shortfall_amount"] = (
        fil["reimbursement_entitled_amount"]
        - fil["reimbursement_received_amount"]).round(2)
    fil["days_to_file"] = (
        pd.to_datetime(fil["filed_date"])
        - pd.to_datetime(fil["filing_deadline_date"])).dt.days
    fil["is_late_filing"] = fil["days_to_file"] > 0
    fil = fil.sort_values(["client_id", "policy_year", "member_id"])
    fil = fil.reset_index(drop=True)
    fil.insert(0, "aso_stop_loss_claimant_key", np.arange(1, len(fil) + 1))
    return fil


def _funding_week(cl: pd.DataFrame, aso_clients) -> pd.DataFrame:
    """Client x funding week: what was drawn, against what the mart holds.

    The request came off the adjudication extract as landed. This recomputes
    the same week from the DE-DUPLICATED mart and puts the two side by side.
    Where an extract was re-driven the client was funded for claim lines that
    do not exist, and the variance is the amount of real money that moved for
    no reason. A duplicate-row count in a data quality report does not make
    anyone act. A wire does.
    """
    req = pd.read_csv(RAW / "raw_aso" / "aso_funding_request.csv.gz",
                      dtype=str, keep_default_na=False, na_values=[""])
    req = numeric(req, ["claims_funded_amount", "claim_lines_funded",
                        "requested_amount", "wire_amount", "variance_amount",
                        "days_to_wire"])

    d = cl[cl["client_id"].isin(aso_clients)][
        ["client_id", "paid_date", "paid_amount", "claim_line_key"]].copy()
    d["paid"] = pd.to_datetime(d["paid_date"])
    offset = (d["paid"].dt.weekday - C.ASO_FUNDING_DAY_OF_WEEK) % 7
    d["funding_week_end"] = (
        d["paid"] + pd.to_timedelta(6 - offset, unit="D")).dt.date.astype(str)
    recon = d.groupby(["client_id", "funding_week_end"], as_index=False).agg(
        reconciled_paid_amount=("paid_amount", "sum"),
        reconciled_claim_lines=("claim_line_key", "size"))
    recon["reconciled_paid_amount"] = recon["reconciled_paid_amount"].round(2)

    out = req.merge(recon, on=["client_id", "funding_week_end"], how="left")
    out[["reconciled_paid_amount", "reconciled_claim_lines"]] = out[
        ["reconciled_paid_amount", "reconciled_claim_lines"]].fillna(0.0)
    out["overfunded_amount"] = (
        out["claims_funded_amount"] - out["reconciled_paid_amount"]).round(2)
    out["overfunded_claim_lines"] = (
        out["claim_lines_funded"] - out["reconciled_claim_lines"]).astype(int)
    out["funding_week_year_month"] = (
        pd.to_datetime(out["funding_week_end"]).dt.strftime("%Y%m").astype(int))
    out = out.sort_values(["client_id", "funding_week_end"])
    out = out.reset_index(drop=True)
    return out


def main() -> int:
    t0 = time.time()
    print("\nBuilding conformed and dimensional layer")
    dims = build_dimensions(t0)
    facts = build_facts(dims, t0)
    contract = build_contract_layer(dims, facts, t0)
    # The ASO layer runs after the contract layer because it consumes the
    # derived completion factor that layer hangs on dim_date.
    aso = build_aso_layer(dims, facts, t0)
    serve = build_serving(dims, facts, t0)

    entries = []
    for group in (dims, facts, contract, aso, serve):
        for name, df in group.items():
            entries.append(W.write_table(df, MART / f"{name}.csv.gz", name))
    total = sum(e["rows"] for e in entries)
    mb = sum(e["bytes_gzipped"] for e in entries) / 1e6
    print()
    print(f"Wrote {len(entries)} mart tables, {total:,} rows, {mb:,.1f} MB "
          f"in {time.time() - t0:.1f}s -> {MART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
