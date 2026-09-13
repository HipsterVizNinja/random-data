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
    E = E.merge(
        dims["dim_member"][["member_key", "member_durable_key"]].dropna(
            subset=["member_durable_key"]),
        on="member_durable_key", how="left")
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


def main() -> int:
    t0 = time.time()
    print("\nBuilding conformed and dimensional layer")
    dims = build_dimensions(t0)
    facts = build_facts(dims, t0)
    serve = build_serving(dims, facts, t0)

    entries = []
    for group in (dims, facts, serve):
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
