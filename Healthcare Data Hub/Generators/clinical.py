"""EHR reality: encounters, encounter diagnoses, labs, and referral orders.

This module carries the demo's aha moment, so the mechanism is worth stating
plainly before the code.

North Ridge Orthopedics (ORTHO-NR) looks like the best referral manager in the
system on EHR data alone and is actually the worst. Two independent defects
combine:

  1. A PracticeOne scheduling rule effective 2024-07-01 auto-closes ORTHO-NR
     referrals at day 30 regardless of whether care happened. Their closure
     rate goes up, their open rate goes down, and neither number means
     anything. Only 38% of their "completed" referrals have a confirming
     encounter against a 72% system average.

  2. ORTHO-NR's out-of-network referrals go overwhelmingly to Summit Point
     Surgery Center, whose contract terminated 2024-10-01 but which STILL
     reads PAR in the EHR referral directory. So their leakage is invisible in
     the EHR: apparent out-of-network rate 6%, true rate 54%.

Nobody made a bad clinical decision. Both are governance failures.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

import config as C
import org
import reference as R

MEAN_DX_PER_ENCOUNTER = 3.25

# Encounter type encoding drifts by site (anomaly A11a). Most sites emit
# 'OFFICE'; four emit the long form; one emits 'AMB', which has no row in the
# service-line crosswalk and therefore lands as UNKNOWN.
LONG_FORM_SITES = {"PRIM-EGR", "PRIM-WPT", "PEDS-SBR", "WMN-SBR"}
AMB_SITE = "MULT-WPT"
# Only one department inside that group emits the bad value, which is why it
# is ~3% of ambulatory volume rather than the whole site.
AMB_DEPT_SHARE = 0.45

# Referral behavior. The system baseline versus the one broken site.
SYSTEM_CONFIRM_RATE = 0.72
NR_CONFIRM_RATE = 0.38
SYSTEM_TRUE_OON_RATE = 0.22
NR_TRUE_OON_RATE = 0.54
NR_AUTOCLOSE_SHARE = 0.63           # share of post-rule closures landing at day 30
# Share of ORTHO-NR out-of-network referrals sent to Summit Point, which reads
# PAR in the stale directory and is therefore invisible.
NR_SUMMIT_SHARE = 0.88

REFERRAL_SPECIALTIES = ["SL01", "SL02", "SL03", "SL05", "SL12", "SL13", "SL14",
                        "SL16", "SL17", "SL18", "SL19", "SL20", "SL21", "SL22"]


def _neg_binomial(rng, mu: np.ndarray, k: float) -> np.ndarray:
    """Gamma-Poisson mixture. Healthcare counts are overdispersed, not Poisson."""
    lam = rng.gamma(shape=k, scale=np.maximum(mu, 1e-9) / k)
    return rng.poisson(lam)


def _age_factor(age: np.ndarray) -> np.ndarray:
    return np.where(age < 2, 2.6,
           np.where(age < 6, 1.5,
           np.where(age < 18, 0.72,
           np.where(age < 40, 0.86,
           np.where(age < 55, 1.0,
           np.where(age < 65, 1.10, 1.25))))))


def build_clinical(
    run: C.RunConfig,
    members: pd.DataFrame,
    prov: pd.DataFrame,
    fac: pd.DataFrame,
    member_months: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    rng = run.rng("clinical")

    # Coverage exposure per member, so encounters only happen while covered.
    exposure = (
        member_months.groupby("member_id", as_index=False)["member_months"].sum()
        .rename(columns={"member_months": "exposure_months"})
    )
    m = members.merge(exposure, on="member_id", how="left")
    m["exposure_months"] = m["exposure_months"].fillna(0.0)

    dx = R.build_dim_diagnosis()
    encounters = _build_encounters(run, rng, m, prov, fac, dx)
    enc_dx = _build_encounter_diagnoses(rng, encounters, m, dx)
    labs = _build_labs(rng, encounters, m)
    referrals = _build_referrals(run, rng, encounters, m, prov, fac)

    return {
        "ehr_encounter": encounters,
        "ehr_encounter_diagnosis": enc_dx,
        "ehr_lab_result": labs,
        "ehr_referral_order": referrals,
    }


# ------------------------------------------------------------------- encounters

def _build_encounters(run, rng, m, prov, fac, dx) -> pd.DataFrame:
    """Encounters, generated per class from risk-driven rates.

    Four independent count draws per member rather than one blended count
    split by a uniform draw. Ambulatory and urgent care scale with chronic
    burden; emergency and inpatient scale with risk and with the specific
    conditions that actually drive admissions. That is what puts the cost
    concentration curve and the admits-per-1000 split where a payer audience
    expects to find them.
    """
    n = len(m)
    years = m["exposure_months"].to_numpy() / 12.0
    risk = m["latent_risk"].to_numpy()
    age = m["age_2024"].to_numpy()
    nchr = m["n_chronic"].to_numpy()
    af = _age_factor(age)
    chronic_mult = 1.0 + C.CHRONIC_UTILIZATION_COEF * nchr
    k = C.ENCOUNTER_DISPERSION

    mu_amb = C.AMBULATORY_BASE_RATE * risk * af * chronic_mult * years
    mu_uc = C.URGENT_CARE_BASE_RATE * np.sqrt(np.maximum(risk, 0.01)) * years

    # Emergency: risk driven, plus a small very-heavy-use cohort.
    elderly = (age >= 65).astype(float)
    mu_ed = (
        C.ED_BASE_RATE * risk * af * years
        * (1.0 + elderly * (C.ELDERLY_ED_MULTIPLIER - 1.0))
    )
    superuser = rng.random(n) < C.ED_SUPERUSER_SHARE
    mu_ed = np.where(superuser, C.ED_SUPERUSER_RATE * years, mu_ed)

    # Admissions: driven by the conditions that actually cause them.
    cond_boost = np.ones(n)
    for code, w in C.ADMIT_CONDITION_WEIGHTS.items():
        col = f"cond_{code.lower()}"
        if col in m.columns:
            cond_boost += w * m[col].to_numpy().astype(float)
    mu_ip = (
        C.ADMIT_BASE_RATE * risk * af * cond_boost * years
        * (1.0 + elderly * (C.ELDERLY_ADMIT_MULTIPLIER - 1.0))
    )

    n_amb = _neg_binomial(rng, mu_amb, k)
    n_uc = _neg_binomial(rng, mu_uc, k)
    n_ed = _neg_binomial(rng, mu_ed, k)
    n_ip = rng.poisson(np.maximum(mu_ip, 0.0))

    classes = ["AMBULATORY", "URGENT_CARE", "EMERGENCY", "INPATIENT"]
    counts_by_class = [n_amb, n_uc, n_ed, n_ip]
    member_idx = np.concatenate([
        np.repeat(np.arange(n), cnt) for cnt in counts_by_class
    ])
    enc_class = np.concatenate([
        np.repeat(cls, int(cnt.sum())) for cls, cnt in zip(classes, counts_by_class)
    ])
    total = len(member_idx)

    # ---- dates, weighted by respiratory seasonality
    span_days = (C.SOURCE_END - C.SOURCE_START).days
    day_offsets = (rng.random(total) * span_days).astype(int)
    dates = np.array([C.SOURCE_START + timedelta(days=int(d)) for d in day_offsets])
    months = np.array([d.month for d in dates])
    season_w = np.array([C.RESPIRATORY_SEASONALITY[mo] for mo in months])
    redraw = rng.random(total) >= (season_w / season_w.max())
    if redraw.any():
        d2 = (rng.random(int(redraw.sum())) * span_days).astype(int)
        dates[redraw] = np.array(
            [C.SOURCE_START + timedelta(days=int(d)) for d in d2]
        )

    # Elective ambulatory care does not happen on weekends or federal holidays.
    dim = R.build_dim_date().set_index("full_date")
    hol = set(dim.index[dim["is_holiday"]].tolist())
    iso = np.array([d.isoformat() for d in dates])
    wd = np.array([d.weekday() for d in dates])
    bad = (enc_class == "AMBULATORY") & ((wd >= 5) | np.isin(iso, list(hol)))
    shift = 0
    while bad.any() and shift < 6:
        dates[bad] = np.array([d + timedelta(days=1) for d in dates[bad]])
        dates = np.array([min(d, C.SOURCE_END) for d in dates])
        iso = np.array([d.isoformat() for d in dates])
        wd = np.array([d.weekday() for d in dates])
        bad = (enc_class == "AMBULATORY") & ((wd >= 5) | np.isin(iso, list(hol)))
        shift += 1

    # ---- site assignment
    attributed = m["attributed_site_code"].to_numpy()[member_idx]
    region = m["region"].to_numpy()[member_idx]
    fac_by_type: dict[str, list] = {}
    for r in fac.itertuples():
        fac_by_type.setdefault(r.facility_type, []).append(r.site_code)

    site = np.empty(total, dtype=object)
    amb = enc_class == "AMBULATORY"
    site[amb] = np.where(
        rng.random(int(amb.sum())) < 0.82,
        attributed[amb],
        rng.choice(org.CLINIC_GROUPS, size=int(amb.sum())),
    )
    for cls, ftype in (("URGENT_CARE", "URGENT_CARE"), ("EMERGENCY", "ED"),
                       ("INPATIENT", "HOSPITAL")):
        sel = enc_class == cls
        if sel.any():
            site[sel] = rng.choice(fac_by_type[ftype], size=int(sel.sum()))

    # ---- EHR department id, including the renumbered hospital (A11c)
    dept = np.array([f"RB-{s}" for s in site], dtype=object)
    is_renum = site == org.RENUMBERED_SITE
    if is_renum.any():
        after = np.array([d >= C.RENUMBER_EFFECTIVE for d in dates])
        dept[is_renum & after] = org.RENUMBERED_NEW_DEPT
        dept[is_renum & ~after] = org.RENUMBERED_OLD_DEPT

    # ---- encounter type string, with the site-level encoding drift (A11a)
    enc_type = np.empty(total, dtype=object)
    enc_type[:] = "OFFICE"
    enc_type[enc_class == "URGENT_CARE"] = "URGENT"
    enc_type[enc_class == "EMERGENCY"] = "ED"
    enc_type[enc_class == "INPATIENT"] = "INPATIENT"
    long_form = amb & np.isin(site, list(LONG_FORM_SITES))
    enc_type[long_form] = "OFFICE VISIT"
    amb_site = amb & (site == AMB_SITE) & (rng.random(total) < AMB_DEPT_SHARE)
    enc_type[amb_site] = "AMB"

    # ---- attending provider from that site's roster
    prov_by_site: dict[str, list[str]] = {}
    for r in prov.itertuples():
        prov_by_site.setdefault(r.primary_site_code, []).append(r.provider_master_id)
    all_prov = prov["provider_master_id"].tolist()
    attending = np.array([
        (prov_by_site.get(s) or all_prov)[
            int(rng.integers(0, len(prov_by_site.get(s) or all_prov)))
        ]
        for s in site
    ], dtype=object)

    # ---- length of stay, ALOS target 3.9-4.6 days
    los = np.zeros(total, dtype=int)
    ip = enc_class == "INPATIENT"
    if ip.any():
        los[ip] = np.clip(
            rng.gamma(shape=2.6, scale=1.62, size=int(ip.sum())).round(), 1, 45
        )
    discharge = np.array([
        a + timedelta(days=int(l)) if l > 0 else a for a, l in zip(dates, los)
    ])

    enc = pd.DataFrame({
        "encounter_id": [f"ENC{i:09d}" for i in range(1, total + 1)],
        "mrn": m["mrn"].to_numpy()[member_idx],
        "member_id_truth": m["member_id"].to_numpy()[member_idx],
        "ehr_dept_id": dept,
        "site_code": site,
        "encounter_class": enc_class,
        "encounter_type_source": enc_type,
        "encounter_date": [d.isoformat() for d in dates],
        "admit_date": [a.isoformat() if l > 0 else None for a, l in zip(dates, los)],
        "discharge_date": [d.isoformat() if l > 0 else None
                           for d, l in zip(discharge, los)],
        "length_of_stay_days": los,
        "attending_provider_master_id": attending,
        "patient_region": region,
    })
    enc["discharge_disposition"] = np.where(
        enc["length_of_stay_days"] > 0,
        rng.choice(["HOME", "HOME_HEALTH", "SNF", "AMA", "EXPIRED"],
                   size=total, p=[0.72, 0.12, 0.13, 0.02, 0.01]),
        None,
    )
    enc = enc.sort_values(["encounter_date", "mrn"]).reset_index(drop=True)
    enc["encounter_id"] = [f"ENC{i:09d}" for i in range(1, len(enc) + 1)]
    return enc


# --------------------------------------------------------- encounter diagnoses

def _build_encounter_diagnoses(rng, enc, m, dx) -> pd.DataFrame:
    """Many-to-many diagnosis bridge, mean 3.25 per encounter.

    Diagnosis draws are conditioned on the member's assigned conditions, so a
    diabetic's encounters carry diabetes codes. Acute codes come from an
    age and sex conditioned pool. is_primary and diagnosis_position ship so
    the correct answer is one predicate away, but NO pre-built allocation is
    provided - deciding how to allocate cost across diagnoses is the lesson.
    """
    n_enc = len(enc)
    counts = np.clip(rng.poisson(MEAN_DX_PER_ENCOUNTER - 1, n_enc) + 1, 1, 12)

    cond_cols = {c: f"cond_{c.lower()}" for c, *_ in C.CONDITIONS}
    mem = m.set_index("mrn")
    dx_by_cond: dict[str, list[str]] = {}
    for r in dx.itertuples():
        if r.condition_code:
            dx_by_cond.setdefault(r.condition_code, []).append(r.icd10_code)
    acute = dx[dx.condition_code.isna() & ~dx.chronic_condition_flag]
    acute_codes = acute.icd10_code.tolist()
    msk = dx[(dx.ccsr_body_system == "Musculoskeletal")].icd10_code.tolist()
    female_only = R.FEMALE_ONLY_DX
    male_only = R.MALE_ONLY_DX
    peds_only = R.PEDIATRIC_ONLY_DX

    enc_idx = np.repeat(np.arange(n_enc), counts)
    position = np.concatenate([np.arange(1, c + 1) for c in counts])

    mrns = enc["mrn"].to_numpy()
    sites = enc["site_code"].to_numpy()
    codes = np.empty(len(enc_idx), dtype=object)

    # Member chronic-code pools are resolved lazily and cached.
    pool_cache: dict[str, list[str]] = {}

    rand = rng.random(len(enc_idx))
    for j, (ei, pos) in enumerate(zip(enc_idx, position)):
        mrn = mrns[ei]
        pool = pool_cache.get(mrn)
        if pool is None:
            row = mem.loc[mrn]
            pool = []
            for cond, col in cond_cols.items():
                if bool(row[col]):
                    pool.extend(dx_by_cond.get(cond, []))
            if bool(row.get("is_pregnant_in_window", False)):
                pool.extend(dx_by_cond.get("PREG", []))
            sex = row["sex"]; age = int(row["age_2024"])
            pool = [
                c for c in pool
                if not (c in female_only and sex != "F")
                and not (c in male_only and sex != "M")
                and not (c in peds_only and age > 17)
            ]
            pool_cache[mrn] = pool
        # Orthopedic sites skew musculoskeletal, which is what makes the
        # referral-leakage story clinically coherent.
        if sites[ei] in ("ORTHO-NR", "SPIN-MRD") and rand[j] < 0.72:
            codes[j] = msk[int(rand[j] * 1e6) % len(msk)]
        elif pool and rand[j] < 0.55:
            codes[j] = pool[int(rand[j] * 1e6) % len(pool)]
        else:
            row = mem.loc[mrn]
            sex = row["sex"]; age = int(row["age_2024"])
            cand = [
                c for c in acute_codes
                if not (c in female_only and sex != "F")
                and not (c in male_only and sex != "M")
                and not (c in peds_only and age > 17)
            ]
            codes[j] = cand[int(rand[j] * 1e6) % len(cand)]

    return pd.DataFrame({
        "encounter_id": enc["encounter_id"].to_numpy()[enc_idx],
        "diagnosis_position": position,
        "icd10_code": codes,
        "is_primary": position == 1,
    })


# ------------------------------------------------------------------------ labs

def _build_labs(rng, enc, m) -> pd.DataFrame:
    """Resulted lab components.

    The HbA1c gap (anomaly A8) is planted here: some diabetic members have a
    test performed at an EXTERNAL lab that returns no structured result, so the
    EHR has no row at all. Others have an in-house result with no separate
    claim line because it was bundled into a global fee. The two sources are
    each missing a different group of people, so neither is the superset and
    the union needs a documented rule.
    """
    mem = m.set_index("mrn")
    diabetic_mrns = set(m.loc[m.cond_dm2, "mrn"])
    amb = enc[enc.encounter_class == "AMBULATORY"]

    rows = []
    panels = [
        ("83036", "HbA1c", "4548-4", 5.2, 0.9, "%"),
        ("80053", "Comprehensive metabolic panel - glucose", "2345-7", 96.0, 22.0, "mg/dL"),
        ("80061", "Lipid panel - LDL", "13457-7", 108.0, 32.0, "mg/dL"),
        ("85025", "CBC - hemoglobin", "718-7", 13.6, 1.5, "g/dL"),
        ("84443", "TSH", "3016-3", 2.1, 1.1, "uIU/mL"),
        ("82043", "Urine albumin", "14957-5", 18.0, 26.0, "mg/L"),
    ]
    sel = amb.sample(frac=0.42, random_state=11) if len(amb) else amb
    for e in sel.itertuples():
        try:
            row = mem.loc[e.mrn]
        except KeyError:
            continue
        n_panels = 1 + int(rng.random() < 0.45) + int(rng.random() < 0.18)
        picks = rng.choice(len(panels), size=n_panels, replace=False)
        for pi in picks:
            code, name, loinc, mean, sd, unit = panels[pi]
            is_a1c = code == "83036"
            if is_a1c and e.mrn not in diabetic_mrns and rng.random() < 0.85:
                continue
            shift = 0.0
            if is_a1c and e.mrn in diabetic_mrns:
                shift = 2.6 + 1.4 * float(row["latent_risk"]) / 2
            value = float(rng.normal(mean + shift, sd))
            # External-lab orders come back with no structured result.
            external = rng.random() < 0.13
            rows.append({
                "encounter_id": e.encounter_id,
                "mrn": e.mrn,
                "result_date": e.encounter_date,
                "lab_code": code,
                "lab_name": name,
                "loinc_code": loinc,
                "performing_lab_site": "LAB-EXT" if external else "LAB-CENT",
                "result_value": None if external else round(value, 2),
                "result_unit": unit,
                "result_status": "NO_STRUCTURED_RESULT" if external else "FINAL",
                "is_abnormal": (
                    None if external
                    else bool(abs(value - mean) > 1.8 * sd)
                ),
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- referrals

def _build_referrals(run, rng, enc, m, prov, fac) -> pd.DataFrame:
    """Referral orders - the spine of the demo.

    Each referral records where it was SENT and what the EHR believed about
    that destination's network status at order time. The EHR belief comes from
    the stale provider directory, which is why the leakage is invisible.
    """
    amb = enc[enc.encounter_class == "AMBULATORY"].copy()
    # Referrals come out of ambulatory visits at clinic groups.
    amb = amb[amb.site_code.isin(org.CLINIC_GROUPS)]
    if amb.empty:
        return pd.DataFrame()

    # Orthopedic sites refer far more often; primary care refers steadily.
    base_rate = np.where(
        amb.site_code.isin(["ORTHO-NR", "SPIN-MRD"]).to_numpy(), 0.34, 0.16
    )
    pick = rng.random(len(amb)) < base_rate
    src = amb[pick].reset_index(drop=True)
    n = len(src)
    if n == 0:
        return pd.DataFrame()

    is_nr = (src.site_code == "ORTHO-NR").to_numpy()
    placed = pd.to_datetime(src.encounter_date)
    post_rule = (placed >= pd.Timestamp(C.AUTOCLOSE_EFFECTIVE)).to_numpy()

    # ---- did care actually happen?
    confirm_p = np.where(is_nr & post_rule, NR_CONFIRM_RATE, SYSTEM_CONFIRM_RATE)
    # Before the rule ORTHO-NR behaved like everyone else.
    confirm_p = np.where(is_nr & ~post_rule, SYSTEM_CONFIRM_RATE, confirm_p)
    actually_occurred = rng.random(n) < confirm_p

    # ---- where was it sent, and was that truly in network?
    true_oon_p = np.where(is_nr & post_rule, NR_TRUE_OON_RATE, SYSTEM_TRUE_OON_RATE)
    true_oon_p = np.where(is_nr & ~post_rule, SYSTEM_TRUE_OON_RATE, true_oon_p)
    is_oon = rng.random(n) < true_oon_p

    in_network_targets = ["ASC-RVB", "ASC-NLK", "ASC-EGR", "ASC-WPT", "ASC-SBR",
                          "HOSP-RVB", "HOSP-NLK", "MULT-WPT", "CARD-RVB", "GI-EGR"]
    other_oon_targets = ["ASC-LKSD", "ASC-PINE", "ASC-CRST", "IMG-OPEN"]

    dest = np.empty(n, dtype=object)
    dest[~is_oon] = rng.choice(in_network_targets, size=int((~is_oon).sum()))
    # ORTHO-NR sends its out-of-network volume overwhelmingly to Summit Point,
    # which still reads PAR in the directory and is therefore invisible.
    nr_oon = is_oon & is_nr
    oth_oon = is_oon & ~is_nr
    if nr_oon.any():
        dest[nr_oon] = np.where(
            rng.random(int(nr_oon.sum())) < NR_SUMMIT_SHARE,
            "ASC-SUMMIT",
            rng.choice(other_oon_targets, size=int(nr_oon.sum())),
        )
    if oth_oon.any():
        dest[oth_oon] = np.where(
            rng.random(int(oth_oon.sum())) < 0.22,
            "ASC-SUMMIT",
            rng.choice(other_oon_targets, size=int(oth_oon.sum())),
        )

    # ---- closure mechanics
    days_to_closure = np.zeros(n, dtype=int)
    closure_actor = np.empty(n, dtype=object)
    status = np.empty(n, dtype=object)

    # Baseline: log-normal 3-60 days, closed by a human, ~19% left open.
    base_days = np.clip(rng.lognormal(np.log(16), 0.62, n).round(), 3, 90).astype(int)
    left_open = rng.random(n) < 0.19
    days_to_closure[:] = base_days
    closure_actor[:] = "USER"
    status[:] = "CLOSED_COMPLETE"
    status[left_open] = "OPEN"

    # ORTHO-NR post-rule: 63% of closures land at day 30 +/- 1, actor SYSTEM,
    # and almost nothing is left open because the rule closes it.
    nr_rule = is_nr & post_rule
    if nr_rule.any():
        k = int(nr_rule.sum())
        auto = rng.random(k) < NR_AUTOCLOSE_SHARE
        d = base_days[nr_rule].copy()
        a = np.array(["USER"] * k, dtype=object)
        st = np.array(["CLOSED_COMPLETE"] * k, dtype=object)
        d[auto] = C.AUTOCLOSE_DAYS + rng.integers(-1, 2, size=int(auto.sum()))
        a[auto] = "SYSTEM"
        # Net ~4% left open at ORTHO-NR post-rule: the rule closes the rest.
        lo = (~auto) & (rng.random(k) < 0.115)
        st[lo] = "OPEN"
        days_to_closure[nr_rule] = d
        closure_actor[nr_rule] = a
        status[nr_rule] = st

    closed = status == "CLOSED_COMPLETE"
    closure_date = np.array([
        (p + pd.Timedelta(days=int(dd))).date().isoformat() if c else None
        for p, dd, c in zip(placed, days_to_closure, closed)
    ], dtype=object)
    closure_actor = np.where(closed, closure_actor, None)
    days_out = np.where(closed, days_to_closure, None)

    # ---- what the EHR directory believed about the destination at order time.
    # Summit Point reads PAR here despite its terminated contract, which is
    # precisely why ORTHO-NR's leakage is invisible on EHR data alone.
    innet_set = set(in_network_targets)
    directory_status = np.array([
        "PAR" if (d in innet_set or d == "ASC-SUMMIT") else "NONPAR" for d in dest
    ], dtype=object)

    specialty = np.where(
        np.isin(dest, ["ASC-SUMMIT", "ASC-LKSD", "ASC-PINE"]),
        "SL01",
        rng.choice(REFERRAL_SPECIALTIES, size=n),
    )

    ref = pd.DataFrame({
        "referral_id": [f"REF{i:08d}" for i in range(1, n + 1)],
        "source_encounter_id": src.encounter_id.to_numpy(),
        "mrn": src.mrn.to_numpy(),
        "referring_site_code": src.site_code.to_numpy(),
        "referring_provider_master_id": src.attending_provider_master_id.to_numpy(),
        "referral_specialty_code": specialty,
        "placed_date": [p.date().isoformat() for p in placed],
        "destination_site_code": dest,
        "destination_status_per_ehr_directory": directory_status,
        "referral_status": status,
        "days_to_closure": days_out,
        "closure_date": closure_date,
        "closure_actor_type": closure_actor,
        "patient_region": src.patient_region.to_numpy(),
        # Internal truth columns, dropped before the raw file is written.
        "_truth_care_occurred": actually_occurred,
        "_truth_out_of_network": is_oon,
    })
    return ref
