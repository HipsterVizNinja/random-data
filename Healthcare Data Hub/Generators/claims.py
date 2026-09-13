"""Claims: headers, lines, adjudication, reversals, and the leakage dollars.

Claims arrive from three places, which is what makes the encounter join
genuinely partial rather than artificially broken:

  1. Northlake encounters - professional and facility claims for care the EHR
     saw. These carry an encounter_id.
  2. Referral episodes - the procedural care a referral led to. Out-of-network
     episodes cost materially more, and this is where the $2.7M lives.
  3. Outside claims - care delivered somewhere Northlake has no visibility
     into. No encounter_id at all, by design, roughly a quarter of all claims.

The money identity holds on every single line:
    allowed  = paid + deductible + copay + coinsurance + cob
    billed  >= allowed >= paid
CO-45 (the contractual write-off, billed minus allowed) is an AMOUNT COLUMN,
never a denial status. Treating it as a denial is the fastest way to lose a
revenue-cycle person in the room.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

import config as C
import org
import reference as R

# Allowed-amount lognormal parameters per service category: (mu, sigma).
COST_MODEL = {
    "EM_OFFICE":       (np.log(118), 0.42),
    "EM_ED":           (np.log(742), 0.78),
    "LAB":             (np.log(28), 0.65),
    "IMAGING":         (np.log(340), 0.85),
    "OP_SURGERY":      (np.log(1450), 0.88),   # professional fee
    "IP_SURGERY":      (np.log(2400), 0.85),   # surgeon fee, not facility
    "PT":              (np.log(96), 0.48),
    "ANESTHESIA":      (np.log(680), 0.72),
    "SPECIALTY_DRUG":  (np.log(4800), 0.95),
    "TRANSPORT":       (np.log(620), 0.55),
}

# Facility contract factors. Hospitals command more than surgery centers.
CONTRACT_FACTOR = {
    "HOSPITAL": (1.00, 1.45), "ASC": (0.55, 0.75), "CLINIC_GROUP": (0.92, 1.08),
    "URGENT_CARE": (0.80, 0.98), "ED": (1.05, 1.40), "SNF": (0.85, 1.05),
    "IMAGING": (0.70, 1.10), "LAB": (0.60, 0.90), "THERAPY": (0.85, 1.05),
    "INFUSION": (1.05, 1.35), "DIALYSIS": (1.00, 1.25),
}

# Out-of-network economics: billed is a large multiple of allowed and the plan
# pays a reduced share.
OON_BILLED_MULTIPLE = 2.8
OON_PAID_SHARE = 0.60

# Facility claims are priced at the CLAIM level and then distributed across
# their lines. Pricing each facility line independently is the single easiest
# way to produce a wildly wrong PMPM: a 14-line admission would draw the full
# inpatient distribution fourteen times over.
FACILITY_CLAIM_TARGET = {
    "INPATIENT": (np.log(16000), 0.90),   # commercial avg allowed $16-24k
    "EMERGENCY": (np.log(1350), 0.80),
    "UNKNOWN":   (np.log(900), 1.00),
}

# Most specialty referrals end in a CONSULT, not an operation. Treating every
# confirmed referral as a surgical episode puts musculoskeletal surgery at
# several hundred cases per 1,000 lives - more than ten times reality - and it
# inflates every leakage dollar figure with it.
REFERRAL_PROCEDURE_SHARE = 0.10

# Allowed amount for a musculoskeletal referral PROCEDURE episode, in versus
# out of network. The gap times the leaked volume is the headline dollar
# figure.
MSK_EPISODE_IN_NETWORK = 9_800.0
MSK_EPISODE_OUT_NETWORK = 14_200.0

REVERSAL_V2_RATE = 0.048
REVERSAL_V3_RATE = 0.007
ORPHAN_REVERSALS = 118           # reversals whose original predates the window

OUTSIDE_CLAIM_SHARE = 0.24       # claims with no Northlake encounter

DENIAL_RATE = 0.068

# Catastrophic members, so the top of the cost distribution does not read
# synthetic. Transplant, NICU, factor products, CAR-T.
N_CATASTROPHIC = 12
CATASTROPHIC_RANGE = (400_000, 1_900_000)


def _zipf_weights(n: int, exponent: float = C.ZIPF_EXPONENT) -> np.ndarray:
    r = np.arange(1, n + 1)
    w = r ** (-exponent)
    return w / w.sum()


def build_claims(
    run: C.RunConfig,
    members: pd.DataFrame,
    prov: pd.DataFrame,
    fac: pd.DataFrame,
    encounters: pd.DataFrame,
    referrals: pd.DataFrame,
    spans: pd.DataFrame,
    plans: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    rng = run.rng("claims")
    proc = R.build_dim_procedure()

    skeleton = _build_claim_skeleton(
        run, rng, members, prov, fac, encounters, referrals, spans
    )
    lines = _build_claim_lines(run, rng, skeleton, proc, fac, members)
    lines = _price_lines(run, rng, lines, fac, members)
    lines = _adjudicate(run, rng, lines, skeleton, plans, members)
    runout_stats = lines.attrs.get("runout_stats", {})
    lines = _apply_versions(run, rng, lines)
    headers = _build_headers(rng, lines, skeleton)
    header_dx = _build_header_diagnoses(rng, headers, encounters, members)
    return {
        "clm_claim_header": headers,
        "clm_claim_line": lines,
        "clm_claim_diagnosis": header_dx,
        "_runout_stats": runout_stats,
    }


# ------------------------------------------------------------------- skeleton

def _build_claim_skeleton(run, rng, members, prov, fac, enc, ref, spans) -> pd.DataFrame:
    """One row per claim before lines or money. Establishes the encounter link."""
    fac_by_code = {r.site_code: r for r in fac.itertuples()}
    members = members.assign(
        _is_ma=members["line_of_business"].eq("MEDICARE_ADVANTAGE")
    )
    mem_by_mrn = members.set_index("mrn")[
        ["member_id", "region", "latent_risk", "_is_ma"]
    ]

    parts = []

    # ---- (1) claims arising from Northlake encounters
    e = enc.merge(mem_by_mrn, left_on="mrn", right_index=True, how="left")
    rates = {"AMBULATORY": 0.30, "URGENT_CARE": 0.75, "EMERGENCY": 0.92,
             "INPATIENT": 1.0}
    for cls, rate in rates.items():
        sub = e[e.encounter_class == cls]
        if sub.empty:
            continue
        if cls == "INPATIENT":
            # One institutional claim plus several professional claims, ALL
            # carrying the same encounter_id. Counting claims as admissions
            # inflates volume 5-8x; COUNT(DISTINCT encounter_id) is correct.
            keep = sub
            inst = keep.assign(claim_type="I", claim_role="FACILITY")
            n_prof = rng.integers(2, 7, size=len(keep))
            prof = keep.loc[keep.index.repeat(n_prof)].assign(
                claim_type="P", claim_role="PROFESSIONAL"
            )
            parts += [inst, prof]
        else:
            sel = sub[rng.random(len(sub)) < rate]
            parts.append(sel.assign(claim_type="P", claim_role="PROFESSIONAL"))
            if cls == "EMERGENCY":
                # ED generates a facility claim alongside the professional one.
                parts.append(
                    sel[rng.random(len(sel)) < 0.85].assign(
                        claim_type="I", claim_role="FACILITY"
                    )
                )

    enc_claims = pd.concat(parts, ignore_index=True)
    enc_claims = enc_claims.rename(columns={"encounter_date": "service_date"})
    enc_claims["source_kind"] = "ENCOUNTER"
    enc_claims["service_site_code"] = enc_claims["site_code"]
    enc_claims["referral_id"] = None
    enc_claims["is_out_of_network"] = False

    keep_cols = ["member_id", "mrn", "encounter_id", "service_date", "claim_type",
                 "claim_role", "source_kind", "service_site_code", "referral_id",
                 "is_out_of_network", "encounter_class", "length_of_stay_days",
                 "admit_date", "discharge_date", "discharge_disposition",
                 "attending_provider_master_id", "region", "latent_risk", "_is_ma"]
    enc_claims = enc_claims[keep_cols]

    # ---- (2) referral episodes: the care a referral actually led to
    if not ref.empty:
        occ = ref[ref["_truth_care_occurred"]].copy()
        occ = occ.merge(mem_by_mrn, left_on="mrn", right_index=True, how="left")
        # Episode happens a little after the referral was placed.
        lag = rng.integers(7, 75, size=len(occ))
        svc = pd.to_datetime(occ["placed_date"]) + pd.to_timedelta(lag, unit="D")
        svc = svc.clip(upper=pd.Timestamp(C.SOURCE_END))
        occ["service_date"] = svc.dt.strftime("%Y-%m-%d")
        # A tenth of confirmed referrals lead to a procedure; the rest are
        # consults, and they are priced through the ordinary per-line model.
        is_procedure = rng.random(len(occ)) < REFERRAL_PROCEDURE_SHARE
        occ["claim_type"] = np.where(is_procedure, "I", "P")
        occ["claim_role"] = np.where(
            is_procedure, "REFERRAL_EPISODE", "REFERRAL_CONSULT")
        occ["source_kind"] = "REFERRAL"
        occ["service_site_code"] = occ["destination_site_code"]
        occ["is_out_of_network"] = occ["_truth_out_of_network"]
        occ["encounter_id"] = None          # care happened outside Northlake
        occ["encounter_class"] = np.where(
            is_procedure, "OUTPATIENT_PROCEDURE", "UNKNOWN")
        occ["length_of_stay_days"] = 0
        occ["admit_date"] = None
        occ["discharge_date"] = None
        occ["discharge_disposition"] = None
        occ["attending_provider_master_id"] = occ["referring_provider_master_id"]
        parts_ref = occ[keep_cols]
        # A professional claim accompanies most episodes.
        prof_ref = parts_ref[rng.random(len(parts_ref)) < 0.78].assign(
            claim_type="P", claim_role="PROFESSIONAL"
        )
    else:
        parts_ref = pd.DataFrame(columns=keep_cols)
        prof_ref = parts_ref

    # ---- (3) outside claims: care with no Northlake visibility at all
    # Referral episodes already carry no encounter_id, so the outside count is
    # solved for the TOTAL no-encounter share rather than added on top of it.
    n_with_enc = len(enc_claims)
    n_no_enc_already = len(parts_ref) + len(prof_ref)
    n_outside = int(round(
        (OUTSIDE_CLAIM_SHARE * n_with_enc
         - (1 - OUTSIDE_CLAIM_SHARE) * n_no_enc_already)
        / (1 - OUTSIDE_CLAIM_SHARE)
    ))
    n_outside = max(n_outside, 0)
    pick = rng.choice(len(members), size=n_outside, replace=True)
    span_days = (C.SOURCE_END - C.SOURCE_START).days
    off = rng.integers(0, span_days + 1, size=n_outside)
    out_sites = ["ASC-CRST", "ASC-PINE", "ASC-LKSD", "IMG-OPEN", "LAB-EXT",
                 "ASC-SUMMIT", "HOSP-WPT", "UC-HLC"]
    outside = pd.DataFrame({
        "member_id": members["member_id"].to_numpy()[pick],
        "mrn": members["mrn"].to_numpy()[pick],
        "encounter_id": None,
        "service_date": [
            (C.SOURCE_START + timedelta(days=int(d))).isoformat() for d in off
        ],
        "claim_type": rng.choice(["P", "I", "D"], size=n_outside, p=[0.74, 0.21, 0.05]),
        "claim_role": "OUTSIDE",
        "source_kind": "OUTSIDE",
        "service_site_code": rng.choice(out_sites, size=n_outside),
        "referral_id": None,
        "is_out_of_network": rng.random(n_outside) < 0.31,
        "encounter_class": "UNKNOWN",
        "length_of_stay_days": 0,
        "admit_date": None,
        "discharge_date": None,
        "discharge_disposition": None,
        "attending_provider_master_id": None,
        "region": members["region"].to_numpy()[pick],
        "latent_risk": members["latent_risk"].to_numpy()[pick],
        "_is_ma": members["_is_ma"].to_numpy()[pick],
    })

    sk = pd.concat([enc_claims, parts_ref, prof_ref, outside], ignore_index=True)
    sk = sk.sort_values(["service_date", "member_id"]).reset_index(drop=True)

    year = pd.to_datetime(sk["service_date"]).dt.year
    sk["claim_number"] = [
        f"{y}{i:09d}" for y, i in zip(year, range(1, len(sk) + 1))
    ]
    sk["claim_seq"] = np.arange(1, len(sk) + 1)

    # ---- servicing and billing provider assignment
    sk = _assign_claim_providers(rng, sk, prov, fac)
    return sk


def _assign_claim_providers(rng, sk, prov, fac) -> pd.DataFrame:
    """Attach billing and servicing providers.

    Some servicing NPIs will have no credentialing record at all, concentrated
    at the urgent care that staffs through an agency. That orphan is applied
    later by the anomaly stage, not here.
    """
    by_site: dict[str, list[str]] = {}
    for r in prov.itertuples():
        by_site.setdefault(r.primary_site_code, []).append(r.provider_master_id)
    all_ids = prov["provider_master_id"].tolist()

    sites = sk["service_site_code"].to_numpy()
    att = sk["attending_provider_master_id"].to_numpy()
    servicing = np.empty(len(sk), dtype=object)
    for i, (s, a) in enumerate(zip(sites, att)):
        if a is not None and not pd.isna(a):
            servicing[i] = a
        else:
            pool = by_site.get(s) or all_ids
            servicing[i] = pool[int(rng.integers(0, len(pool)))]
    sk["servicing_provider_master_id"] = servicing
    sk["billing_provider_master_id"] = servicing
    return sk


# ---------------------------------------------------------------------- lines

def _build_claim_lines(run, rng, sk, proc, fac, members) -> pd.DataFrame:
    """Explode claims into service lines with procedure codes.

    Code selection is Zipf-weighted within service category, never uniform, so
    99213 and 99214 dominate professional lines the way they do in real data.
    """
    fac_type = {r.site_code: r.facility_type for r in fac.itertuples()}

    # Which service categories a claim can draw from, by role and type.
    def categories_for(role, ctype, cls):
        if role == "FACILITY" and cls == "INPATIENT":
            # Inpatient facility lines carry the room-and-board and ancillary
            # semantics in the REVENUE code; the procedure code is the
            # surgical or ancillary service performed.
            return ["IP_SURGERY", "LAB", "IMAGING", "PT", "SPECIALTY_DRUG"]
        if role == "REFERRAL_EPISODE":
            return ["OP_SURGERY", "ANESTHESIA", "IMAGING"]
        if role == "REFERRAL_CONSULT":
            return ["EM_OFFICE", "IMAGING", "LAB", "PT"]
        if role == "FACILITY":
            return ["EM_ED", "LAB", "IMAGING"]
        if role == "OUTSIDE":
            return ["EM_OFFICE", "LAB", "IMAGING", "OP_SURGERY", "PT"]
        return ["EM_OFFICE", "LAB", "IMAGING", "PT"]

    proc_by_cat: dict[str, pd.DataFrame] = {
        c: g.reset_index(drop=True) for c, g in proc.groupby("service_category")
    }
    cat_weights = {
        c: _zipf_weights(len(g)) for c, g in proc_by_cat.items()
    }

    roles = sk["claim_role"].to_numpy()
    ctypes = sk["claim_type"].to_numpy()
    classes = sk["encounter_class"].to_numpy()

    # Line counts by role. Institutional inpatient claims are line-heavy.
    n_lines = np.where(
        roles == "FACILITY",
        np.where(classes == "INPATIENT", rng.integers(6, 22, len(sk)),
                 rng.integers(2, 7, len(sk))),
        np.where(roles == "REFERRAL_EPISODE", rng.integers(2, 6, len(sk)),
                 rng.integers(1, 5, len(sk))),
    )

    idx = np.repeat(np.arange(len(sk)), n_lines)
    line_no = np.concatenate([np.arange(1, k + 1) for k in n_lines])

    codes = np.empty(len(idx), dtype=object)
    cats = np.empty(len(idx), dtype=object)
    systems = np.empty(len(idx), dtype=object)
    units = np.ones(len(idx))

    # Draw a category then a Zipf-weighted code within it.
    for j, i in enumerate(idx):
        pool = categories_for(roles[i], ctypes[i], classes[i])
        cat = pool[int(rng.integers(0, len(pool)))]
        g = proc_by_cat[cat]
        k = int(rng.choice(len(g), p=cat_weights[cat]))
        codes[j] = g.at[k, "procedure_code"]
        cats[j] = cat
        systems[j] = g.at[k, "code_system"]
        tu = g.at[k, "typical_units"]
        units[j] = max(1, int(rng.poisson(tu)) if tu > 1 else 1)

    lines = pd.DataFrame({
        "claim_number": sk["claim_number"].to_numpy()[idx],
        "claim_line_number": line_no,
        "claim_seq": sk["claim_seq"].to_numpy()[idx],
        "member_id": sk["member_id"].to_numpy()[idx],
        "mrn": sk["mrn"].to_numpy()[idx],
        "encounter_id": sk["encounter_id"].to_numpy()[idx],
        "referral_id": sk["referral_id"].to_numpy()[idx],
        "claim_type": ctypes[idx],
        "claim_role": roles[idx],
        "source_kind": sk["source_kind"].to_numpy()[idx],
        "service_date": sk["service_date"].to_numpy()[idx],
        "service_site_code": sk["service_site_code"].to_numpy()[idx],
        "is_out_of_network": sk["is_out_of_network"].to_numpy()[idx],
        "procedure_code": codes,
        "code_system": systems,
        "service_category": cats,
        "units": units,
        "servicing_provider_master_id": sk["servicing_provider_master_id"].to_numpy()[idx],
        "billing_provider_master_id": sk["billing_provider_master_id"].to_numpy()[idx],
        "latent_risk": sk["latent_risk"].to_numpy()[idx],
        "region": sk["region"].to_numpy()[idx],
        # Carried for claim-level pricing, dropped before the raw file is written.
        "_encounter_class": classes[idx],
        "_los": sk["length_of_stay_days"].to_numpy()[idx],
        "_is_ma": sk["_is_ma"].to_numpy()[idx],
    })

    # ---- place of service, consistent with the facility type
    site_type = np.array([fac_type.get(s, "CLINIC_GROUP") for s in lines["service_site_code"]])
    pos = np.select(
        [site_type == "HOSPITAL", site_type == "ED", site_type == "ASC",
         site_type == "URGENT_CARE", site_type == "SNF", site_type == "LAB",
         site_type == "IMAGING", site_type == "THERAPY"],
        ["21", "23", "24", "20", "31", "81", "22", "11"],
        default="11",
    )
    # A facility-only procedure can never be billed at POS 11.
    fac_only = set(R.FACILITY_ONLY_PROCEDURES)
    is_fac_only = lines["procedure_code"].isin(fac_only).to_numpy()
    pos = np.where((pos == "11") & is_fac_only, "24", pos)
    lines["pos_code"] = pos

    # ---- revenue codes on facility lines only. A CPT on an inpatient
    # facility line with no revenue code is an instant credibility tell.
    rev_codes = [c for c, _ in R.REVENUE_CODES]
    is_facility_line = np.isin(lines["claim_type"].to_numpy(), ["I"])
    lines["revenue_code"] = np.where(
        is_facility_line,
        rng.choice(rev_codes, size=len(lines)),
        None,
    )

    # ---- modifiers, including the bilateral and repeat cases that LOOK like
    # duplicates and are not.
    bil = set(R.BILATERAL_CAPABLE)
    can_bil = lines["procedure_code"].isin(bil).to_numpy()
    mod1 = np.full(len(lines), None, dtype=object)
    r1 = rng.random(len(lines))
    mod1 = np.where(can_bil & (r1 < 0.10), "50", mod1)
    mod1 = np.where(can_bil & (r1 >= 0.10) & (r1 < 0.18), "76", mod1)
    mod1 = np.where(can_bil & (r1 >= 0.18) & (r1 < 0.26), "RT", mod1)
    mod1 = np.where(can_bil & (r1 >= 0.26) & (r1 < 0.34), "LT", mod1)
    is_rad = lines["service_category"].to_numpy() == "IMAGING"
    mod1 = np.where(is_rad & (r1 > 0.72), "26", mod1)
    lines["modifier_1"] = mod1
    lines["modifier_2"] = np.where(
        (lines["service_category"].to_numpy() == "LAB") & (r1 < 0.06), "59", None
    )
    return lines


# --------------------------------------------------------------------- pricing

def _price_lines(run, rng, lines, fac, members) -> pd.DataFrame:
    """Allowed, billed, and the contractual write-off.

    Allowed is a two-part lognormal per service category, scaled by a facility
    contract factor and by the member's latent risk (sicker members get more
    intensive services, not just more of them).
    """
    fac_type = {r.site_code: r.facility_type for r in fac.itertuples()}
    n = len(lines)
    cats = lines["service_category"].to_numpy()
    mu = np.array([COST_MODEL[c][0] for c in cats])
    sigma = np.array([COST_MODEL[c][1] for c in cats])
    allowed = rng.lognormal(mu, sigma)

    # Facility contract factor.
    st = np.array([fac_type.get(s, "CLINIC_GROUP") for s in lines["service_site_code"]])
    lo = np.array([CONTRACT_FACTOR.get(t, (0.9, 1.1))[0] for t in st])
    hi = np.array([CONTRACT_FACTOR.get(t, (0.9, 1.1))[1] for t in st])
    allowed *= lo + rng.random(n) * (hi - lo)

    # Intensity rises with member risk.
    allowed *= C.INTENSITY_BASE + C.INTENSITY_RISK_COEF * np.clip(
        lines["latent_risk"].to_numpy(), 0, C.INTENSITY_RISK_CAP
    )

    # Units drive the line total for time-based and drug codes.
    u = lines["units"].to_numpy()
    allowed *= np.where(u > 1, 1.0 + 0.42 * (u - 1), 1.0)

    # ---- unit-cost trend and elective seasonality
    svc = pd.to_datetime(lines["service_date"])
    year = svc.dt.year.to_numpy()
    month = svc.dt.month.to_numpy()
    allowed *= 1.0 + 0.042 * (year - 2023)
    elective = np.isin(cats, ["OP_SURGERY", "IMAGING", "IP_SURGERY"])
    season = np.array([C.ELECTIVE_SEASONALITY[m] for m in month])
    allowed *= np.where(elective, season, 1.0)

    allowed = np.maximum(allowed, 1.0)
    lines["_raw_allowed"] = allowed

    # ---- claim-level pricing for facility claims and referral episodes.
    # A claim target is drawn once, then apportioned across that claim's lines
    # in proportion to their raw draws, so the line mix stays plausible while
    # the CLAIM total lands on a realistic figure.
    is_oon = lines["is_out_of_network"].to_numpy().astype(bool)
    roles = lines["claim_role"].to_numpy()
    classes_line = lines["claim_role"].to_numpy()  # placeholder, replaced below
    is_ep = roles == "REFERRAL_EPISODE"
    is_fac = (lines["claim_type"].to_numpy() == "I") & ~is_ep

    target = np.full(n, np.nan)

    # Referral episodes carry the in/out-of-network episode gap, which is what
    # makes the headline leakage figure real rather than asserted.
    if is_ep.any():
        base = np.where(is_oon, MSK_EPISODE_OUT_NETWORK, MSK_EPISODE_IN_NETWORK)
        target = np.where(is_ep, base * rng.uniform(0.80, 1.24, n), target)

    if is_fac.any():
        enc_cls = lines["_encounter_class"].to_numpy()
        mu_f = np.array([
            FACILITY_CLAIM_TARGET.get(c, FACILITY_CLAIM_TARGET["UNKNOWN"])[0]
            for c in enc_cls
        ])
        sg_f = np.array([
            FACILITY_CLAIM_TARGET.get(c, FACILITY_CLAIM_TARGET["UNKNOWN"])[1]
            for c in enc_cls
        ])
        fac_target = rng.lognormal(mu_f, sg_f)
        # Inpatient scales with length of stay: a per-diem component on top of
        # the case rate. A 12-day stay should not cost the same as a 2-day one.
        los = lines["_los"].to_numpy().astype(float)
        fac_target *= np.where(enc_cls == "INPATIENT", 0.55 + 0.16 * np.clip(los, 1, 30), 1.0)
        target = np.where(is_fac, fac_target, target)

    claim_priced = ~np.isnan(target)
    if claim_priced.any():
        df = pd.DataFrame({
            "claim_number": lines["claim_number"].to_numpy(),
            "raw": allowed,
            "target": target,
            "priced": claim_priced,
        })
        raw_sum = df.groupby("claim_number")["raw"].transform("sum").to_numpy()
        # One target per claim: take the first line's draw for the whole claim.
        claim_target = df.groupby("claim_number")["target"].transform("first").to_numpy()
        scaled = np.where(
            claim_priced & (raw_sum > 0),
            allowed / raw_sum * claim_target,
            allowed,
        )
        allowed = np.where(claim_priced, scaled, allowed)

    # Medicare reimburses materially less than commercial for the same
    # service. Applied per member line of business.
    is_ma = lines["_is_ma"].to_numpy().astype(bool)
    allowed = allowed * np.where(is_ma, C.MA_REIMBURSEMENT_FACTOR, 1.0)
    allowed = allowed * C.ALLOWED_CALIBRATION

    # ---- catastrophic cohort. Without a genuine high-cost tail the top of
    # the distribution reads synthetic, and stop-loss and reinsurance - a
    # conversation any payer audience recognizes immediately - cannot be
    # demonstrated at all. Transplant, NICU, factor products, CAR-T.
    cat_members = lines["member_id"].drop_duplicates().sample(
        n=min(run.n(N_CATASTROPHIC), lines["member_id"].nunique()),
        random_state=997,
    )
    is_cat = lines["member_id"].isin(set(cat_members)).to_numpy()
    if is_cat.any():
        cur_by_member = (
            pd.Series(allowed).groupby(lines["member_id"].to_numpy()).transform("sum")
            .to_numpy()
        )
        want = rng.uniform(*CATASTROPHIC_RANGE, size=len(lines))
        boost = np.where(
            is_cat & (cur_by_member > 0),
            want / np.maximum(cur_by_member, 1.0),
            1.0,
        )
        allowed = allowed * np.clip(boost, 1.0, None)

    allowed = np.round(np.maximum(allowed, 1.0), 2)
    lines.drop(columns=["_raw_allowed"], inplace=True)

    # ---- billed. Out of network bills a large multiple of allowed.
    billed_mult = np.where(is_oon, OON_BILLED_MULTIPLE, 1.0 + rng.random(n) * 1.6 + 1.15)
    billed = np.round(allowed * billed_mult, 2)

    lines["billed_amount"] = billed
    lines["allowed_amount"] = allowed
    # CO-45: the contractual write-off. An amount, not a denial.
    lines["contractual_writeoff_amount"] = np.round(billed - allowed, 2)
    return lines


# ---------------------------------------------------------------- adjudication

def _adjudicate(run, rng, lines, sk, plans, members) -> pd.DataFrame:
    """Split allowed into paid and member liability, then build headers.

    The member-liability mix follows the benefit-year reset: deductible is 62%
    of liability in January and 11% in December. Anyone who has done payer
    work looks for that January spike and notices when it is missing.
    """
    n = len(lines)
    svc = pd.to_datetime(lines["service_date"])
    month = svc.dt.month.to_numpy()
    allowed = lines["allowed_amount"].to_numpy()

    # ---- denials
    is_denied = rng.random(n) < DENIAL_RATE
    denial_codes = rng.choice(
        ["CO-197", "CO-97", "CO-16", "CO-29", "CO-96"],
        size=n, p=[0.30, 0.26, 0.22, 0.10, 0.12],
    )
    lines["denial_code"] = np.where(is_denied, denial_codes, None)

    # ---- member liability share of allowed
    liability_rate = np.clip(rng.beta(2.0, 7.0, n), 0, 0.85)
    liability = np.round(allowed * liability_rate, 2)
    ded_share = np.array([C.DEDUCTIBLE_SHARE[m] for m in month])
    deductible = np.round(liability * ded_share, 2)
    remaining = np.round(liability - deductible, 2)
    copay = np.round(remaining * 0.45, 2)
    coins = np.round(remaining - copay, 2)

    # ---- coordination of benefits on a small share of lines
    cob = np.where(rng.random(n) < 0.03, np.round(allowed * 0.12, 2), 0.0)

    paid = allowed - deductible - copay - coins - cob
    # Out-of-network pays a reduced share.
    is_oon = lines["is_out_of_network"].to_numpy().astype(bool)
    paid = np.where(is_oon, paid * OON_PAID_SHARE, paid)
    # Denied lines pay nothing at all.
    paid = np.where(is_denied, 0.0, paid)
    paid = np.round(np.maximum(paid, 0.0), 2)

    # The identity allowed = paid + ded + copay + coins + cob must hold to the
    # penny on 100% of lines. Round every other component first, then make
    # COINSURANCE the exact arithmetic residual. Anything else leaves rounding
    # dust that shows up as a reconciliation break downstream.
    deductible = np.round(deductible, 2)
    copay = np.round(copay, 2)
    cob = np.round(cob, 2)
    # Keep the residual non-negative by trimming copay, then deductible, if
    # the fixed components would otherwise exceed allowed less paid.
    room = np.round(allowed - paid, 2)
    over = np.round(deductible + copay + cob - room, 2)
    trim = np.minimum(np.maximum(over, 0.0), copay)
    copay = np.round(copay - trim, 2)
    over = np.round(over - trim, 2)
    trim2 = np.minimum(np.maximum(over, 0.0), deductible)
    deductible = np.round(deductible - trim2, 2)
    over = np.round(over - trim2, 2)
    trim3 = np.minimum(np.maximum(over, 0.0), cob)
    cob = np.round(cob - trim3, 2)
    coins = np.round(room - deductible - copay - cob, 2)

    lines["deductible_amount"] = deductible
    lines["copay_amount"] = copay
    lines["coinsurance_amount"] = coins
    lines["cob_amount"] = cob
    lines["paid_amount"] = paid

    # ---- paid date: lognormal lag off the service date
    lag = np.clip(
        rng.lognormal(C.PAID_LAG_MU, C.PAID_LAG_SIGMA, n).round(), 1, 400
    ).astype(int)
    paid_dt = svc + pd.to_timedelta(lag, unit="D")
    lines["paid_date"] = paid_dt.dt.strftime("%Y-%m-%d")
    lines["paid_lag_days"] = lag

    # ---- runout, as ONE coherent mechanism.
    #
    # A claim is absent from this extract for exactly one reason: it had not
    # adjudicated by the paid-through date. So the claims missing from the most
    # recent service months are precisely the SLOW-adjudicating ones, not a
    # random sample. Modeling it any other way (thinning at random, or
    # thinning on top of a lag cut) produces a month that is incomplete in a
    # way no real extract is, and it double-counts the effect.
    #
    # For the named months the lag distribution is truncated so realized
    # completeness lands on the designed curve, keeping the fastest-paid
    # fraction of each month's volume.
    lines["_svc_ym"] = svc.dt.strftime("%Y-%m")
    keep = (paid_dt <= pd.Timestamp(C.PAID_THROUGH)).to_numpy()
    for month, target in C.RUNOUT_COMPLETENESS.items():
        sel = (lines["_svc_ym"] == month).to_numpy()
        n_month = int(sel.sum())
        if n_month == 0:
            continue
        # Rank that month's lines by how fast they paid; keep the fastest
        # `target` share of the month's FULL volume.
        order = np.full(n_month, np.inf)
        order = lag[sel].astype(float)
        cutoff_idx = int(round(target * n_month))
        if cutoff_idx <= 0:
            keep[sel] = False
            continue
        threshold = np.sort(order)[min(cutoff_idx, n_month) - 1]
        month_keep = order <= threshold
        # Break ties deterministically so the share is exact rather than
        # whatever the tie block happens to contain.
        if month_keep.sum() > cutoff_idx:
            tie = np.flatnonzero(month_keep & (order == threshold))
            excess = int(month_keep.sum() - cutoff_idx)
            month_keep[tie[:excess]] = False
        idx = np.flatnonzero(sel)
        keep[idx] = month_keep
    runout_stats = {}
    for month in C.RUNOUT_COMPLETENESS:
        sel = (lines["_svc_ym"] == month).to_numpy()
        n_month = int(sel.sum())
        if n_month:
            runout_stats[month] = {
                "natural_lines": n_month,
                "retained_lines": int(keep[sel].sum()),
                "retained_share": round(float(keep[sel].sum()) / n_month, 4),
                "designed_share": C.RUNOUT_COMPLETENESS[month],
            }
    lines.attrs["runout_stats"] = runout_stats
    lines = lines[keep].drop(columns=["_svc_ym"]).reset_index(drop=True)

    lines["adjudication_seq"] = 1
    lines["is_current_version"] = True
    lines["net_sign"] = 1
    lines["original_claim_number"] = None
    lines["is_orphan_reversal"] = False
    lines["source_load_batch_id"] = "BATCH-BASE"
    return lines


def _build_headers(rng, lines, sk) -> pd.DataFrame:
    """One row per claim per adjudication version.

    DRG, admit/discharge, LOS, disposition and the claim total live ONLY here,
    so any DRG-by-procedure question is forced through the header/line join.
    """
    agg = lines.groupby("claim_number", as_index=False).agg(
        claim_seq=("claim_seq", "first"),
        member_id=("member_id", "first"),
        mrn=("mrn", "first"),
        encounter_id=("encounter_id", "first"),
        claim_type=("claim_type", "first"),
        claim_role=("claim_role", "first"),
        source_kind=("source_kind", "first"),
        service_site_code=("service_site_code", "first"),
        is_out_of_network=("is_out_of_network", "first"),
        service_from_date=("service_date", "min"),
        service_to_date=("service_date", "max"),
        paid_date=("paid_date", "max"),
        billing_provider_master_id=("billing_provider_master_id", "first"),
        servicing_provider_master_id=("servicing_provider_master_id", "first"),
        line_count=("claim_line_number", "count"),
        total_billed_amount=("billed_amount", "sum"),
        total_allowed_amount=("allowed_amount", "sum"),
        total_claim_paid_amount=("paid_amount", "sum"),
        adjudication_seq=("adjudication_seq", "first"),
        is_current_version=("is_current_version", "first"),
        net_sign=("net_sign", "first"),
    )
    for c in ("total_billed_amount", "total_allowed_amount", "total_claim_paid_amount"):
        agg[c] = agg[c].round(2)

    meta = sk.set_index("claim_number")[
        ["length_of_stay_days", "admit_date", "discharge_date",
         "discharge_disposition", "encounter_class"]
    ]
    agg = agg.merge(meta, left_on="claim_number", right_index=True, how="left")

    # ---- DRG on inpatient facility claims only
    drg = R.build_dim_drg()
    is_ip = (agg["claim_type"] == "I") & (agg["encounter_class"] == "INPATIENT")
    codes = np.full(len(agg), None, dtype=object)
    if is_ip.any():
        w = _zipf_weights(len(drg))
        picks = rng.choice(len(drg), size=int(is_ip.sum()), p=w)
        codes[is_ip.to_numpy()] = drg["drg_code"].to_numpy()[picks]
    agg["drg_code"] = codes

    agg["claim_status_code"] = np.where(
        agg["total_claim_paid_amount"] > 0, "PAID", "DENY_INFO"
    )
    agg["original_claim_number"] = None
    agg["is_orphan_reversal"] = False
    agg["source_load_batch_id"] = "BATCH-BASE"
    return agg


# ------------------------------------------------------- reversals and versions

MONEY_COLS = [
    "billed_amount", "allowed_amount", "paid_amount", "deductible_amount",
    "copay_amount", "coinsurance_amount", "cob_amount",
    "contractual_writeoff_amount",
]


def _apply_versions(run, rng, lines: pd.DataFrame) -> pd.DataFrame:
    """Build the adjudication version chain.

    A reversal is a full negation of the version it supersedes: same lines,
    negated amounts. An adjustment is that reversal plus a new positive
    version. The chain matters - a v3 must negate the v2 REPLACEMENT, not the
    original v1, or the arithmetic stops closing.

      v2 chain:  v1(+) -> rev v1(-) -> repl(+, current)
      v3 chain:  v1(+) -> rev v1(-) -> repl1(+) -> rev repl1(-) -> repl2(+, current)

    Two sanctioned nettings then tie exactly:
        SUM(paid_amount) over every row
        SUM(paid_amount) WHERE is_current_version
    Note the second has NO reversal exclusion. Orphan reversals are current
    and negative on purpose, so filtering them out breaks the tie - which is
    exactly why this function and the orphan anomaly are paired.
    """
    claims = lines["claim_number"].drop_duplicates().to_numpy()
    r = rng.random(len(claims))
    # Disjoint: a claim is adjusted once or twice, never both paths at once.
    v3_ids = set(claims[r < REVERSAL_V3_RATE])
    v2_ids = set(claims[(r >= REVERSAL_V3_RATE) & (r < REVERSAL_V2_RATE)])

    def scaled(df, factor, seq, net, current, batch, orig):
        """Scale a version's money columns, preserving the line identity.

        Scaling each column independently and rounding leaves dust that
        breaks allowed = paid + ded + copay + coins + cob, so coinsurance is
        recomputed as the exact residual afterwards. The identity has to hold
        on every version, not just the original.
        """
        out = df.copy()
        for c in MONEY_COLS:
            out[c] = (out[c] * factor).round(2)
        out["coinsurance_amount"] = (
            out["allowed_amount"]
            - out["paid_amount"]
            - out["deductible_amount"]
            - out["copay_amount"]
            - out["cob_amount"]
        ).round(2)
        out["contractual_writeoff_amount"] = (
            out["billed_amount"] - out["allowed_amount"]
        ).round(2)
        out["adjudication_seq"] = seq
        out["net_sign"] = net
        out["is_current_version"] = current
        out["source_load_batch_id"] = batch
        out["original_claim_number"] = orig
        return out

    frames = [lines]

    # Adjustments trend slightly reductive: audits claw money back more often
    # than they add it. That is what makes an adjudication_seq = 1 filter
    # overstate paid rather than understate it.
    f1 = 0.88
    f2 = 0.93

    if v2_ids:
        base = lines[lines["claim_number"].isin(v2_ids)]
        frames.append(scaled(base, -1.0, 2, -1, False, "BATCH-REV-V2",
                             base["claim_number"]))
        frames.append(scaled(base, f1, 2, 1, True, "BATCH-ADJ-V2",
                             base["claim_number"]))
        lines.loc[lines["claim_number"].isin(v2_ids), "is_current_version"] = False

    if v3_ids:
        base = lines[lines["claim_number"].isin(v3_ids)]
        repl1 = scaled(base, f1, 2, 1, False, "BATCH-ADJ-V2", base["claim_number"])
        frames.append(scaled(base, -1.0, 2, -1, False, "BATCH-REV-V2",
                             base["claim_number"]))
        frames.append(repl1)
        # v3 negates the v2 replacement, not the original.
        frames.append(scaled(repl1, -1.0, 3, -1, False, "BATCH-REV-V3",
                             repl1["claim_number"]))
        frames.append(scaled(repl1, f2, 3, 1, True, "BATCH-ADJ-V3",
                             repl1["claim_number"]))
        lines.loc[lines["claim_number"].isin(v3_ids), "is_current_version"] = False

    L = pd.concat(frames, ignore_index=True)

    # ---- orphan reversals: the original adjudicated before this window
    # opened, so there is nothing here to net against. Retain them, flag them,
    # disclose them. Dropping them hides a real liability; netting them
    # blindly drives a couple of small plan-months negative.
    n_orph = run.n(ORPHAN_REVERSALS)
    donor_claims = (
        L.loc[(L["adjudication_seq"] == 1) & (L["net_sign"] == 1), "claim_number"]
        .drop_duplicates()
    )
    if len(donor_claims) and n_orph:
        take = donor_claims.sample(
            n=min(n_orph, len(donor_claims)), random_state=23
        )
        osel = L[(L["claim_number"].isin(set(take))) & (L["adjudication_seq"] == 1)]
        orph = scaled(osel, -1.0, 1, -1, True, "BATCH-ORPHAN-REV", None)
        orph["original_claim_number"] = "PRE" + osel["claim_number"].to_numpy()
        orph["claim_number"] = "ORPH" + osel["claim_number"].to_numpy()
        orph["is_orphan_reversal"] = True
        L = pd.concat([L, orph], ignore_index=True)

    L["is_reversal"] = L["net_sign"] < 0
    L = L.sort_values(
        ["claim_number", "claim_line_number", "adjudication_seq", "net_sign"]
    ).reset_index(drop=True)
    L.insert(0, "claim_line_key", np.arange(1, len(L) + 1))
    return L


def _build_headers(rng, lines: pd.DataFrame, sk: pd.DataFrame) -> pd.DataFrame:
    """One row per claim per adjudication version, aggregated FROM the lines.

    Built after versioning rather than versioned in parallel, so
    header.total_claim_paid_amount = SUM(line.paid_amount) per (claim,
    version) is true by construction and reconciles to the penny.

    DRG, admit and discharge dates, length of stay, disposition and the claim
    totals live ONLY here, so any DRG-by-procedure question is forced through
    the header-to-line join.
    """
    agg = lines.groupby(["claim_number", "adjudication_seq"], as_index=False).agg(
        claim_seq=("claim_seq", "first"),
        member_id=("member_id", "first"),
        mrn=("mrn", "first"),
        encounter_id=("encounter_id", "first"),
        claim_type=("claim_type", "first"),
        claim_role=("claim_role", "first"),
        source_kind=("source_kind", "first"),
        service_site_code=("service_site_code", "first"),
        is_out_of_network=("is_out_of_network", "first"),
        service_from_date=("service_date", "min"),
        service_to_date=("service_date", "max"),
        paid_date=("paid_date", "max"),
        billing_provider_master_id=("billing_provider_master_id", "first"),
        servicing_provider_master_id=("servicing_provider_master_id", "first"),
        line_count=("claim_line_number", "count"),
        total_billed_amount=("billed_amount", "sum"),
        total_allowed_amount=("allowed_amount", "sum"),
        total_claim_paid_amount=("paid_amount", "sum"),
        net_sign=("net_sign", "first"),
        is_current_version=("is_current_version", "first"),
        is_reversal=("is_reversal", "first"),
        is_orphan_reversal=("is_orphan_reversal", "first"),
        original_claim_number=("original_claim_number", "first"),
        source_load_batch_id=("source_load_batch_id", "first"),
    )
    for c in ("total_billed_amount", "total_allowed_amount", "total_claim_paid_amount"):
        agg[c] = agg[c].round(2)

    meta = sk.drop_duplicates("claim_number").set_index("claim_number")[
        ["length_of_stay_days", "admit_date", "discharge_date",
         "discharge_disposition", "encounter_class"]
    ]
    base_claim = agg["claim_number"].str.replace("^ORPH", "", regex=True)
    agg = agg.join(meta, on=base_claim.rename("base"))
    agg["length_of_stay_days"] = agg["length_of_stay_days"].fillna(0).astype(int)

    # ---- DRG on inpatient facility claims only, Zipf weighted
    drg = R.build_dim_drg()
    is_ip = ((agg["claim_type"] == "I")
             & (agg["encounter_class"] == "INPATIENT")).to_numpy()
    codes = np.full(len(agg), None, dtype=object)
    if is_ip.any():
        w = _zipf_weights(len(drg))
        picks = rng.choice(len(drg), size=int(is_ip.sum()), p=w)
        codes[is_ip] = drg["drg_code"].to_numpy()[picks]
    agg["drg_code"] = codes

    agg["claim_status_code"] = np.select(
        [agg["is_orphan_reversal"].to_numpy(),
         agg["is_reversal"].to_numpy(),
         (agg["adjudication_seq"] > 1).to_numpy(),
         (agg["total_claim_paid_amount"] > 0).to_numpy()],
        ["REVERSED", "REVERSED", "ADJUSTED", "PAID"],
        default="DENY_INFO",
    )
    agg = agg.sort_values(["claim_number", "adjudication_seq"]).reset_index(drop=True)
    agg.insert(0, "claim_header_key", np.arange(1, len(agg) + 1))
    return agg


# ------------------------------------------------------------ header diagnoses

def _build_header_diagnoses(rng, headers, enc, members) -> pd.DataFrame:
    """Diagnoses at HEADER grain, positions 1-12, exactly like an 837.

    Claim LINES carry four small integer pointers into this list rather than
    their own diagnosis codes. That is how an 837P actually works, it avoids a
    third diagnosis bridge, and the unpivot-and-resolve exercise is one no
    other synthetic healthcare dataset bothers to reproduce.
    """
    dx = R.build_dim_diagnosis()
    mem = members.set_index("mrn")
    female_only, male_only = R.FEMALE_ONLY_DX, R.MALE_ONLY_DX
    peds_only = R.PEDIATRIC_ONLY_DX

    uniq = headers.drop_duplicates("claim_number")[["claim_number", "mrn", "service_site_code"]]
    n = len(uniq)
    counts = np.clip(rng.poisson(2.4, n) + 1, 1, 12)
    idx = np.repeat(np.arange(n), counts)
    pos = np.concatenate([np.arange(1, c + 1) for c in counts])

    msk = dx[dx.ccsr_body_system == "Musculoskeletal"].icd10_code.tolist()
    general = dx[dx.sex_restriction.isna() & dx.max_age.isna()].icd10_code.tolist()
    fem = dx[dx.sex_restriction == "F"].icd10_code.tolist()
    male = dx[dx.sex_restriction == "M"].icd10_code.tolist()

    mrns = uniq["mrn"].to_numpy()
    sites = uniq["service_site_code"].to_numpy()
    rand = rng.random(len(idx))
    codes = np.empty(len(idx), dtype=object)
    for j, i in enumerate(idx):
        site = sites[i]
        if site in ("ORTHO-NR", "SPIN-MRD", "ASC-SUMMIT", "ASC-LKSD", "ASC-PINE") \
                and rand[j] < 0.78:
            codes[j] = msk[int(rand[j] * 1e6) % len(msk)]
            continue
        mrn = mrns[i]
        try:
            row = mem.loc[mrn]
            sex, age = row["sex"], int(row["age_2024"])
        except KeyError:
            sex, age = "F", 40
        pool = general
        if rand[j] > 0.94:
            pool = fem if sex == "F" else male
        codes[j] = pool[int(rand[j] * 1e6) % len(pool)]

    return pd.DataFrame({
        "claim_number": uniq["claim_number"].to_numpy()[idx],
        "diagnosis_position": pos,
        "icd10_code": codes,
        "is_primary": pos == 1,
    })
