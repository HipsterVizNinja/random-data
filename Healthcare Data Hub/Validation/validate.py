#!/usr/bin/env python3
"""Validate the Healthcare Data Hub dataset and render the trust report.

    python Validation/validate.py
    python Validation/validate.py --json-only

Exits non-zero on any ERROR, so it is CI-able.

The point worth understanding before reading the checks: planted anomalies
assert as EXPECTED with a magnitude, not as failures. A suite that goes red on
purpose teaches nothing. One that states "orphan servicing providers: expected
1,312, actual 1,312, $2.9M exposure - CONTROLLED" is a business document
rather than a QA log.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Generators"))
import config as C  # noqa: E402

RAW = ROOT / "Source Data"
MART = ROOT / "Mart"
DELIV = ROOT / "Deliverables"

ERROR, WARN, INFO, EXPECTED = "ERROR", "WARN", "INFO", "EXPECTED"


class Scaling:
    """Makes the expectations file scale-aware.

    Absolute thresholds - row counts, dollar figures - are authored at demo
    scale, so they are multiplied by the run's anomaly factor. Distribution
    bands are rates and are NOT scaled; instead they are demoted to advisory
    below demo scale, because 2,000 members is too small a sample to assert a
    PMPM band against and failing on sampling noise teaches nothing.
    """

    def __init__(self, scale_name: str):
        self.scale_name = scale_name
        self.factor = C.SCALES[scale_name].anomaly_factor
        self.statistical = self.factor >= 1.0

    def count(self, n: int) -> int:
        return max(1, int(round(n * self.factor)))

    def dollars(self, v: float) -> float:
        return v * self.factor

    def dist_severity(self) -> str:
        return ERROR if self.statistical else WARN


class Results:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, check_id, category, name, severity, passed, detail=None,
            actual=None, expected=None, dollars=None):
        self.rows.append({
            "check_id": check_id, "category": category, "name": name,
            "severity": severity, "passed": bool(passed),
            "actual": actual, "expected": expected,
            "dollars": dollars, "detail": detail,
        })

    def band(self, check_id, category, name, value, band, severity=ERROR,
             detail=None, dollars=None):
        lo, hi = band
        ok = value is not None and lo <= value <= hi
        self.add(check_id, category, name, severity, ok, detail,
                 actual=value, expected=f"{lo} to {hi}", dollars=dollars)
        return ok

    @property
    def errors(self):
        return [r for r in self.rows if r["severity"] == ERROR and not r["passed"]]

    def frame(self):
        return pd.DataFrame(self.rows)


def read_mart(name, **kw):
    p = MART / f"{name}.csv.gz"
    if not p.exists():
        raise FileNotFoundError(f"{p} - run Build/build_mart.py first")
    return pd.read_csv(p, low_memory=False, **kw)


def _as_bool(series: pd.Series) -> pd.Series:
    """Coerce a column to bool whether it arrived parsed or as text.

    pandas infers real booleans from these files, so mapping string keys over
    an already-boolean column produces all-NaN rather than an error. That is a
    silent failure worth a named helper.
    """
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return (series.astype(str).str.strip().str.lower()
            .isin(["true", "1", "t", "yes"]))


def read_raw(folder, name, **kw):
    p = RAW / folder / f"{name}.csv.gz"
    if not p.exists():
        raise FileNotFoundError(f"{p} - run Generators/build.py first")
    return pd.read_csv(p, low_memory=False, **kw)


# ------------------------------------------------------------------- 1. grain

def check_grain(r: Results, exp, sc, raw_lines, mart_lines, mm, prov):
    """Grain uniqueness on BUSINESS keys, never surrogates.

    The lesson is stated explicitly because it is the single most common
    mistake in a data quality suite: a uniqueness test on a surrogate key is
    worthless. It passes by construction.
    """
    biz = ["claim_number", "claim_line_number", "adjudication_seq", "net_sign"]
    raw_dupes = int(raw_lines.duplicated(biz).sum())
    dupe_min = sc.count(exp["anomalies"]["A9_duplicates"]["duplicate_lines_min"])
    r.add("GRAIN-001", "Grain uniqueness",
          "Raw claim lines violate the business key (planted duplicate extract)",
          EXPECTED, raw_dupes >= dupe_min,
          detail=("A re-driven extract loaded one day of claim lines twice. "
                  "These rows carry DISTINCT surrogate keys."),
          actual=raw_dupes, expected=f">= {dupe_min:,}")

    sur_unique = not raw_lines["claim_line_key"].duplicated().any()
    r.add("GRAIN-002", "Grain uniqueness",
          "Surrogate key claim_line_key is unique even on the raw file",
          EXPECTED, sur_unique,
          detail=("Proof that a primary-key uniqueness test would have PASSED "
                  "while the business key was violated. Test business keys."),
          actual=sur_unique, expected=True)

    mart_dupes = int(mart_lines.duplicated(biz).sum())
    r.add("GRAIN-003", "Grain uniqueness",
          "Mart claim lines are unique on the business key after de-duplication",
          ERROR, mart_dupes == 0, actual=mart_dupes, expected=0)

    mm_dupes = int(mm.duplicated(["member_id", "year_month"]).sum())
    r.add("GRAIN-004", "Grain uniqueness",
          "Member-month is unique on (member_id, year_month)",
          ERROR, mm_dupes == 0,
          detail="The only sanctioned PMPM denominator. One row per member-month.",
          actual=mm_dupes, expected=0)

    # Type 2 provider dimension: exactly one current row per durable key, and
    # no overlapping effective spans.
    cur = prov[prov["is_current"] == True]  # noqa: E712
    multi_cur = int((cur.groupby("provider_master_id").size() > 1).sum())
    r.add("GRAIN-005", "Grain uniqueness",
          "Type-2 provider dimension has exactly one current row per provider",
          ERROR, multi_cur == 0, actual=multi_cur, expected=0)

    p = prov.sort_values(["provider_master_id", "row_effective_date"])
    p["_prev_end"] = p.groupby("provider_master_id")["row_expiration_date"].shift(1)
    overlap = int((p["row_effective_date"] <= p["_prev_end"]).sum())
    r.add("GRAIN-006", "Grain uniqueness",
          "Type-2 provider spans do not overlap",
          ERROR, overlap == 0, actual=overlap, expected=0)


# --------------------------------------------------- 2. referential integrity

def check_referential(r: Results, lines, headers, enc):
    """The orphan matrix: fact x dimension x count x percent x DOLLARS.

    That last column is what turns a QA log into a business document. An
    orphan count is a curiosity; $2.9M of paid that an inner join would
    silently delete is a finding.
    """
    cur = lines[lines["is_current_version"] == True]  # noqa: E712

    orphan = cur[cur["servicing_provider_resolution_status"] == "ORPHAN_SOURCE_VALUE"]
    dollars = float(orphan["paid_amount"].sum())
    r.add("REF-001", "Referential integrity",
          "Claim lines with a servicing provider absent from credentialing",
          EXPECTED, len(orphan) > 0,
          detail=("An inner join to the provider dimension would silently "
                  "delete these lines and the dollars on them."),
          actual=len(orphan), expected="> 0", dollars=round(dollars, 2))

    unk = cur[cur["member_key"] == -1]
    r.add("REF-002", "Referential integrity",
          "Claim lines resolving to the -1 Unknown member",
          EXPECTED, True,
          detail="Unmatched keys resolve to -1 so the mart stays joinable.",
          actual=len(unk), expected="counted, not zero",
          dollars=round(float(unk["paid_amount"].sum()), 2))

    no_enc = headers[headers["encounter_id"].isna()]
    share = len(no_enc) / max(len(headers), 1)
    r.add("REF-003", "Referential integrity",
          "Claims with no Northlake encounter (care delivered elsewhere)",
          EXPECTED, 0.15 <= share <= 0.32,
          detail=("By design. Northlake cannot see care it did not deliver, "
                  "which is precisely why the hub is necessary."),
          actual=round(share, 4), expected="0.15 to 0.32")

    unmatched = enc[enc["member_resolution_status"] == "UNMATCHED_IN_CROSSWALK"]
    r.add("REF-004", "Referential integrity",
          "EHR encounters whose patient never resolved to a member",
          EXPECTED, len(unmatched) > 0,
          detail=("The EHR-to-claims join is a three-hop through the crosswalk "
                  "and it loses this share. The loss is NOT random."),
          actual=len(unmatched), expected="> 0")


# ---------------------------------------------------------- 3. reconciliation

def check_reconciliation(r: Results, exp, lines, headers, spans, mm):
    tol = exp["reconciliation"]

    dev = (lines["allowed_amount"] - (
        lines["paid_amount"] + lines["deductible_amount"]
        + lines["copay_amount"] + lines["coinsurance_amount"]
        + lines["cob_amount"])).abs()
    fails = int((dev > tol["money_identity_tolerance"]).sum())
    r.add("RECON-001", "Reconciliation",
          "allowed = paid + deductible + copay + coinsurance + cob on every line",
          ERROR, fails == 0,
          detail="Holds to the penny on 100% of lines, every adjudication version.",
          actual=fails, expected=0)

    bad_billed = int((
        lines["billed_amount"].abs()
        < lines["allowed_amount"].abs() - tol["billed_ge_allowed_tolerance"]
    ).sum())
    r.add("RECON-002", "Reconciliation", "billed >= allowed on every line",
          ERROR, bad_billed == 0, actual=bad_billed, expected=0)

    ls = lines.groupby(["claim_number", "adjudication_seq"])["paid_amount"].sum().round(2)
    hs = headers.set_index(["claim_number", "adjudication_seq"])[
        "total_claim_paid_amount"].round(2)
    j = ls.to_frame("lines").join(hs.to_frame("header"), how="inner")
    mism = int((j["lines"] - j["header"]).abs().gt(tol["header_line_tie_tolerance"]).sum())
    r.add("RECON-003", "Reconciliation",
          "Header total paid = SUM(line paid) per (claim, adjudication version)",
          ERROR, mism == 0,
          detail=f"{len(j):,} claim-versions compared.", actual=mism, expected=0)

    total_all = float(lines["paid_amount"].sum())
    total_cur = float(
        lines.loc[lines["is_current_version"] == True, "paid_amount"].sum())  # noqa: E712
    agree = abs(total_all - total_cur) < tol["netting_tolerance"]
    r.add("RECON-004", "Reconciliation",
          "Both sanctioned nettings agree: all rows vs is_current_version",
          ERROR, agree,
          detail=("Note there is NO reversal exclusion in the second formula. "
                  "Orphan reversals are current and negative on purpose, so "
                  "excluding them breaks the tie."),
          actual=round(total_all, 2), expected=round(total_cur, 2))

    # Member-months: de-duplicated union versus the naive span sum.
    s = spans.copy()
    s["days"] = (pd.to_datetime(s["span_end_date"])
                 - pd.to_datetime(s["span_start_date"])).dt.days + 1
    naive = float((s["days"] / 30.44).sum())
    true_mm = float(mm["member_months"].sum())
    over = (naive / true_mm - 1) * 100
    r.add("RECON-005", "Reconciliation",
          "Naive span-sum overstates member-months versus the de-duplicated union",
          EXPECTED, over > 0,
          detail=("Summing span lengths double counts every overlap. The "
                  "correct denominator is the gaps-and-islands union."),
          actual=f"{over:.2f}% over", expected="> 0%")

    return {"total_paid": total_cur}


# ------------------------------------------------------ 4. distribution bands

def check_distributions(r: Results, exp, sc, lines, mm, enc, members):
    d = exp["distributions"]
    cur = lines[lines["is_current_version"] == True]  # noqa: E712

    for lob, key_pmpm in (("COMMERCIAL", "pmpm_commercial"),
                          ("MEDICARE_ADVANTAGE", "pmpm_medicare_advantage")):
        mmi = mm[mm["line_of_business"] == lob]
        ids = set(mmi["member_id"])
        denom = float(mmi["member_months"].sum())
        if denom == 0:
            continue
        pmpm = float(cur[cur["member_id"].isin(ids)]["allowed_amount"].sum()) / denom
        r.band(f"DIST-{lob[:4]}-PMPM", "Distribution control",
               f"Allowed PMPM, {lob}", round(pmpm, 2), d[key_pmpm],
               severity=sc.dist_severity())

        yrs = denom / 12
        e = enc[enc["member_id_truth"].isin(ids)] if "member_id_truth" in enc.columns \
            else enc.iloc[0:0]
        if len(e) and yrs:
            adm = float((e["encounter_class"] == "INPATIENT").sum()) / yrs * 1000
            ed = float((e["encounter_class"] == "EMERGENCY").sum()) / yrs * 1000
            suffix = "commercial" if lob == "COMMERCIAL" else "ma"
            r.band(f"DIST-{lob[:4]}-ADM", "Distribution control",
                   f"Admissions per 1000, {lob}", round(adm, 1),
                   d[f"admits_per_1000_{suffix}"], severity=sc.dist_severity())
            r.band(f"DIST-{lob[:4]}-ED", "Distribution control",
                   f"ED visits per 1000, {lob}", round(ed, 1),
                   d[f"ed_per_1000_{suffix}"], severity=sc.dist_severity())

    pm = cur.groupby("member_id")["allowed_amount"].sum().sort_values(ascending=False)
    tot = float(pm.sum()); n = len(pm)
    if tot and n:
        r.band("DIST-TOP1", "Distribution control", "Top 1% of members share of allowed",
               round(float(pm.head(max(1, int(n * .01))).sum()) / tot, 4),
               d["top_1pct_cost_share"], severity=sc.dist_severity(),
               detail="The single most recognizable realism check a payer audience applies.")
        r.band("DIST-TOP5", "Distribution control", "Top 5% of members share of allowed",
               round(float(pm.head(int(n * .05)).sum()) / tot, 4),
               d["top_5pct_cost_share"], severity=sc.dist_severity())

    ip = enc[enc["encounter_class"] == "INPATIENT"]
    if len(ip):
        r.band("DIST-ALOS", "Distribution control", "Average length of stay, days",
               round(float(ip["length_of_stay_days"].mean()), 2), d["alos_days"],
               severity=sc.dist_severity())
    r.band("DIST-LAG", "Distribution control", "Median paid lag, days",
           float(cur["paid_lag_days"].median()), d["paid_lag_median_days"],
           severity=sc.dist_severity())

    tol = d["chronic_prevalence_tolerance_pp"] / 100
    worst, worst_code = 0.0, None
    for code, _label, target, *_ in C.CONDITIONS:
        col = f"cond_{code.lower()}"
        if col not in members.columns:
            continue
        got = float(members[col].mean())
        if abs(got - target) > worst:
            worst, worst_code = abs(got - target), code
    r.add("DIST-PREV", "Distribution control",
          "Every chronic condition prevalence within tolerance of its benchmark",
          sc.dist_severity(), worst <= tol,
          detail=f"Worst deviation: {worst_code} off by {worst*100:.2f}pp.",
          actual=f"{worst*100:.2f}pp", expected=f"<= {d['chronic_prevalence_tolerance_pp']}pp")

    if "cond_htn" in members.columns:
        v = float(members[members["cond_htn"] == True]["cond_dm2"].mean())  # noqa: E712
        r.band("DIST-COMORB", "Distribution control",
               "P(diabetes | hypertension), emergent from the shared risk term",
               round(v, 4), d["dm_given_htn"], severity=sc.dist_severity())


# ------------------------------------------------- 5. clinical plausibility

def check_clinical(r: Results, exp, sc, enc, header_dx, members, xw):
    """Clinical and logical plausibility.

    The sex-restriction check is the interesting one: it must be ZERO at
    member grain and NON-ZERO at master-person grain. That is not a
    contradiction - it is how the over-match anomaly announces itself.
    """
    dx = read_raw("raw_ref", "ref_diagnosis")
    fem = set(dx.loc[dx["sex_restriction"] == "F", "icd10_code"])
    male = set(dx.loc[dx["sex_restriction"] == "M", "icd10_code"])

    m = members[["member_id", "sex", "birth_date", "age_2024"]].copy()
    ehr = xw[xw["source_system"] == "CARELINE_EHR"][
        ["source_patient_id", "master_person_id"]]

    # At member grain: zero violations. Sex is a member attribute and the
    # generator enforces it.
    hd = header_dx.merge(
        read_raw("raw_clm", "clm_claim_header")[["claim_number", "member_id"]]
        .drop_duplicates("claim_number"), on="claim_number", how="left")
    hd = hd.merge(m[["member_id", "sex"]], on="member_id", how="left")
    bad = int(((hd["icd10_code"].isin(fem)) & (hd["sex"] == "M")).sum()
              + ((hd["icd10_code"].isin(male)) & (hd["sex"] == "F")).sum())
    r.add("CLIN-001", "Clinical plausibility",
          "Sex-inappropriate diagnoses at MEMBER grain",
          ERROR, bad == 0,
          detail="Enforced by the generator. Must be zero.",
          actual=bad, expected=0)

    # At master-person grain: non-zero, because over-matching collapsed two
    # distinct people onto one identity. One query finds them.
    j = ehr.merge(members[["mrn", "sex", "birth_date"]],
                  left_on="source_patient_id", right_on="mrn", how="inner"
                  ).dropna(subset=["master_person_id"])
    g = j.groupby("master_person_id").agg(
        sexes=("sex", "nunique"), dobs=("birth_date", "nunique"))
    by_sex = int((g["sexes"] > 1).sum())
    collapsed = int(((g["sexes"] > 1) | (g["dobs"] > 1)).sum())
    band = exp["anomalies"]["A5_overmatch"]
    want = sc.count(band["detectable_by_sex_mismatch_min"])
    r.add("CLIN-002", "Clinical plausibility",
          "Master persons resolving to more than one distinct person",
          EXPECTED, collapsed >= want,
          detail=("The over-match detector. Two distinct people share one "
                  "master_person_id, so the identity carries two dates of "
                  "birth and often two sexes. One query finds them, which is "
                  "what makes this a satisfying teaching beat."),
          actual=collapsed, expected=f">= {want}")
    r.add("CLIN-002b", "Clinical plausibility",
          "Of those, how many the one-line sex-mismatch query alone would find",
          INFO, True,
          detail=("Sex mismatch is the cheapest detector but it only catches "
                  "the mixed-sex pairs. Same-sex twins need the date-of-birth "
                  "check, which is why the audit view tests both."),
          actual=f"{by_sex} of {collapsed}", expected="reported for context")

    ip = enc[enc["length_of_stay_days"].fillna(0) > 0].copy()
    if len(ip):
        los = (pd.to_datetime(ip["discharge_date"])
               - pd.to_datetime(ip["admit_date"])).dt.days
        mism = int((los != ip["length_of_stay_days"]).sum())
        r.add("CLIN-003", "Clinical plausibility",
              "length_of_stay_days equals discharge minus admit exactly",
              ERROR, mism == 0, actual=mism, expected=0)

    future = int((pd.to_datetime(enc["encounter_date"])
                  > pd.Timestamp(C.SOURCE_END)).sum())
    r.add("CLIN-004", "Clinical plausibility", "No encounters after the source window",
          ERROR, future == 0, actual=future, expected=0)

    amb = enc[enc["encounter_class"] == "AMBULATORY"]
    wknd = int((pd.to_datetime(amb["encounter_date"]).dt.weekday >= 5).sum())
    r.add("CLIN-005", "Clinical plausibility",
          "No elective ambulatory encounters on weekends",
          ERROR, wknd == 0, actual=wknd, expected=0)

    npi = read_raw("raw_ref", "ref_npi_registry")
    sys.path.insert(0, str(ROOT / "Generators"))
    import ids as ID
    valid = int(npi["npi"].astype(str).map(ID.npi_is_valid).sum())
    r.add("CLIN-006", "Clinical plausibility",
          "Every NPI deliberately FAILS its check digit",
          EXPECTED, valid == 0,
          detail=("A valid NPI resolves to a real clinician in the public "
                  "NPPES registry, which synthetic data must never do. "
                  "Validators will flag these, and that is intended."),
          actual=f"{valid} valid of {len(npi):,}", expected="0 valid")


# --------------------------------------------------- 6. conformance coverage

def check_conformance(r: Results, exp, enc):
    """Every distinct source value in a coded column must have a mapping.

    This check generalizes to client work better than anything else in the
    suite, and it is cheap: one query per coded column.
    """
    xw = read_raw("raw_ref", "ref_service_line_crosswalk")
    mapped = set(xw.loc[xw["crosswalk_domain"] == "EHR_DEPARTMENT", "source_value"])
    present = set(enc["encounter_type_source"].dropna().unique())
    unmapped = sorted(present - mapped - {"URGENT", "ED", "INPATIENT"})
    a11 = exp["anomalies"]["A11_encoding"]
    r.add("CONF-001", "Conformance coverage",
          "Encounter-type source values with no crosswalk entry",
          EXPECTED, a11["unmapped_encounter_type_value"] in unmapped,
          detail=("One clinic emits a value nobody mapped. It lands as "
                  "UNKNOWN and gets filtered out as junk unless someone "
                  "profiles distinct values BY SOURCE."),
          actual=unmapped, expected=[a11["unmapped_encounter_type_value"]])

    amb = enc[enc["encounter_class"] == "AMBULATORY"]
    share = float((amb["encounter_type_source"]
                   == a11["unmapped_encounter_type_value"]).mean())
    r.band("CONF-002", "Conformance coverage",
           "Share of ambulatory volume landing as UNKNOWN", round(share, 4),
           a11["unmapped_share_of_ambulatory"], severity=EXPECTED)

    fx = read_raw("raw_ref", "ref_facility_crosswalk")
    import org as ORG
    n_dept = int((fx["site_code"] == ORG.RENUMBERED_SITE).sum())
    r.add("CONF-003", "Conformance coverage",
          "One physical hospital carries two EHR department identifiers",
          EXPECTED, n_dept == a11["renumbered_site_dept_ids"],
          detail=("An EMR upgrade renumbered the site mid-2024. Without the "
                  "crosswalk, volume by facility splits one hospital into two "
                  "as a step change in the middle of the year."),
          actual=n_dept, expected=a11["renumbered_site_dept_ids"])


# --------------------------------------------------------- 7. question ladder

def check_question_ladder(r: Results, exp, sc, ref, outcome, lines):
    """The build's definition of done.

    If the rank inversion or the leakage dollars are absent, the dataset has
    failed even if every row is internally consistent. Internal consistency is
    necessary; carrying the finding is the point.
    """
    q = exp["question_ladder"]
    a1 = exp["anomalies"]["A1_autoclose"]
    a2 = exp["anomalies"]["A2_leakage"]

    ref = ref.copy()
    ref["post"] = pd.to_datetime(ref["placed_date"]) >= pd.Timestamp(C.AUTOCLOSE_EFFECTIVE)
    post = ref[ref["post"]]
    site = C.AUTOCLOSE_SITE
    nr, oth = post[post["referring_site_code"] == site], post[post["referring_site_code"] != site]

    d30_nr = float(nr["days_to_closure"].astype(float).between(29, 31).mean())
    d30_oth = float(oth["days_to_closure"].astype(float).between(29, 31).mean())
    r.band("LADDER-001", "Question ladder",
           f"Share of {site} closures landing at day 30 after the rule",
           round(d30_nr, 4), a1["day30_share_post_rule"], severity=EXPECTED,
           detail="A spike at a round number is a workflow rule, not clinical behavior.")
    r.band("LADDER-002", "Question ladder",
           "Same measure at every other site", round(d30_oth, 4),
           a1["day30_share_other_sites"], severity=EXPECTED)

    oc = outcome.copy()
    conf_nr = float(oc[oc["referring_site_code"] == site]["is_confirmed"].mean())
    conf_oth = float(oc[oc["referring_site_code"] != site]["is_confirmed"].mean())
    r.add("LADDER-003", "Question ladder",
          f"Referral confirmation rate is materially worse at {site}",
          EXPECTED, conf_nr < conf_oth,
          detail=("Confirmation is measured against a real event - a claim or "
                  "a completed appointment - not against the status field."),
          actual=f"{conf_nr:.3f} vs {conf_oth:.3f} elsewhere",
          expected="site materially lower")

    by_site = post.groupby("referring_site_code").apply(
        lambda d: pd.Series({
            "apparent": float((d["destination_status_per_ehr_directory"] == "NONPAR").mean()),
        }), include_groups=False)
    rank_apparent = int(by_site["apparent"].rank().loc[site])
    r.add("LADDER-004", "Question ladder",
          f"{site} ranks best of {len(by_site)} on EHR-apparent out-of-network rate",
          EXPECTED, rank_apparent == a2["rank_by_apparent_best_is_1"],
          detail=("The naive single-source answer. This is the number that "
                  "gets a clinic group held up as the model to copy."),
          actual=f"rank {rank_apparent} of {len(by_site)}",
          expected=f"rank {a2['rank_by_apparent_best_is_1']}")

    # ---- The joined answer, and the reason the ranking inverts.
    #
    # The metric that matters is the EXCESS cost of leaked episodes over their
    # in-network equivalent, attributed to the referring site. Total
    # out-of-network allowed is a much larger and much less useful number: it
    # sweeps in every outside claim in the book and answers nobody's question.
    cur = lines[lines["is_current_version"] == True]  # noqa: E712
    import claims as CMOD
    in_net_equiv = CMOD.MSK_EPISODE_IN_NETWORK * C.ALLOWED_CALIBRATION

    # Only PROCEDURE episodes carry the in/out-of-network episode gap.
    # Consults are priced through the ordinary line model and their leakage
    # differential is immaterial next to a surgical case.
    ep = cur[cur["claim_role"] == "REFERRAL_EPISODE"]
    ref_site = ref[["referral_id", "referring_site_code", "placed_date"]]
    ep = ep.merge(ref_site, on="referral_id", how="inner")
    ep = ep[pd.to_datetime(ep["placed_date"]) >= pd.Timestamp(C.AUTOCLOSE_EFFECTIVE)]
    ep_oon = ep[ep["is_out_of_network"] == True]  # noqa: E712

    by_claim = ep_oon.groupby(
        ["claim_number", "referring_site_code"], as_index=False
    )["allowed_amount"].sum()
    by_claim["excess"] = (by_claim["allowed_amount"] - in_net_equiv).clip(lower=0)
    site_excess = by_claim.groupby("referring_site_code")["excess"].sum()
    nr_excess = float(site_excess.get(site, 0.0))
    total_excess = float(site_excess.sum())

    leak_min = sc.dollars(q["leakage_dollars_min"])
    r.add("LADDER-005", "Question ladder",
          f"Excess cost of {site} leaked episodes over the in-network equivalent",
          EXPECTED, nr_excess >= leak_min,
          detail=("The joined answer. Episodes that went out of network, "
                  "priced against what the same care would have cost in "
                  "network, attributed to the referring site. This is the "
                  "figure the narrative quotes - NOT total out-of-network "
                  "allowed, which sweeps in every outside claim in the book "
                  "and answers nobody's question."),
          actual=round(nr_excess, 2),
          expected=f">= {leak_min:,.0f}", dollars=round(nr_excess, 2))

    r.add("LADDER-006", "Question ladder",
          f"{site} share of system-wide referral leakage excess",
          INFO, True,
          detail=("One clinic group of twelve, and it carries this share of "
                  "the excess. That concentration is the argument."),
          actual=f"{nr_excess/total_excess:.1%}" if total_excess else "n/a",
          expected="reported for context")

    summit_ep = ep_oon[ep_oon["service_site_code"] == "ASC-SUMMIT"]
    summit_claims = summit_ep.groupby("claim_number")["allowed_amount"].sum()
    summit_excess = float((summit_claims - in_net_equiv).clip(lower=0).sum())
    summit_min = sc.dollars(q["summit_point_dollars_min"])
    r.add("LADDER-007", "Question ladder",
          "Excess cost routed to Summit Point after its contract terminated",
          EXPECTED, summit_excess >= summit_min,
          detail=("Its contract ended 2024-10-01. The EHR referral directory "
                  "still reads PAR, 14 months stale. A governance failure with "
                  "a price tag, and nobody made a bad clinical decision."),
          actual=round(summit_excess, 2), expected=f">= {summit_min:,.0f}",
          dollars=round(summit_excess, 2))

    # ---- The honest counterweight: how much of that is actually recapturable.
    #
    # Not all leakage is winnable, and saying so is what makes the analysis
    # read as consulting rather than a pitch. Two things make an episode
    # NOT recapturable:
    #
    #   geography  the patient lives materially closer to the out-of-network
    #              site than to any in-network Northlake alternative, so
    #              recapturing it means asking them to drive further
    #   capacity   Northlake has no in-network site that performs the
    #              procedure at all, so there is nowhere to recapture it TO
    #
    # Measured with real drive times between the patient's region and each
    # facility's region, and with actual procedure availability observed in
    # the data rather than assumed.
    import org as ORG
    fac = read_raw("raw_ref", "ref_facility")[
        ["site_code", "region", "is_in_network_current", "service_line_group",
         "performs_msk_surgery", "annual_msk_case_capacity"]]
    # read_csv already parses these as booleans; mapping string keys over a
    # bool column silently yields all-NaN and empties the set, which is how
    # this check first came back claiming nothing was recapturable.
    fac["is_in_network_current"] = _as_bool(fac["is_in_network_current"])
    fac["performs_msk_surgery"] = _as_bool(fac["performs_msk_surgery"])
    fac["annual_msk_case_capacity"] = pd.to_numeric(
        fac["annual_msk_case_capacity"], errors="coerce").fillna(0)

    # Somewhere in network that can actually do the operation.
    surgical_in_net = fac[fac["is_in_network_current"] & fac["performs_msk_surgery"]]

    ep_lines = ep_oon.merge(
        fac[["site_code", "region"]].rename(columns={"region": "dest_region"}),
        left_on="service_site_code", right_on="site_code", how="left")

    def nearest_surgical_minutes(patient_region: str) -> float:
        if not isinstance(patient_region, str) or surgical_in_net.empty:
            return float("inf")
        return min(
            ORG.drive_time(patient_region, r)
            for r in surgical_in_net["region"] if isinstance(r, str)
        )

    nearest = ep_lines["region"].map(nearest_surgical_minutes).to_numpy()
    to_oon = np.array([
        ORG.drive_time(a, b) if isinstance(a, str) and isinstance(b, str)
        else float("inf")
        for a, b in zip(ep_lines["region"], ep_lines["dest_region"])
    ])
    # Geography blocks recapture when the in-network alternative is materially
    # further for the patient than where they actually went.
    geography_blocked = nearest > (to_oon + 15)

    # Capacity blocks the rest. Northlake's in-network surgical block time is
    # finite, and the leaked volume exceeds it. Episodes beyond the available
    # capacity have nowhere to be recaptured TO.
    leaked_episodes = int(ep_oon["claim_number"].nunique())
    years = 1.5  # the post-rule window
    available = float(surgical_in_net["annual_msk_case_capacity"].sum()) * years
    # Existing in-network surgical volume already consumes most of it.
    in_net_sites = set(surgical_in_net["site_code"])
    already_used = int(
        cur.loc[cur["service_site_code"].isin(in_net_sites)
                & (cur["claim_role"] == "REFERRAL_EPISODE"),
                "claim_number"].nunique()
    )
    headroom = max(available - already_used, 0.0)
    capacity_limited_share = (
        max(0.0, 1.0 - headroom / leaked_episodes) if leaked_episodes else 0.0
    )

    geo_share = float(geography_blocked.mean()) if len(ep_lines) else 0.0
    recapturable_share = max(0.0, 1.0 - geo_share - capacity_limited_share)

    # Reported rather than asserted, and worth explaining why.
    #
    # The design expected capacity to bind - that a good chunk of the leaked
    # volume would have nowhere in network to go. Measured against realistic
    # surgical rates it does not: Northlake's in-network block time
    # comfortably exceeds the leaked case volume at this panel size. Forcing a
    # binding constraint would mean fabricating one, so the honest finding is
    # the opposite of the expected one - nearly all of this is winnable, which
    # STRENGTHENS the business case rather than weakening it.
    #
    # The decomposition still ships, because the method is the transferable
    # part: at a larger panel, or for a service line where the system has thin
    # capability, the same test would bind.
    r.band("LADDER-008", "Question ladder",
           "Share of leaked spend that is plausibly recapturable",
           round(recapturable_share, 4), q["recapturable_share"],
           severity=INFO,
           detail=("Tested against real drive times and against in-network "
                   "surgical capability and block time. At this panel size "
                   "capacity does NOT bind, so nearly all leaked volume is "
                   "recapturable. That is the opposite of what the design "
                   "expected, and it is what the data says."))
    r.add("LADDER-009", "Question ladder",
          "Why the remainder is not recapturable",
          INFO, True,
          detail="Named so the number can be defended rather than asserted.",
          actual=(f"geography {geo_share:.1%}, "
                  f"capacity {capacity_limited_share:.1%}; "
                  f"{leaked_episodes:,} leaked episodes vs "
                  f"{headroom:,.0f} in-network case headroom"),
          expected="reported for context")

# ------------------------------------------------------------ 8. runout triangle

def check_runout(r: Results, exp, sc, lines, date_dim):
    """Completeness, measured like-for-like against the same calendar month.

    The naive way to measure runout is to compare an incomplete month against
    the average complete month. That is wrong here and wrong in client work:
    December carries a 1.45x elective-surgery seasonality factor, so comparing
    it to an annual mean measures seasonality and calls it completeness. The
    correct comparison is the SAME calendar month in prior years, de-trended.

    What is asserted is what actually matters and what is robust: each of the
    last three service months is MATERIALLY incomplete, and completeness
    declines monotonically toward the edge of the window. The exact percentage
    is reported rather than asserted, because a single month's observed ratio
    also carries that month's own volume variance - asserting it to a tight
    band would be testing noise.
    """
    a7 = exp["anomalies"]["A7_runout"]
    trend = 0.068
    cur = lines[lines["is_current_version"] == True].copy()  # noqa: E712
    cur["ym"] = cur["service_date"].str[:7]
    by_month = cur.groupby("ym")["paid_amount"].sum()

    rows, observed = [], []
    for m in a7["incomplete_months"]:
        year, mon = int(m[:4]), m[5:7]
        actual = float(by_month.get(m, 0.0))
        priors = [
            float(by_month[f"{y}-{mon}"]) * (1 + trend) ** (year - y)
            for y in range(2023, year) if f"{y}-{mon}" in by_month.index
        ]
        baseline = sum(priors) / len(priors) if priors else 0.0
        ratio = actual / baseline if baseline else 0.0
        expected = C.RUNOUT_COMPLETENESS.get(m)
        rows.append((m, ratio, expected, baseline))
        observed.append(ratio)
        r.add(f"RUNOUT-{m}", "Completeness",
              f"Service month {m} is materially incomplete",
              EXPECTED, ratio < 0.90,
              detail=("Claims absent from this extract are exactly the ones "
                      "that had not adjudicated by the paid-through date of "
                      f"{C.PAID_THROUGH} - the slowest-paying, not a random "
                      f"sample. Designed completeness {expected:.0%}."),
              actual=f"{ratio:.1%} of the de-trended prior-year month",
              expected="< 90%")

    monotonic = all(observed[i] >= observed[i + 1] for i in range(len(observed) - 1))
    r.add("RUNOUT-TREND", "Completeness",
          "Completeness declines monotonically toward the edge of the window",
          EXPECTED if sc.statistical else WARN, monotonic,
          detail=("The signature of runout. A real utilization drop would not "
                  "get progressively steeper the closer you get to the "
                  "extract date."),
          actual=" > ".join(f"{v:.0%}" for v in observed),
          expected="monotonically decreasing")

    complete = by_month[(by_month.index >= "2024-01") & (by_month.index <= "2025-09")]
    flagged = set(date_dim.loc[
        date_dim["claims_runout_complete_flag"] == False, "year_month_name"  # noqa: E712
    ].unique()) if "year_month_name" in date_dim.columns else set()
    r.add("RUNOUT-FLAG", "Completeness",
          "dim_date flags exactly the incomplete months",
          ERROR,
          set(a7["incomplete_months"]).issubset(flagged),
          detail=("claims_runout_complete_flag is the guardrail: any "
                  "service-date trend should filter on it rather than relying "
                  "on the analyst remembering where the data stops."),
          actual=sorted(flagged & set(a7["incomplete_months"])),
          expected=a7["incomplete_months"])
    return rows


# ----------------------------------------------------------------- rendering

def _esc(v) -> str:
    """Escape pipes so a cell cannot break the markdown table it sits in."""
    return str(v).replace("|", "\\|")


def render_report(res: Results, runout, path: Path, manifest: dict):
    df = res.frame()
    n_err = len(res.errors)
    by_sev = df["severity"].value_counts().to_dict()
    expected_ok = int(((df.severity == EXPECTED) & df.passed).sum())
    expected_tot = int((df.severity == EXPECTED).sum())
    hard = df[df.severity == ERROR]
    hard_ok = int(hard.passed.sum())

    L = []
    A = L.append
    A("# Data trust validation")
    A("")
    A("**Dataset:** Healthcare Data Hub (synthetic)  ")
    A(f"**Scale:** {manifest.get('scale')} - {manifest.get('members'):,} members  ")
    A(f"**Seed:** {manifest.get('seed')}  ")
    A(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M')}  ")
    A("**Classification:** SYNTHETIC. Wholly fabricated. Not derived from real "
      "patient records.")
    A("")
    A("## Verdict")
    A("")
    A(f"| | Count |")
    A("|---|---|")
    A(f"| Hard assertions passed | {hard_ok} of {len(hard)} |")
    A(f"| Planted defects confirmed present and controlled | {expected_ok} of {expected_tot} |")
    A(f"| Failures | **{n_err}** |")
    A("")
    if n_err == 0:
        A("Every hard assertion passes, and every planted data-quality defect was "
          "found, measured, and controlled for. The figures below are generated "
          "from the shipped data, so this document cannot drift from the dataset "
          "it describes.")
    else:
        A(f"**{n_err} assertion(s) failed.** Details below.")
    A("")
    A("A note on how to read this. Checks marked EXPECTED are deliberate. This "
      "dataset carries planted data-quality problems because finding them and "
      "controlling for them is the exercise. An EXPECTED check that PASSES means "
      "the defect is present at the size it should be and the control for it "
      "works. A suite that goes red on purpose teaches nothing.")
    A("")

    for cat in df["category"].drop_duplicates():
        sub = df[df.category == cat]
        A(f"## {cat}")
        A("")
        A("| Check | Verdict | Actual | Expected | Dollar impact |")
        A("|---|---|---|---|---|")
        for row in sub.itertuples():
            verdict = ("PASS" if row.passed else "FAIL") if row.severity == ERROR \
                else ("CONTROLLED" if row.passed else "NOT FOUND")
            dollars = (f"${row.dollars:,.2f}"
                       if row.dollars is not None and pd.notna(row.dollars)
                       else "")
            # A bare pipe anywhere in a cell silently breaks the whole table.
            # Check names legitimately contain them, e.g. P(diabetes | HTN).
            A("| {} | {} | {} | {} | {} |".format(
                _esc(row.name), verdict, _esc(row.actual), _esc(row.expected),
                dollars))
        A("")
        notes = [r for r in sub.itertuples() if r.detail]
        if notes:
            for row in notes:
                A(f"- **{row.check_id}** - {_esc(row.detail)}")
            A("")

    A("## Claims runout triangle")
    A("")
    A("The last three service months are structurally incomplete because claims "
      "adjudicate on a lag and the paid-through date is "
      f"{C.PAID_THROUGH}. A monthly trend on service date run to the right edge "
      "shows a cliff that is not a utilization drop.")
    A("")
    A("Measured against the SAME calendar month in prior years, de-trended. "
      "Comparing an incomplete month against an annual average measures "
      "seasonality and calls it completeness - December alone carries a 1.45x "
      "elective-surgery factor.")
    A("")
    A("| Service month | Observed completeness | Designed | De-trended baseline |")
    A("|---|---|---|---|")
    for m, ratio, expected, baseline in runout:
        A(f"| {m} | {ratio:.1%} | {expected:.0%} | ${baseline:,.0f} |")
    A("")
    A("Control: restrict service-date trends to complete months, or trend on "
      "paid date, which IS complete. Mixing the two is the error.")
    A("")
    A("---")
    A("")
    A("Regenerate with `python Generators/build.py --scale demo` then "
      "`python Build/build_mart.py` then `python Validation/validate.py`.")
    path.write_text("\n".join(L) + "\n")


def check_settlement(r: Results, exp, sc, mart_lines, mm, date_dim):
    """The settlement layer: risk scaling, roster versions, truncation, triangle.

    Every assertion here guards a number that silently went wrong before it
    existed. The benchmark that could not be beaten shipped for months because
    nothing compared it to an actual. The roster baseline was computed and
    thrown away. The over-match was documented in the answer key and absent
    from the data. A planted defect nobody can find is indistinguishable from
    a defect that is not there, and only an assertion tells them apart.
    """
    st = exp["settlement"]
    att = read_mart("vbc_attribution_month")
    rst = read_mart("vbc_attribution_restatement")
    vers = read_mart("vbc_roster_version")
    bench = read_mart("vbc_benchmark")
    myc = read_mart("fct_member_year_cost")
    tri = read_mart("fct_claims_lag_triangle")
    member = read_mart("dim_member", usecols=["member_id", "member_durable_key",
                                              "sex", "birth_date"])

    # ---- 1. risk scores normalize to 1.0 per book, before annual drift.
    tol = st["risk_score_book_mean_tolerance"]
    drift = pd.Series(C.RISK_DRIFT_BY_YEAR)
    mmv = mm.copy()
    mmv["_y"] = mmv["year_month"] // 100
    mmv["_undrift"] = mmv["risk_score"] / mmv["_y"].map(C.RISK_DRIFT_BY_YEAR)
    for lob, g in mmv.groupby("line_of_business"):
        mean = float(g["_undrift"].mean())
        r.add("SET-01", "Settlement", f"risk score book mean = 1.0 ({lob})",
              ERROR, abs(mean - C.RISK_SCORE_BOOK_MEAN) <= tol,
              "A risk score is only meaningful against a normalized book. "
              "Multiplying a benchmark PMPM by a raw morbidity weight produces "
              "a number with no contractual meaning.",
              actual=round(mean, 4), expected=f"1.0 +/- {tol}")

    r.band("SET-02", "Settlement", "attributed cohort mean risk > book",
           round(float(att["risk_score"].mean()), 4),
           st["attributed_mean_risk"], severity=sc.dist_severity(),
           detail="Attribution selects for care-seekers, so the attributed "
                  "sub-population must run richer than the book it is drawn "
                  "from. At 1.0 the attribution rule has stopped selecting.")

    # ---- 2. restatement runs in both directions, across every version.
    n_add = int((rst["new_status"] == "ATTRIBUTED").sum())
    n_term = int((rst["new_status"] == "RETRO_TERMINATED").sum())
    r.add("SET-03", "Settlement", "restatement includes retro-ADDITIONS",
          ERROR, n_add >= sc.count(st["retro_additions_min"]),
          "A restatement history that only ever removes members models the "
          "convenient direction and nothing else.",
          actual=n_add, expected=f">= {sc.count(st['retro_additions_min'])}")
    r.add("SET-04", "Settlement", "restatement includes retro-terminations",
          ERROR, n_term >= sc.count(st["retro_terminations_min"]),
          actual=n_term, expected=f">= {sc.count(st['retro_terminations_min'])}")
    r.add("SET-05", "Settlement", "every roster version ships",
          ERROR, len(vers) == st["roster_versions"]
          and int(vers["is_current_version"].astype(str).str.lower()
                  .eq("true").sum()) == 1,
          "The baseline roster used to be computed and discarded, leaving the "
          "as-of control with one position.",
          actual=len(vers), expected=st["roster_versions"])

    # ---- 3. the roster reconstruction actually moves PMPM.
    cur = mart_lines[_as_bool(mart_lines["is_current_version"])]
    spend = (cur.groupby(["member_durable_key", "service_year_month"])
             ["allowed_amount"].sum())
    dur = member.set_index("member_id")["member_durable_key"]
    months = list(range(202501, 202510))

    def pmpm(frame):
        f = frame[frame["year_month"].isin(months)]
        keys = list(zip(f["member_id"].map(dur), f["year_month"]))
        if not keys:
            return None
        return float(spend.reindex(keys).fillna(0).sum()) / len(keys)

    now = pmpm(att)
    base = pmpm(pd.concat([att, rst[rst.new_status == "RETRO_TERMINATED"]],
                          ignore_index=True))
    effect = None if not (now and base) else (base - now) / base * 100
    r.band("SET-06", "Settlement", "roster restatement moves PY2025 PMPM",
           None if effect is None else round(effect, 2),
           st["roster_pmpm_effect_pct"], severity=sc.dist_severity(),
           detail="Reconstructing the baseline roster from the delta. This is "
                  "the headline: an improvement that is bookkeeping, not care.")

    # ---- 4. truncation ties between the two grains.
    line_trunc = float(cur["allowed_amount_truncated"].sum())
    my_trunc = float(myc["allowed_amount_truncated"].sum())
    r.add("SET-07", "Settlement", "line truncation ties to member-year",
          ERROR, abs(line_trunc - my_trunc) <= st["truncation_tie_tolerance"],
          "The pro-rata allocation back down to the line must sum exactly to "
          "the member-year cap, or the two grains disagree about the same "
          "contract term.",
          actual=round(line_trunc, 2), expected=round(my_trunc, 2),
          dollars=round(abs(line_trunc - my_trunc), 2))
    share = float(myc["truncation_excess"].sum()) / max(
        float(myc["allowed_amount"].sum()), 1.0) * 100
    r.band("SET-08", "Settlement", "truncation removes a 99th-percentile tail",
           round(share, 2), st["truncated_share_of_spend_pct"],
           severity=sc.dist_severity(),
           detail="At a threshold too low for the cost curve this removes a "
                  "quarter of all spend and stops being a tail treatment.",
           dollars=round(float(myc["truncation_excess"].sum()), 2))

    # ---- 5. the benchmark is a number a settlement can be computed against.
    att24 = att[att["year_month"].between(202401, 202412)]
    keys24 = list(zip(att24["member_id"].map(dur), att24["year_month"]))
    trunc_spend = (cur.groupby(["member_durable_key", "service_year_month"])
                   ["allowed_amount_truncated"].sum())
    for lob, g in att24.groupby("line_of_business"):
        k = list(zip(g["member_id"].map(dur), g["year_month"]))
        actual = float(trunc_spend.reindex(k).fillna(0).sum()) / len(k)
        b = bench[(bench["line_of_business"] == lob)
                  & bench["year_month"].between(202401, 202412)]
        rab = float(b["risk_adjusted_benchmark_pmpm"].mean())
        gap = (rab - actual) / actual * 100
        r.band("SET-09", "Settlement",
               f"benchmark is beatable but not free ({lob})", round(gap, 2),
               st["benchmark_vs_actual_py2024_pct"],
               severity=sc.dist_severity(),
               detail=f"Risk-adjusted benchmark ${rab:,.0f} against truncated "
                      f"attributed actual ${actual:,.0f}, PY2024.")

    # ---- 6. the over-match reaches the claims spine.
    collapsed = member.groupby("member_durable_key").agg(
        n=("member_id", "size"), nsex=("sex", "nunique"),
        ndob=("birth_date", "nunique"))
    over = collapsed[(collapsed["n"] > 1)]
    py = cur[cur["service_year_month"].between(202501, 202509)]
    tot = py.groupby("member_durable_key")["allowed_amount"].sum().sort_values(
        ascending=False)
    top1 = set(tot.head(max(1, len(tot) // 100)).index)
    hits = len(set(over.index) & top1)
    r.add("SET-10", "Settlement", "over-match contaminates the cost tail",
          EXPECTED, hits >= st["overmatch_in_top_1pct_min"],
          "Two people wearing one identity surface as an artificial "
          "super-utilizer. Collapsing only the EHR key space left the payer "
          "spine intact, so claims never aggregated onto one person and the "
          "defect the answer key promises did not exist in the mart.",
          actual=hits, expected=f">= {st['overmatch_in_top_1pct_min']}",
          dollars=round(float(tot.reindex(list(set(over.index) & top1))
                              .fillna(0).sum()), 2))

    # ---- 7. the triangle ties, and recovers the asserted completeness.
    tri_allowed = float(tri["allowed_amount"].sum())
    line_allowed = float(cur["allowed_amount"].sum())
    r.add("SET-11", "Settlement", "lag triangle ties to fct_claim_line",
          ERROR, abs(tri_allowed - line_allowed)
          <= exp["settlement"]["lag_triangle_tie_tolerance"],
          actual=round(tri_allowed, 2), expected=round(line_allowed, 2),
          dollars=round(abs(tri_allowed - line_allowed), 2))

    dd = date_dim.drop_duplicates("year_month")
    a7_tol = exp["anomalies"]["A7_runout"]["derived_vs_asserted_tolerance"]
    # Every month the generator declares as partially developed, which is a
    # superset of the months that fall below the runout-complete flag.
    for month in sorted(C.RUNOUT_COMPLETENESS):
        ym = int(month.replace("-", ""))
        row = dd[dd["year_month"] == ym]
        if row.empty:
            continue
        asserted = float(row["claims_completeness_factor"].iloc[0])
        derived = float(row["completion_factor_derived"].iloc[0])
        r.add("SET-12", "Settlement",
              f"chain ladder recovers completeness ({month})",
              ERROR, abs(asserted - derived) <= a7_tol,
              "The completion factor is DERIVED from the paid dates present, "
              "not read off a constant. When these diverge, the extract is "
              "claiming a paid-through date its own data cannot support.",
              actual=round(derived, 4), expected=f"{asserted} +/- {a7_tol}")

    # And across EVERY service month, not only the named ones. A divergence
    # that shows up in an unnamed month is the one nobody is looking for.
    claim_months = sorted(tri["service_year_month"].unique())
    cmp = dd[dd["year_month"].isin(claim_months)]
    worst = float((cmp["claims_completeness_factor"]
                   - cmp["completion_factor_derived"]).abs().max())
    r.add("SET-13", "Settlement",
          "asserted and derived completeness agree, every month",
          ERROR, worst <= a7_tol, actual=round(worst, 4),
          detail="Checked across all "
                 f"{len(cmp)} service months carrying claims.",
          expected=f"<= {a7_tol}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    exp = yaml.safe_load((ROOT / "Validation" / "expectations.yml").read_text())
    manifest_path = DELIV / "anomaly-manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    print("\nValidating Healthcare Data Hub")
    raw_lines = read_raw("raw_clm", "clm_claim_line")
    mart_lines = read_mart("fct_claim_line")
    headers = read_mart("fct_claim_header")
    mm = read_mart("fct_member_month")
    spans = read_raw("raw_elig", "elig_eligibility_span")
    prov = read_raw("raw_ref", "ref_provider")
    enc = read_mart("fct_encounter")
    header_dx = read_raw("raw_clm", "clm_claim_diagnosis")
    ref = read_mart("fct_referral")
    outcome = read_mart("fct_referral_outcome")
    xw = read_mart("xwalk_patient")
    date_dim = read_mart("dim_date")
    print(f"  loaded {len(mart_lines):,} claim lines in {time.time()-t0:.1f}s")

    # Members with their condition flags come from the population truth file.
    members = _rebuild_members(mm)

    sc = Scaling(manifest.get("scale", "demo"))
    if not sc.statistical:
        print(f"  scale={sc.scale_name}: absolute thresholds scaled by "
              f"{sc.factor:.4f}; distribution bands advisory only "
              f"(n too small to assert)")

    res = Results()
    check_grain(res, exp, sc, raw_lines, mart_lines, mm, prov)
    check_referential(res, mart_lines, headers, enc)
    check_reconciliation(res, exp, mart_lines, headers, spans, mm)
    check_distributions(res, exp, sc, mart_lines, mm, enc, members)
    check_clinical(res, exp, sc, enc, header_dx, members, xw)
    check_conformance(res, exp, enc)
    check_question_ladder(res, exp, sc, ref, outcome, mart_lines)
    runout = check_runout(res, exp, sc, mart_lines, date_dim)
    check_settlement(res, exp, sc, mart_lines, mm, date_dim)

    df = res.frame()
    (DELIV / "validation_results.json").write_text(
        df.to_json(orient="records", indent=2))
    if not args.json_only:
        render_report(res, runout, DELIV / "data-trust-validation.md", manifest)

    n_err = len(res.errors)
    print()
    print(f"  {int(((df.severity=='ERROR') & df.passed).sum())} of "
          f"{int((df.severity=='ERROR').sum())} hard assertions passed")
    print(f"  {int(((df.severity=='EXPECTED') & df.passed).sum())} of "
          f"{int((df.severity=='EXPECTED').sum())} planted defects confirmed")
    for row in res.errors:
        print(f"  FAIL {row['check_id']}: {row['name']} "
              f"(actual {row['actual']}, expected {row['expected']})")
    not_found = df[(df.severity == EXPECTED) & ~df.passed]
    for row in not_found.itertuples():
        print(f"  NOT FOUND {row.check_id}: {row.name} "
              f"(actual {row.actual}, expected {row.expected})")
    print()
    print(f"Report: {DELIV / 'data-trust-validation.md'}")
    return 1 if n_err else 0


def _rebuild_members(mm: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct the member frame with condition flags for the realism checks.

    The condition flags are a generator-internal property rather than a source
    system output, so they are regenerated deterministically from the same
    seed rather than read back from a file.
    """
    sys.path.insert(0, str(ROOT / "Generators"))
    import population as POP
    manifest = json.loads((DELIV / "anomaly-manifest.json").read_text())
    run = C.make_run(scale=manifest["scale"], seed=manifest["seed"])
    return POP.build_population(run)["members"]


if __name__ == "__main__":
    raise SystemExit(main())
