"""Provider master, SCD2 affiliation history, and the EHR provider directory.

Three things here carry demo weight:
  1. 22% of providers hold two or more concurrent facility affiliations, so a
     careless join to the affiliation bridge fans out and overstates facility
     totals. `allocation_pct` sums to 1.0 per provider-span for anyone who
     wants a weighted answer.
  2. A cardiologist changes facility mid-window, so a current-state provider
     dimension silently reassigns three years of her history.
  3. The EHR provider directory is a SEPARATE, staler copy of network status.
     Its `last_maintained_date` for Summit Point is 14 months behind the
     contract termination, which is the $1.9M finding.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

import config as C
import ids
import names as N
import org

# specialty, taxonomy, service_line, is_pcp, share of provider pool
SPECIALTIES = [
    ("Family medicine", "207Q00000X", "SL07", True, 0.128),
    ("Internal medicine", "207R00000X", "SL07", True, 0.118),
    ("Pediatrics", "208000000X", "SL08", True, 0.074),
    ("Orthopedic surgery", "207X00000X", "SL01", False, 0.062),
    ("Sports medicine", "207XS0106X", "SL03", False, 0.024),
    ("Spine surgery", "207XX0005X", "SL02", False, 0.016),
    ("Physical medicine", "208100000X", "SL04", False, 0.048),
    ("Cardiology", "207RC0000X", "SL05", False, 0.052),
    ("Thoracic surgery", "208G00000X", "SL06", False, 0.010),
    ("Obstetrics and gynecology", "207V00000X", "SL09", False, 0.056),
    ("General surgery", "208600000X", "SL11", False, 0.038),
    ("Gastroenterology", "207RG0100X", "SL12", False, 0.028),
    ("Ophthalmology", "207W00000X", "SL13", False, 0.024),
    ("Hematology and oncology", "207RH0003X", "SL14", False, 0.028),
    ("Pulmonology", "207RP1001X", "SL16", False, 0.022),
    ("Nephrology", "207RN0300X", "SL17", False, 0.018),
    ("Endocrinology", "207RE0101X", "SL18", False, 0.016),
    ("Neurology", "2084N0400X", "SL19", False, 0.024),
    ("Rheumatology", "207RR0500X", "SL20", False, 0.014),
    ("Dermatology", "207N00000X", "SL21", False, 0.022),
    ("Urology", "208800000X", "SL22", False, 0.020),
    ("Emergency medicine", "207P00000X", "SL23", False, 0.062),
    ("Urgent care", "261QU0200X", "SL24", False, 0.036),
    ("Hospitalist", "208M00000X", "SL25", False, 0.040),
    ("Diagnostic radiology", "2085R0202X", "SL26", False, 0.044),
    ("Anesthesiology", "207L00000X", "SL28", False, 0.036),
]

# Which facility types a specialty can primarily sit at.
SITE_AFFINITY = {
    "SL07": ["PRIM-CTR", "PRIM-NLK", "PRIM-EGR", "PRIM-WPT", "MULT-WPT"],
    "SL08": ["PEDS-SBR", "PRIM-NLK", "PRIM-EGR"],
    "SL01": ["ORTHO-NR", "MULT-WPT"],
    "SL03": ["ORTHO-NR"],
    "SL02": ["SPIN-MRD", "ORTHO-NR"],
    "SL04": ["PT-NLK", "PT-CTR", "PT-EGR", "PT-WPT", "SPIN-MRD"],
    "SL05": ["CARD-RVB", "MULT-WPT"],
    "SL06": ["HOSP-RVB"],
    "SL09": ["WMN-SBR", "MULT-WPT"],
    "SL11": ["HOSP-RVB", "HOSP-NLK", "MULT-WPT"],
    "SL12": ["GI-EGR", "MULT-WPT"],
    "SL13": ["MULT-WPT", "ASC-EYE"],
    "SL14": ["ONC-NLK", "ONC-INF"],
    "SL16": ["MULT-WPT", "HOSP-RVB"],
    "SL17": ["MULT-WPT", "DIAL-RVB"],
    "SL18": ["MULT-WPT", "PRIM-CTR"],
    "SL19": ["MULT-WPT", "HOSP-RVB"],
    "SL20": ["MULT-WPT"],
    "SL21": ["MULT-WPT"],
    "SL22": ["MULT-WPT"],
    "SL23": ["ED-RVB", "ED-NLK", "ED-EGR", "ED-WPT"],
    "SL24": ["UC-NORTHGATE", "UC-CTR", "UC-EGR", "UC-WPT", "UC-SBR", "UC-RVB",
             "UC-NLK", "UC-HLC"],
    "SL25": ["HOSP-RVB", "HOSP-NLK", "HOSP-EGR", "HOSP-WPT"],
    "SL26": ["IMG-RVB", "IMG-NLK", "IMG-EGR"],
    "SL28": ["HOSP-RVB", "HOSP-NLK", "ASC-RVB", "ASC-NLK"],
}

# The cardiologist whose affiliation changes mid-window (SCD2 teaching case).
AFFILIATION_MOVE_DATE = date(2024, 8, 12)

# Share of providers holding two or more concurrent facility affiliations.
MULTI_SITE_RATE = 0.22


def build_providers(run: C.RunConfig, fac: pd.DataFrame) -> dict[str, pd.DataFrame]:
    rng = run.rng("providers")
    n_prov = max(140, run.scale.n_members // 18)

    shares = np.array([s for *_, s in SPECIALTIES])
    shares = shares / shares.sum()
    pick = rng.choice(len(SPECIALTIES), size=n_prov, p=shares)

    site_by_code = {r.site_code: r for r in fac.itertuples()}

    rows = []
    npis = ids.mint_npis(rng, n_prov)  # deliberately invalid check digits
    for i in range(n_prov):
        spec, taxonomy, sl, is_pcp, _ = SPECIALTIES[pick[i]]
        candidates = SITE_AFFINITY[sl]
        primary = str(rng.choice(candidates))
        sex = "F" if rng.random() < 0.44 else "M"
        birth_year = int(rng.integers(1955, 1992))
        pool = N.given_name_pool(sex, birth_year)
        rows.append({
            "provider_seq": i + 1,
            "npi": npis[i],
            "provider_master_id": f"PRV{i+1:06d}",
            "ehr_provider_id": f"EP{100000 + (i + 1) * 7}",
            "first_name": pool[int(rng.integers(0, len(pool)))],
            "last_name": str(rng.choice(N.SURNAMES)),
            "credential": "MD" if rng.random() < 0.78 else "DO",
            "sex": sex,
            "primary_specialty": spec,
            "taxonomy_code": taxonomy,
            "service_line_code": sl,
            "is_pcp": is_pcp,
            "primary_site_code": primary,
            "primary_facility_id": site_by_code[primary].facility_id,
            "tin": site_by_code[primary].tin,
        })
    prov = pd.DataFrame(rows)

    # ---- the three mid-volume ORTHO-NR specialists who route to Summit Point
    ortho_nr = prov[
        (prov.primary_site_code == "ORTHO-NR")
        & (prov.service_line_code.isin(["SL01", "SL03"]))
    ]
    n_leak = min(3, len(ortho_nr))
    leakers = list(ortho_nr.provider_master_id.iloc[:n_leak]) if n_leak else []
    prov["routes_to_summit_point"] = prov.provider_master_id.isin(leakers)

    # ---- the cardiologist who changes facility mid-window
    cards = prov[prov.service_line_code == "SL05"]
    mover = cards.provider_master_id.iloc[0] if len(cards) else None
    prov["changes_affiliation"] = prov.provider_master_id == mover

    # ---- concurrent multi-site affiliation for 22% of providers
    # Concentrated in cardiology and orthopedics, which is what makes the
    # fan-out change the facility RANKING and not merely the total. The
    # specialty weighting is normalized so the OVERALL rate stays at 22%
    # rather than drifting up as a side effect of the concentration.
    weight = np.where(
        prov.service_line_code.isin(["SL01", "SL02", "SL03", "SL05"]).to_numpy(),
        2.4, 1.0,
    )
    p_multi = np.clip(MULTI_SITE_RATE * weight / weight.mean(), 0.0, 0.95)
    prov["is_multi_site"] = rng.random(len(prov)) < p_multi

    affiliations = _build_affiliations(rng, prov, fac)
    prov_scd2 = _build_provider_scd2(prov, fac)
    directory = _build_ehr_directory(rng, prov, fac)

    return {
        "provider_master": prov,
        "provider_scd2": prov_scd2,
        "affiliation": affiliations,
        "ehr_provider_directory": directory,
    }


def _build_affiliations(
    rng: np.random.Generator, prov: pd.DataFrame, fac: pd.DataFrame
) -> pd.DataFrame:
    """One row per provider x facility x effective span, with allocation_pct.

    allocation_pct sums to 1.0 per provider per span, so a weighted join gives
    the right answer. An unweighted join fans out. Both are possible on
    purpose: the bridge is correct, the careless usage is the trap.
    """
    by_code = {r.site_code: r for r in fac.itertuples()}
    rows = []
    key = 1
    for p in prov.itertuples():
        sl = p.service_line_code
        sites = [p.primary_site_code]
        if p.is_multi_site:
            extra_pool = [s for s in SITE_AFFINITY[sl] if s != p.primary_site_code]
            # Orthopedic and cardiology practices also hold hospital privileges.
            if sl in ("SL01", "SL02", "SL03"):
                extra_pool += ["HOSP-RVB", "HOSP-NLK", "ASC-RVB", "ASC-NLK"]
            if sl == "SL05":
                extra_pool += ["HOSP-RVB", "HOSP-NLK"]
            extra_pool = sorted(set(extra_pool))
            if extra_pool:
                # 1 extra site usually, occasionally 2 or 3. Mean ~1.44, which
                # with a 22% multi-site rate lands the unweighted-join fan-out
                # near the 31.6% the anomaly manifest advertises.
                n_extra = int(rng.choice([1, 2, 3], p=[0.64, 0.28, 0.08]))
                n_extra = min(n_extra, len(extra_pool))
                sites += list(rng.choice(extra_pool, size=n_extra, replace=False))
        sites = list(dict.fromkeys(sites))

        # Allocation weights, primary site dominant, summing to exactly 1.0.
        # The last weight absorbs the rounding remainder so the bridge always
        # ties to 1.0000 and a weighted join reconciles to the penny.
        if len(sites) > 1:
            share = round(0.38 / (len(sites) - 1), 4)
            w = np.array([0.62] + [share] * (len(sites) - 1))
            w[-1] = round(1.0 - w[:-1].sum(), 4)
        else:
            w = np.array([1.0])

        if p.changes_affiliation:
            # Same provider, two spans, different facility in each.
            new_site = "CARD-RVB" if p.primary_site_code != "CARD-RVB" else "HOSP-RVB"
            for span_start, span_end, site in (
                (C.SOURCE_START, AFFILIATION_MOVE_DATE - timedelta(days=1),
                 p.primary_site_code),
                (AFFILIATION_MOVE_DATE, date(9999, 12, 31), new_site),
            ):
                rows.append({
                    "affiliation_key": key, "provider_master_id": p.provider_master_id,
                    "npi": p.npi, "site_code": site,
                    "facility_id": by_code[site].facility_id,
                    "effective_date": span_start.isoformat(),
                    "expiration_date": span_end.isoformat(),
                    "allocation_pct": 1.0, "is_primary_site": True,
                    "affiliation_note": "Practice relocation",
                })
                key += 1
            continue

        for site, weight in zip(sites, w):
            rows.append({
                "affiliation_key": key, "provider_master_id": p.provider_master_id,
                "npi": p.npi, "site_code": site,
                "facility_id": by_code[site].facility_id,
                "effective_date": C.SOURCE_START.isoformat(),
                "expiration_date": "9999-12-31",
                "allocation_pct": round(float(weight), 4),
                "is_primary_site": site == p.primary_site_code,
                "affiliation_note": None,
            })
            key += 1
    return pd.DataFrame(rows)


def _build_provider_scd2(prov: pd.DataFrame, fac: pd.DataFrame) -> pd.DataFrame:
    """Type 2 provider dimension keyed on the tracked attributes."""
    by_code = {r.site_code: r for r in fac.itertuples()}
    rows = []
    key = 1
    for p in prov.itertuples():
        spans = [(C.SOURCE_START, date(9999, 12, 31), p.primary_site_code)]
        if p.changes_affiliation:
            new_site = "CARD-RVB" if p.primary_site_code != "CARD-RVB" else "HOSP-RVB"
            spans = [
                (C.SOURCE_START, AFFILIATION_MOVE_DATE - timedelta(days=1),
                 p.primary_site_code),
                (AFFILIATION_MOVE_DATE, date(9999, 12, 31), new_site),
            ]
        for start, end, site in spans:
            f = by_code[site]
            rows.append({
                "provider_key": key,
                "provider_master_id": p.provider_master_id,
                "npi": p.npi,
                "ehr_provider_id": p.ehr_provider_id,
                "provider_name": f"{p.first_name} {p.last_name}, {p.credential}",
                "first_name": p.first_name,
                "last_name": p.last_name,
                "sex": p.sex,
                "primary_specialty": p.primary_specialty,
                "taxonomy_code": p.taxonomy_code,
                "service_line_code": p.service_line_code,
                "is_pcp": p.is_pcp,
                "site_code": site,
                "facility_id": f.facility_id,
                "tin": f.tin,
                "network_status": "PAR" if f.is_in_network_current else "NONPAR",
                "row_effective_date": start.isoformat(),
                "row_expiration_date": end.isoformat(),
                "is_current": end == date(9999, 12, 31),
            })
            key += 1
    return pd.DataFrame(rows)


def _build_ehr_directory(
    rng: np.random.Generator, prov: pd.DataFrame, fac: pd.DataFrame
) -> pd.DataFrame:
    """The EHR referral pick-list. A separate, staler copy of network status.

    Summit Point still reads PAR here long after its contract terminated,
    because nobody maintains the directory. That gap is the $1.9M finding and
    it is a governance failure, not a clinical one.
    """
    rows = []
    for f in fac.itertuples():
        if f.site_code == "ASC-SUMMIT":
            status, maintained = "PAR", "2024-08-15"   # 14 months stale
        elif f.site_code in org.OUT_OF_NETWORK_MSK_ASCS:
            status, maintained = "NONPAR", "2025-09-30"
        else:
            status = "PAR" if f.is_in_network_current else "NONPAR"
            maintained = "2025-11-15"
        rows.append({
            "ehr_dept_id": (
                org.RENUMBERED_NEW_DEPT if f.site_code == org.RENUMBERED_SITE
                else f"RB-{f.site_code}"
            ),
            "site_code": f.site_code,
            "facility_display_name": f.facility_name,
            "referral_network_status": status,
            "accepts_referrals": True,
            "last_maintained_date": maintained,
        })
    return pd.DataFrame(rows)
