"""Northlake Health Partners org structure: facilities, plans, network contracts.

Every name here is invented. ZIPs are plausible Kansas City metro values not
tied to any real facility address.

Two entities carry the demo's weight:
  ORTHO-NR  North Ridge Orthopedics - the clinic group with the auto-close rule
  ASC-SUMMIT Summit Point Surgery Center - TIN terminated 2024-10-01 while the
             EHR referral directory kept reading PAR for 14 more months
"""
from __future__ import annotations

import pandas as pd

import config as C
import ids

REGIONS = ["North", "South", "East", "West", "Central"]

# Region-to-region drive time in minutes. Serves the geography finding without
# a geospatial model.
DRIVE_TIME = {
    ("North", "North"): 9, ("North", "Central"): 18, ("North", "East"): 34,
    ("North", "West"): 41, ("North", "South"): 52,
    ("South", "South"): 11, ("South", "Central"): 21, ("South", "East"): 38,
    ("South", "West"): 33, ("South", "North"): 52,
    ("East", "East"): 10, ("East", "Central"): 19, ("East", "North"): 34,
    ("East", "South"): 38, ("East", "West"): 55,
    ("West", "West"): 12, ("West", "Central"): 22, ("West", "North"): 41,
    ("West", "South"): 33, ("West", "East"): 55,
    ("Central", "Central"): 8, ("Central", "North"): 18, ("Central", "South"): 21,
    ("Central", "East"): 19, ("Central", "West"): 22,
}


def drive_time(member_region: str, facility_region: str) -> int:
    return DRIVE_TIME[(member_region, facility_region)]


# facility_id, site_code, name, type, region, zip, beds, in_network, service_line_group
FACILITIES = [
    # Four hospitals
    ("100010", "HOSP-RVB", "Riverbend Medical Center", "HOSPITAL", "Central", "64108", 412, True, "ACUTE"),
    ("100020", "HOSP-NLK", "Northlake General Hospital", "HOSPITAL", "North", "64118", 288, True, "ACUTE"),
    ("100030", "HOSP-EGR", "Eastgate Regional Hospital", "HOSPITAL", "East", "64133", 196, True, "ACUTE"),
    ("100040", "HOSP-WPT", "Westport Community Hospital", "HOSPITAL", "West", "66212", 124, True, "ACUTE"),
    # Twelve ambulatory clinic groups
    ("200010", "ORTHO-NR", "North Ridge Orthopedics", "CLINIC_GROUP", "North", "64119", 0, True, "MSK"),
    ("200020", "PRIM-CTR", "Centerline Primary Care", "CLINIC_GROUP", "Central", "64111", 0, True, "PRIMARY"),
    ("200030", "PRIM-NLK", "Northlake Family Medicine", "CLINIC_GROUP", "North", "64116", 0, True, "PRIMARY"),
    ("200040", "PRIM-EGR", "Eastgate Family Health", "CLINIC_GROUP", "East", "64134", 0, True, "PRIMARY"),
    ("200050", "PRIM-WPT", "Westport Internal Medicine", "CLINIC_GROUP", "West", "66214", 0, True, "PRIMARY"),
    ("200060", "PEDS-SBR", "Sunberry Pediatrics", "CLINIC_GROUP", "South", "64131", 0, True, "PRIMARY"),
    ("200070", "CARD-RVB", "Riverbend Cardiology Institute", "CLINIC_GROUP", "Central", "64108", 0, True, "CARDIO"),
    ("200080", "SPIN-MRD", "Meridian Spine and Pain", "CLINIC_GROUP", "Central", "64112", 0, True, "MSK"),
    ("200090", "GI-EGR", "Eastgate Digestive Health", "CLINIC_GROUP", "East", "64136", 0, True, "SURGICAL"),
    ("200100", "ONC-NLK", "Northlake Cancer Center", "CLINIC_GROUP", "North", "64117", 0, True, "ONC"),
    ("200110", "WMN-SBR", "Sunberry Women's Health", "CLINIC_GROUP", "South", "64132", 0, True, "WOMENS"),
    ("200120", "MULT-WPT", "Westport Multispecialty Group", "CLINIC_GROUP", "West", "66215", 0, True, "MEDICAL"),
    # Eight urgent care
    ("300010", "UC-NORTHGATE", "Northgate Urgent Care", "URGENT_CARE", "North", "64118", 0, True, "ACUTE"),
    ("300020", "UC-CTR", "Centerline Urgent Care", "URGENT_CARE", "Central", "64110", 0, True, "ACUTE"),
    ("300030", "UC-EGR", "Eastgate Urgent Care", "URGENT_CARE", "East", "64133", 0, True, "ACUTE"),
    ("300040", "UC-WPT", "Westport Urgent Care", "URGENT_CARE", "West", "66213", 0, True, "ACUTE"),
    ("300050", "UC-SBR", "Sunberry Urgent Care", "URGENT_CARE", "South", "64130", 0, True, "ACUTE"),
    ("300060", "UC-RVB", "Riverbend Express Care", "URGENT_CARE", "Central", "64109", 0, True, "ACUTE"),
    ("300070", "UC-NLK", "Northlake Walk-In Clinic", "URGENT_CARE", "North", "64115", 0, True, "ACUTE"),
    ("300080", "UC-HLC", "Hillcrest Urgent Care", "URGENT_CARE", "South", "64137", 0, True, "ACUTE"),
    # Ten ambulatory surgery centers - four of them out of network
    ("400010", "ASC-RVB", "Riverbend Surgery Center", "ASC", "Central", "64108", 0, True, "SURGICAL"),
    ("400020", "ASC-NLK", "Northlake Ambulatory Surgery", "ASC", "North", "64116", 0, True, "SURGICAL"),
    ("400030", "ASC-EGR", "Eastgate Day Surgery", "ASC", "East", "64134", 0, True, "SURGICAL"),
    ("400040", "ASC-SUMMIT", "Summit Point Surgery Center", "ASC", "North", "64120", 0, False, "MSK"),
    ("400050", "ASC-LKSD", "Lakeside Orthopedic Surgery Center", "ASC", "North", "64121", 0, False, "MSK"),
    ("400060", "ASC-PINE", "Pinehurst Surgical Institute", "ASC", "West", "66216", 0, False, "MSK"),
    ("400070", "ASC-CRST", "Crestview Ambulatory Surgery", "ASC", "South", "64138", 0, False, "SURGICAL"),
    ("400080", "ASC-WPT", "Westport Surgery Center", "ASC", "West", "66214", 0, True, "SURGICAL"),
    ("400090", "ASC-EYE", "Clearview Eye Surgery Center", "ASC", "Central", "64113", 0, True, "SURGICAL"),
    ("400100", "ASC-SBR", "Sunberry Outpatient Surgery", "ASC", "South", "64131", 0, True, "SURGICAL"),
    # Two skilled nursing
    ("500010", "SNF-NLK", "Northlake Transitional Care", "SNF", "North", "64117", 96, True, "ACUTE"),
    ("500020", "SNF-RVB", "Riverbend Rehabilitation Center", "SNF", "Central", "64109", 72, True, "ACUTE"),
    # Diagnostic, lab, therapy, other
    ("600010", "IMG-RVB", "Riverbend Imaging", "IMAGING", "Central", "64108", 0, True, "DIAGNOSTIC"),
    ("600020", "IMG-NLK", "Northlake Diagnostic Imaging", "IMAGING", "North", "64116", 0, True, "DIAGNOSTIC"),
    ("600030", "IMG-EGR", "Eastgate Imaging Partners", "IMAGING", "East", "64135", 0, True, "DIAGNOSTIC"),
    ("600040", "IMG-OPEN", "OpenView MRI", "IMAGING", "West", "66217", 0, False, "DIAGNOSTIC"),
    ("600050", "LAB-CENT", "Central Valley Reference Laboratory", "LAB", "Central", "64114", 0, True, "DIAGNOSTIC"),
    ("600060", "LAB-EXT", "Meridian External Lab Network", "LAB", "Central", "64115", 0, False, "DIAGNOSTIC"),
    ("600070", "PT-NLK", "Northlake Physical Therapy", "THERAPY", "North", "64118", 0, True, "MSK"),
    ("600080", "PT-CTR", "Centerline Rehab and Sports", "THERAPY", "Central", "64111", 0, True, "MSK"),
    ("600090", "PT-EGR", "Eastgate Physical Therapy", "THERAPY", "East", "64133", 0, True, "MSK"),
    ("600100", "PT-WPT", "Westport Sports Rehab", "THERAPY", "West", "66213", 0, True, "MSK"),
    ("600110", "ONC-INF", "Northlake Infusion Center", "INFUSION", "North", "64117", 0, True, "ONC"),
    ("600120", "DIAL-RVB", "Riverbend Dialysis", "DIALYSIS", "Central", "64110", 0, True, "MEDICAL"),
    ("600130", "ED-RVB", "Riverbend Emergency Department", "ED", "Central", "64108", 0, True, "ACUTE"),
    ("600140", "ED-NLK", "Northlake Emergency Department", "ED", "North", "64118", 0, True, "ACUTE"),
    ("600150", "ED-EGR", "Eastgate Emergency Department", "ED", "East", "64133", 0, True, "ACUTE"),
    ("600160", "ED-WPT", "Westport Emergency Department", "ED", "West", "66212", 0, True, "ACUTE"),
]

# The twelve clinic groups ranked in the demo, and their attributed panel size.
CLINIC_GROUPS = [
    "ORTHO-NR", "PRIM-CTR", "PRIM-NLK", "PRIM-EGR", "PRIM-WPT", "PEDS-SBR",
    "CARD-RVB", "SPIN-MRD", "GI-EGR", "ONC-NLK", "WMN-SBR", "MULT-WPT",
]

# Panel weights. North Ridge holds ~4,800 lives at demo scale (48k total).
PANEL_WEIGHTS = {
    "ORTHO-NR": 0.100, "PRIM-CTR": 0.132, "PRIM-NLK": 0.118, "PRIM-EGR": 0.104,
    "PRIM-WPT": 0.098, "PEDS-SBR": 0.092, "CARD-RVB": 0.058, "SPIN-MRD": 0.046,
    "GI-EGR": 0.044, "ONC-NLK": 0.036, "WMN-SBR": 0.098, "MULT-WPT": 0.074,
}

# Hospital renumbered in the mid-2024 EMR upgrade. The EHR emits a second
# dept_id from RENUMBER_EFFECTIVE forward, so one physical hospital splits in
# two unless the facility crosswalk is applied.
RENUMBERED_SITE = "HOSP-EGR"
RENUMBERED_OLD_DEPT = "RB-EGR-030"
RENUMBERED_NEW_DEPT = "RB-EAST-141"

# Urgent care that staffs through an agency, producing orphan servicing NPIs.
STAFFING_AGENCY_SITE = "UC-NORTHGATE"

OUT_OF_NETWORK_MSK_ASCS = ["ASC-SUMMIT", "ASC-LKSD", "ASC-PINE"]

# Which sites can actually perform musculoskeletal surgery, and how many cases
# a year they have block time for.
#
# This exists because "recapturable leakage" is not the same number as "leaked
# leakage", and the difference has to live IN the data as a documented
# attribute rather than being assumed by whoever runs the analysis. A clinic
# group cannot perform surgery at all; an ASC can, but only up to its block
# time. Northlake's in-network surgical capacity is materially smaller than
# the volume leaking out, which is the honest counterweight to the headline
# finding and the beat that stops a recommendation over-promising.
MSK_SURGICAL_CAPACITY = {
    "ASC-RVB": 900, "ASC-NLK": 650, "ASC-EGR": 400, "ASC-WPT": 350,
    "ASC-SBR": 300, "HOSP-RVB": 700, "HOSP-NLK": 450,
    # Out-of-network sites, listed so the comparison is apples to apples.
    "ASC-SUMMIT": 2400, "ASC-LKSD": 1500, "ASC-PINE": 1400, "ASC-CRST": 1200,
}


def build_dim_facility(rng) -> pd.DataFrame:
    tins = ids.mint_tins(rng, len(FACILITIES))
    rows = []
    for i, (fid, code, name, ftype, region, zipc, beds, innet, slg) in enumerate(
        FACILITIES, 1
    ):
        rows.append({
            "facility_key": i,
            "facility_id": fid,
            "site_code": code,
            "facility_name": name,
            "facility_type": ftype,
            "region": region,
            "postal_code": zipc,
            "bed_count": beds,
            "is_in_network_current": innet,
            "service_line_group": slg,
            "tin": tins[i - 1],
            "ccn": f"26{1000 + i}" if ftype in ("HOSPITAL", "SNF") else None,
            "is_clinic_group": code in CLINIC_GROUPS,
            "attributed_panel_weight": PANEL_WEIGHTS.get(code, 0.0),
            "performs_msk_surgery": code in MSK_SURGICAL_CAPACITY,
            "annual_msk_case_capacity": MSK_SURGICAL_CAPACITY.get(code, 0),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------- network contract

def build_network_contract(fac: pd.DataFrame) -> pd.DataFrame:
    """SCD2 network participation by TIN and plan effective window.

    Summit Point terminates 2024-10-01. Everything else runs the full window.
    An as-of-service-date join against this table is the only correct way to
    answer 'was this provider in network when the care happened'.
    """
    rows = []
    key = 1
    for _, f in fac.iterrows():
        if f["site_code"] == "ASC-SUMMIT":
            # In network until termination, then out.
            rows.append({
                "network_contract_key": key, "tin": f["tin"],
                "facility_id": f["facility_id"], "site_code": f["site_code"],
                "network_status": "PAR",
                "effective_date": C.SOURCE_START.isoformat(),
                "expiration_date": (C.SUMMIT_POINT_TERM - pd.Timedelta(days=1)).date().isoformat()
                if hasattr(C.SUMMIT_POINT_TERM, "date") else "2024-09-30",
                "is_current": False,
                "termination_reason": "Contract not renewed",
            })
            key += 1
            rows.append({
                "network_contract_key": key, "tin": f["tin"],
                "facility_id": f["facility_id"], "site_code": f["site_code"],
                "network_status": "NONPAR",
                "effective_date": C.SUMMIT_POINT_TERM.isoformat(),
                "expiration_date": "9999-12-31",
                "is_current": True,
                "termination_reason": None,
            })
            key += 1
        else:
            rows.append({
                "network_contract_key": key, "tin": f["tin"],
                "facility_id": f["facility_id"], "site_code": f["site_code"],
                "network_status": "PAR" if f["is_in_network_current"] else "NONPAR",
                "effective_date": C.SOURCE_START.isoformat(),
                "expiration_date": "9999-12-31",
                "is_current": True,
                "termination_reason": None,
            })
            key += 1
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ coverage plans

def build_dim_coverage_plan() -> pd.DataFrame:
    """Two risk contracts with Meridian, across three benefit years.

    HMO and Medicare Advantage only. No PPO: referrals are advisory in a PPO
    and a healthcare audience will say so out loud, which collapses the whole
    referral-leakage premise.
    """
    rows = []
    key = 1
    products = [
        ("MHMO", "Meridian Commercial HMO", "COMMERCIAL", "HMO", "FULLY_INSURED",
         "Silver", 2500, 7500),
        ("MHMO-HD", "Meridian Commercial HMO High Deductible", "COMMERCIAL", "HMO",
         "FULLY_INSURED", "Bronze", 5000, 9100),
        ("MHMO-ASO", "Meridian Commercial HMO Self-Funded", "COMMERCIAL", "HMO",
         "ASO", "Gold", 1500, 5000),
        ("MMA-HMO", "Meridian Medicare Advantage HMO", "MEDICARE_ADVANTAGE", "HMO",
         "FULLY_INSURED", None, 0, 4500),
        ("MMA-DSNP", "Meridian MA Dual Special Needs", "MEDICARE_ADVANTAGE", "HMO",
         "FULLY_INSURED", None, 0, 3200),
    ]
    for year in (2023, 2024, 2025):
        for code, name, lob, prod, funding, tier, deduct, oop in products:
            infl = 1.0 + 0.05 * (year - 2023)
            rows.append({
                "coverage_plan_key": key,
                "plan_code": f"{code}-{year}",
                "plan_name": name,
                "payer_name": "Meridian Health Plan",
                "line_of_business": lob,
                "product": prod,
                "funding_type": funding,
                "metal_tier": tier,
                "benefit_year": year,
                "deductible_amount": round(deduct * infl, 2),
                "oop_max_amount": round(oop * infl, 2),
                "requires_referral": True,
                "is_risk_contract": True,
            })
            key += 1
    return pd.DataFrame(rows)


# ------------------------------------------------ deliberately imperfect crosswalks

def build_service_line_crosswalk() -> pd.DataFrame:
    """Claim taxonomy / EHR department / contract category -> service line.

    Two gaps are planted here on purpose:
      - the arthroscopy CPT range maps two different ways, worth a ~7% swing
        in MSK totals depending on which mapping an analyst picks
      - one EHR encounter-type value has no row at all
    """
    rows = [
        ("CLAIM_TAXONOMY", "207X00000X", "SL01", "Orthopedic surgery", 1),
        ("CLAIM_TAXONOMY", "207XS0106X", "SL03", "Sports medicine", 1),
        ("CLAIM_TAXONOMY", "207XX0005X", "SL02", "Spine surgery", 1),
        ("CLAIM_TAXONOMY", "208100000X", "SL04", "Physical medicine", 1),
        ("CLAIM_TAXONOMY", "207RC0000X", "SL05", "Cardiology", 1),
        ("CLAIM_TAXONOMY", "208G00000X", "SL06", "Thoracic surgery", 1),
        ("CLAIM_TAXONOMY", "207Q00000X", "SL07", "Family medicine", 1),
        ("CLAIM_TAXONOMY", "207R00000X", "SL07", "Internal medicine", 1),
        ("CLAIM_TAXONOMY", "208000000X", "SL08", "Pediatrics", 1),
        ("CLAIM_TAXONOMY", "207V00000X", "SL09", "Obstetrics and gynecology", 1),
        ("CLAIM_TAXONOMY", "208600000X", "SL11", "General surgery", 1),
        ("CLAIM_TAXONOMY", "207RG0100X", "SL12", "Gastroenterology", 1),
        ("CLAIM_TAXONOMY", "207W00000X", "SL13", "Ophthalmology", 1),
        ("CLAIM_TAXONOMY", "207RH0003X", "SL14", "Hematology and oncology", 1),
        ("CLAIM_TAXONOMY", "207RP1001X", "SL16", "Pulmonology", 1),
        ("CLAIM_TAXONOMY", "207RN0300X", "SL17", "Nephrology", 1),
        ("CLAIM_TAXONOMY", "207RE0101X", "SL18", "Endocrinology", 1),
        ("CLAIM_TAXONOMY", "2084N0400X", "SL19", "Neurology", 1),
        ("CLAIM_TAXONOMY", "207RR0500X", "SL20", "Rheumatology", 1),
        ("CLAIM_TAXONOMY", "207N00000X", "SL21", "Dermatology", 1),
        ("CLAIM_TAXONOMY", "208800000X", "SL22", "Urology", 1),
        ("CLAIM_TAXONOMY", "207P00000X", "SL23", "Emergency medicine", 1),
        ("CLAIM_TAXONOMY", "261QU0200X", "SL24", "Urgent care", 1),
        ("CLAIM_TAXONOMY", "208M00000X", "SL25", "Hospitalist", 1),
        ("CLAIM_TAXONOMY", "2085R0202X", "SL26", "Diagnostic radiology", 1),
        ("CLAIM_TAXONOMY", "291U00000X", "SL27", "Clinical laboratory", 1),
        ("CLAIM_TAXONOMY", "207L00000X", "SL28", "Anesthesiology", 1),
        # Arthroscopy mapped two ways - version 1 calls it orthopedics,
        # version 2 calls it sports medicine. Both rows are "active".
        ("PROCEDURE_RANGE", "29800-29999", "SL01", "Arthroscopy as orthopedics", 1),
        ("PROCEDURE_RANGE", "29800-29999", "SL03", "Arthroscopy as sports medicine", 2),
        ("EHR_DEPARTMENT", "OFFICE", "SL07", "Office visit", 1),
        ("EHR_DEPARTMENT", "OFFICE VISIT", "SL07", "Office visit, long form", 1),
        ("EHR_DEPARTMENT", "ORTHO", "SL01", "Orthopedics", 1),
        ("EHR_DEPARTMENT", "SPINE", "SL02", "Spine", 1),
        ("EHR_DEPARTMENT", "CARDIO", "SL05", "Cardiology", 1),
        ("EHR_DEPARTMENT", "PEDS", "SL08", "Pediatrics", 1),
        ("EHR_DEPARTMENT", "OBGYN", "SL09", "Women's health", 1),
        ("EHR_DEPARTMENT", "GI", "SL12", "Gastroenterology", 1),
        ("EHR_DEPARTMENT", "ONC", "SL14", "Oncology", 1),
        ("EHR_DEPARTMENT", "ED", "SL23", "Emergency", 1),
        ("EHR_DEPARTMENT", "URGENT", "SL24", "Urgent care", 1),
        ("EHR_DEPARTMENT", "IMAGING", "SL26", "Imaging", 1),
        ("EHR_DEPARTMENT", "LAB", "SL27", "Laboratory", 1),
        ("EHR_DEPARTMENT", "PT", "SL04", "Physical therapy", 1),
        # NOTE: 'AMB' is deliberately absent. One clinic emits it and 3.1% of
        # ambulatory volume lands as UNKNOWN until someone profiles the values.
    ]
    return pd.DataFrame([
        {"crosswalk_domain": d, "source_value": s, "service_line_code": t,
         "mapping_note": n, "mapping_version": v}
        for d, s, t, n, v in rows
    ])


def build_facility_crosswalk(fac: pd.DataFrame) -> pd.DataFrame:
    """EHR dept_id -> claims facility_id, including the renumbered hospital."""
    rows = []
    for _, f in fac.iterrows():
        code = f["site_code"]
        if code == RENUMBERED_SITE:
            rows.append({
                "ehr_dept_id": RENUMBERED_OLD_DEPT, "facility_id": f["facility_id"],
                "site_code": code, "effective_date": C.SOURCE_START.isoformat(),
                "expiration_date": (C.RENUMBER_EFFECTIVE - pd.Timedelta(days=1)).date().isoformat()
                if hasattr(C.RENUMBER_EFFECTIVE, "date") else "2024-04-30",
                "crosswalk_note": "Pre-upgrade department identifier",
            })
            rows.append({
                "ehr_dept_id": RENUMBERED_NEW_DEPT, "facility_id": f["facility_id"],
                "site_code": code, "effective_date": C.RENUMBER_EFFECTIVE.isoformat(),
                "expiration_date": "9999-12-31",
                "crosswalk_note": "Post-upgrade department identifier, same physical site",
            })
        else:
            rows.append({
                "ehr_dept_id": f"RB-{code}", "facility_id": f["facility_id"],
                "site_code": code, "effective_date": C.SOURCE_START.isoformat(),
                "expiration_date": "9999-12-31", "crosswalk_note": None,
            })
    return pd.DataFrame(rows)
