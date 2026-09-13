"""Reference data: calendar, code sets, facilities, plans, network contracts.

Code system notes, which matter for credibility:
  - ICD-10-CM titles and MS-DRG titles are public domain and used as published.
  - HCPCS Level II is public domain.
  - CPT descriptors are AMA copyright. The CODE NUMBERS here are referenced for
    realism, but every descriptor string is written for this project and is not
    the AMA descriptor. Stated in the README.
  - Revenue codes (UB-04) and POS codes are public domain.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

import config as C

# --------------------------------------------------------------------- calendar


def build_dim_date() -> pd.DataFrame:
    days = pd.date_range(C.CALENDAR_START, C.CALENDAR_END, freq="D")
    df = pd.DataFrame({"full_date": days})
    df["date_key"] = df["full_date"].dt.strftime("%Y%m%d").astype(int)
    df["calendar_year"] = df["full_date"].dt.year
    df["calendar_month"] = df["full_date"].dt.month
    df["calendar_day"] = df["full_date"].dt.day
    df["year_month"] = df["full_date"].dt.strftime("%Y%m").astype(int)
    df["year_month_name"] = df["full_date"].dt.strftime("%Y-%m")
    df["calendar_quarter"] = df["full_date"].dt.quarter
    df["day_of_week"] = df["full_date"].dt.dayofweek + 1
    df["day_name"] = df["full_date"].dt.day_name()
    df["is_weekend"] = df["day_of_week"].isin([6, 7])
    df["iso_week"] = df["full_date"].dt.isocalendar().week.astype(int)
    df["days_in_month"] = df["full_date"].dt.days_in_month
    df["is_month_end"] = df["full_date"].dt.is_month_end
    # Northlake runs a July fiscal year.
    df["fiscal_year"] = df["calendar_year"] + (df["calendar_month"] >= 7).astype(int)
    df["fiscal_quarter"] = ((df["calendar_month"] - 7) % 12) // 3 + 1

    hol = {(m, d) for m, d in C.FEDERAL_HOLIDAYS_MD}
    df["is_holiday"] = [
        (r.month, r.day) in hol or _is_floating_holiday(r)
        for r in df["full_date"]
    ]

    # Claims completeness by incurred month drives every runout lesson.
    factor = []
    for ym in df["year_month_name"]:
        if ym in C.RUNOUT_COMPLETENESS:
            factor.append(C.RUNOUT_COMPLETENESS[ym])
        elif ym > "2025-12":
            factor.append(0.0)
        else:
            factor.append(1.0)
    df["claims_completeness_factor"] = factor
    df["claims_runout_complete_flag"] = (
        df["claims_completeness_factor"] >= C.RUNOUT_THRESHOLD
    )
    df["is_in_source_window"] = (
        (df["full_date"] >= pd.Timestamp(C.SOURCE_START))
        & (df["full_date"] <= pd.Timestamp(C.SOURCE_END))
    )
    df["is_in_analysis_window"] = (
        (df["full_date"] >= pd.Timestamp(C.ANALYSIS_START))
        & (df["full_date"] <= pd.Timestamp(C.ANALYSIS_END))
    )
    df["full_date"] = df["full_date"].dt.strftime("%Y-%m-%d")
    return df


def _is_floating_holiday(ts: pd.Timestamp) -> bool:
    """MLK, Presidents, Memorial, Labor, Columbus, Thanksgiving."""
    wd, m, d = ts.dayofweek, ts.month, ts.day
    week = (d - 1) // 7 + 1
    if m == 1 and wd == 0 and week == 3:
        return True
    if m == 2 and wd == 0 and week == 3:
        return True
    if m == 5 and wd == 0 and d + 7 > 31:
        return True
    if m == 9 and wd == 0 and week == 1:
        return True
    if m == 10 and wd == 0 and week == 2:
        return True
    if m == 11 and wd == 3 and week == 4:
        return True
    return False


# ---------------------------------------------------------------- diagnosis set

# (code, title, ccsr_category, ccsr_body_system, chronic, hcc, condition_code)
# ICD-10-CM titles are public domain.
DIAGNOSES = [
    ("I10", "Essential (primary) hypertension", "CIR007", "Circulatory", 1, None, "HTN"),
    ("I11.0", "Hypertensive heart disease with heart failure", "CIR008", "Circulatory", 1, "HCC85", "HTN"),
    ("E78.5", "Hyperlipidemia, unspecified", "END010", "Endocrine", 1, None, "HLD"),
    ("E78.00", "Pure hypercholesterolemia, unspecified", "END010", "Endocrine", 1, None, "HLD"),
    ("E66.9", "Obesity, unspecified", "END009", "Endocrine", 1, None, "OBES"),
    ("E66.01", "Morbid (severe) obesity due to excess calories", "END009", "Endocrine", 1, "HCC22", "OBES"),
    ("E11.9", "Type 2 diabetes mellitus without complications", "END002", "Endocrine", 1, "HCC19", "DM2"),
    ("E11.65", "Type 2 diabetes mellitus with hyperglycemia", "END002", "Endocrine", 1, "HCC18", "DM2"),
    ("E11.22", "Type 2 diabetes with diabetic chronic kidney disease", "END002", "Endocrine", 1, "HCC18", "DM2"),
    ("F41.1", "Generalized anxiety disorder", "MBD005", "Mental/Behavioral", 1, None, "ANX"),
    ("F41.9", "Anxiety disorder, unspecified", "MBD005", "Mental/Behavioral", 1, None, "ANX"),
    ("F32.9", "Major depressive disorder, single episode, unspecified", "MBD002", "Mental/Behavioral", 1, "HCC59", "DEP"),
    ("F33.1", "Major depressive disorder, recurrent, moderate", "MBD002", "Mental/Behavioral", 1, "HCC59", "DEP"),
    ("J45.909", "Unspecified asthma, uncomplicated", "RSP008", "Respiratory", 1, None, "ASTH"),
    ("J45.40", "Moderate persistent asthma, uncomplicated", "RSP008", "Respiratory", 1, None, "ASTH"),
    ("J44.9", "Chronic obstructive pulmonary disease, unspecified", "RSP009", "Respiratory", 1, "HCC111", "COPD"),
    ("J44.1", "COPD with (acute) exacerbation", "RSP009", "Respiratory", 1, "HCC111", "COPD"),
    ("I25.10", "Atherosclerotic heart disease of native coronary artery", "CIR011", "Circulatory", 1, "HCC88", "CAD"),
    ("I25.119", "Atherosclerotic heart disease with unspecified angina", "CIR011", "Circulatory", 1, "HCC88", "CAD"),
    ("N18.3", "Chronic kidney disease, stage 3 unspecified", "GEN003", "Genitourinary", 1, "HCC138", "CKD"),
    ("N18.4", "Chronic kidney disease, stage 4 (severe)", "GEN003", "Genitourinary", 1, "HCC137", "CKD"),
    ("E03.9", "Hypothyroidism, unspecified", "END004", "Endocrine", 1, None, "HYPO"),
    ("I50.22", "Chronic systolic (congestive) heart failure", "CIR019", "Circulatory", 1, "HCC85", "CHF"),
    ("I50.32", "Chronic diastolic (congestive) heart failure", "CIR019", "Circulatory", 1, "HCC85", "CHF"),
    ("I48.0", "Paroxysmal atrial fibrillation", "CIR017", "Circulatory", 1, "HCC96", "AFIB"),
    ("I48.91", "Unspecified atrial fibrillation", "CIR017", "Circulatory", 1, "HCC96", "AFIB"),
    ("C50.911", "Malignant neoplasm of unspecified site of right female breast", "NEO013", "Neoplasms", 1, "HCC12", "CANC"),
    ("C34.90", "Malignant neoplasm of unspecified part of unspecified bronchus or lung", "NEO020", "Neoplasms", 1, "HCC9", "CANC"),
    ("C61", "Malignant neoplasm of prostate", "NEO031", "Neoplasms", 1, "HCC12", "CANC"),
    ("C18.9", "Malignant neoplasm of colon, unspecified", "NEO017", "Neoplasms", 1, "HCC11", "CANC"),
    # Musculoskeletal - the referral-leakage clinical spine of the demo.
    ("M17.11", "Unilateral primary osteoarthritis, right knee", "MUS006", "Musculoskeletal", 1, None, None),
    ("M17.12", "Unilateral primary osteoarthritis, left knee", "MUS006", "Musculoskeletal", 1, None, None),
    ("M16.11", "Unilateral primary osteoarthritis, right hip", "MUS006", "Musculoskeletal", 1, None, None),
    ("M16.12", "Unilateral primary osteoarthritis, left hip", "MUS006", "Musculoskeletal", 1, None, None),
    ("M25.561", "Pain in right knee", "MUS011", "Musculoskeletal", 0, None, None),
    ("M25.562", "Pain in left knee", "MUS011", "Musculoskeletal", 0, None, None),
    ("M54.5", "Low back pain", "MUS010", "Musculoskeletal", 0, None, None),
    ("M54.2", "Cervicalgia", "MUS010", "Musculoskeletal", 0, None, None),
    ("M75.101", "Unspecified rotator cuff tear or rupture of right shoulder", "MUS008", "Musculoskeletal", 0, None, None),
    ("M23.221", "Derangement of posterior horn of medial meniscus, right knee", "MUS008", "Musculoskeletal", 0, None, None),
    ("S83.241", "Other tear of medial meniscus, current injury, right knee", "INJ019", "Injury", 0, None, None),
    ("M79.604", "Pain in right leg", "MUS011", "Musculoskeletal", 0, None, None),
    ("M48.061", "Spinal stenosis, lumbar region without neurogenic claudication", "MUS004", "Musculoskeletal", 1, None, None),
    ("M51.26", "Other intervertebral disc displacement, lumbar region", "MUS004", "Musculoskeletal", 1, None, None),
    # Acute and preventive
    ("J06.9", "Acute upper respiratory infection, unspecified", "RSP002", "Respiratory", 0, None, None),
    ("J02.9", "Acute pharyngitis, unspecified", "RSP002", "Respiratory", 0, None, None),
    ("J20.9", "Acute bronchitis, unspecified", "RSP003", "Respiratory", 0, None, None),
    ("J18.9", "Pneumonia, unspecified organism", "RSP005", "Respiratory", 0, "HCC115", None),
    ("N39.0", "Urinary tract infection, site not specified", "GEN004", "Genitourinary", 0, None, None),
    ("R51.9", "Headache, unspecified", "NVS020", "Nervous", 0, None, None),
    ("R05.9", "Cough, unspecified", "SYM003", "Symptoms", 0, None, None),
    ("R07.9", "Chest pain, unspecified", "SYM006", "Symptoms", 0, None, None),
    ("R10.9", "Unspecified abdominal pain", "SYM008", "Symptoms", 0, None, None),
    ("Z00.00", "Encounter for general adult medical exam without abnormal findings", "FAC001", "Factors", 0, None, None),
    ("Z00.129", "Encounter for routine child health exam without abnormal findings", "FAC001", "Factors", 0, None, None),
    ("Z23", "Encounter for immunization", "FAC006", "Factors", 0, None, None),
    ("Z12.11", "Encounter for screening for malignant neoplasm of colon", "FAC004", "Factors", 0, None, None),
    ("Z12.31", "Encounter for screening mammogram for malignant neoplasm of breast", "FAC004", "Factors", 0, None, None),
    # Pregnancy - female-only, enforced by validation
    ("Z34.90", "Encounter for supervision of normal pregnancy, unspecified trimester", "PRG001", "Pregnancy", 0, None, "PREG"),
    ("O80", "Encounter for full-term uncomplicated delivery", "PRG013", "Pregnancy", 0, None, "PREG"),
    ("O09.90", "Supervision of high risk pregnancy, unspecified", "PRG002", "Pregnancy", 0, None, "PREG"),
    # Male-only, used to catch the over-match anomaly
    ("N40.0", "Benign prostatic hyperplasia without lower urinary tract symptoms", "GEN014", "Genitourinary", 1, None, None),
    ("R97.20", "Elevated prostate specific antigen (PSA)", "SYM014", "Symptoms", 0, None, None),
]

FEMALE_ONLY_DX = {"Z34.90", "O80", "O09.90", "C50.911"}
MALE_ONLY_DX = {"C61", "N40.0", "R97.20"}
PEDIATRIC_ONLY_DX = {"Z00.129"}


def build_dim_diagnosis() -> pd.DataFrame:
    rows = []
    for i, (code, title, ccsr, system, chronic, hcc, cond) in enumerate(DIAGNOSES, 1):
        rows.append({
            "diagnosis_key": i,
            "icd10_code": code,
            "icd10_description": title,
            "ccsr_category": ccsr,
            "ccsr_body_system": system,
            "chronic_condition_flag": bool(chronic),
            "hcc_code": hcc,
            "condition_code": cond,
            "sex_restriction": ("F" if code in FEMALE_ONLY_DX
                                else "M" if code in MALE_ONLY_DX else None),
            "max_age": 17 if code in PEDIATRIC_ONLY_DX else None,
            "is_valid_billable": True,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- procedure set

# (code, system, our own descriptor, service_category, betos, avg_units)
# CPT descriptors below are written for this project, not AMA text.
PROCEDURES = [
    ("99213", "CPT", "Office visit, established patient, low complexity", "EM_OFFICE", "M1B", 1),
    ("99214", "CPT", "Office visit, established patient, moderate complexity", "EM_OFFICE", "M1B", 1),
    ("99215", "CPT", "Office visit, established patient, high complexity", "EM_OFFICE", "M1B", 1),
    ("99212", "CPT", "Office visit, established patient, straightforward", "EM_OFFICE", "M1B", 1),
    ("99203", "CPT", "Office visit, new patient, low complexity", "EM_OFFICE", "M1A", 1),
    ("99204", "CPT", "Office visit, new patient, moderate complexity", "EM_OFFICE", "M1A", 1),
    ("99205", "CPT", "Office visit, new patient, high complexity", "EM_OFFICE", "M1A", 1),
    ("99396", "CPT", "Preventive visit, established patient, age 40-64", "EM_OFFICE", "M1B", 1),
    ("99385", "CPT", "Preventive visit, new patient, adolescent", "EM_OFFICE", "M1A", 1),
    ("99283", "CPT", "Emergency department visit, moderate severity", "EM_ED", "M2C", 1),
    ("99284", "CPT", "Emergency department visit, high severity", "EM_ED", "M2C", 1),
    ("99285", "CPT", "Emergency department visit, highest severity", "EM_ED", "M2C", 1),
    ("99282", "CPT", "Emergency department visit, low severity", "EM_ED", "M2C", 1),
    ("36415", "CPT", "Routine venipuncture for specimen collection", "LAB", "T1H", 1),
    ("80053", "CPT", "Comprehensive metabolic panel", "LAB", "T1B", 1),
    ("80061", "CPT", "Lipid panel", "LAB", "T1B", 1),
    ("83036", "CPT", "Hemoglobin A1c measurement", "LAB", "T1B", 1),
    ("85025", "CPT", "Complete blood count with differential", "LAB", "T1B", 1),
    ("84443", "CPT", "Thyroid stimulating hormone assay", "LAB", "T1B", 1),
    ("81001", "CPT", "Urinalysis with microscopy, automated", "LAB", "T1B", 1),
    ("82043", "CPT", "Urine albumin, quantitative", "LAB", "T1B", 1),
    ("80048", "CPT", "Basic metabolic panel", "LAB", "T1B", 1),
    ("71046", "CPT", "Chest radiograph, two views", "IMAGING", "I1A", 1),
    ("73721", "CPT", "MRI of lower extremity joint without contrast", "IMAGING", "I2B", 1),
    ("73562", "CPT", "Knee radiograph, three views", "IMAGING", "I1A", 1),
    ("72148", "CPT", "MRI of lumbar spine without contrast", "IMAGING", "I2B", 1),
    ("73030", "CPT", "Shoulder radiograph, complete", "IMAGING", "I1A", 1),
    ("74177", "CPT", "CT of abdomen and pelvis with contrast", "IMAGING", "I2A", 1),
    ("77067", "CPT", "Screening mammography, bilateral", "IMAGING", "I3E", 1),
    ("93000", "CPT", "Electrocardiogram, routine with interpretation", "IMAGING", "T2A", 1),
    ("93306", "CPT", "Transthoracic echocardiography, complete", "IMAGING", "T2A", 1),
    ("29881", "CPT", "Knee arthroscopy with medial meniscectomy", "OP_SURGERY", "P1D", 1),
    ("29827", "CPT", "Shoulder arthroscopy with rotator cuff repair", "OP_SURGERY", "P1D", 1),
    ("29880", "CPT", "Knee arthroscopy with medial and lateral meniscectomy", "OP_SURGERY", "P1D", 1),
    ("64483", "CPT", "Transforaminal epidural injection, lumbar, single level", "OP_SURGERY", "P8A", 1),
    ("20610", "CPT", "Major joint aspiration or injection", "OP_SURGERY", "P8A", 1),
    ("45378", "CPT", "Diagnostic colonoscopy", "OP_SURGERY", "P2D", 1),
    ("45380", "CPT", "Colonoscopy with biopsy", "OP_SURGERY", "P2D", 1),
    ("66984", "CPT", "Cataract extraction with intraocular lens insertion", "OP_SURGERY", "P4A", 1),
    ("27447", "CPT", "Total knee arthroplasty", "IP_SURGERY", "P1A", 1),
    ("27130", "CPT", "Total hip arthroplasty", "IP_SURGERY", "P1A", 1),
    ("22633", "CPT", "Lumbar spinal fusion, single interspace", "IP_SURGERY", "P1B", 1),
    ("33533", "CPT", "Coronary artery bypass, single arterial graft", "IP_SURGERY", "P1C", 1),
    ("97110", "CPT", "Therapeutic exercise, each 15 minutes", "PT", "P5D", 3),
    ("97140", "CPT", "Manual therapy techniques, each 15 minutes", "PT", "P5D", 2),
    ("97530", "CPT", "Therapeutic activities, each 15 minutes", "PT", "P5D", 2),
    ("00400", "CPT", "Anesthesia for procedures on the extremities", "ANESTHESIA", "P0", 6),
    ("01402", "CPT", "Anesthesia for total knee arthroplasty", "ANESTHESIA", "P0", 8),
    ("01630", "CPT", "Anesthesia for shoulder procedures", "ANESTHESIA", "P0", 5),
    ("J1745", "HCPCS", "Infliximab injection, 10 mg", "SPECIALTY_DRUG", "O1E", 40),
    ("J9310", "HCPCS", "Rituximab injection, 100 mg", "SPECIALTY_DRUG", "O1E", 6),
    ("J0178", "HCPCS", "Aflibercept injection, 1 mg", "SPECIALTY_DRUG", "O1E", 2),
    ("J2350", "HCPCS", "Ocrelizumab injection, 1 mg", "SPECIALTY_DRUG", "O1E", 300),
    ("A0429", "HCPCS", "Ambulance service, basic life support, emergency", "TRANSPORT", "O1A", 1),
    ("G0439", "HCPCS", "Annual wellness visit, subsequent", "EM_OFFICE", "M1B", 1),
    ("0SRC0J9", "ICD10PCS", "Replacement of right knee joint with synthetic substitute", "IP_SURGERY", None, 1),
    ("0SRB0J9", "ICD10PCS", "Replacement of left knee joint with synthetic substitute", "IP_SURGERY", None, 1),
    ("0SR904A", "ICD10PCS", "Replacement of right hip joint with ceramic substitute", "IP_SURGERY", None, 1),
    ("02100Z9", "ICD10PCS", "Bypass coronary artery, one artery, from aorta", "IP_SURGERY", None, 1),
]

# Procedures that must never appear at POS 11 (office).
FACILITY_ONLY_PROCEDURES = {
    "27447", "27130", "22633", "33533", "66984", "45378", "45380",
    "29881", "29827", "29880", "0SRC0J9", "0SRB0J9", "0SR904A", "02100Z9",
}
MSK_SURGICAL_PROCEDURES = {
    "29881", "29827", "29880", "27447", "27130", "22633", "64483",
}
BILATERAL_CAPABLE = {"29881", "29880", "20610", "73562", "73721", "64483"}


def build_dim_procedure() -> pd.DataFrame:
    rows = []
    for i, (code, system, desc, cat, betos, units) in enumerate(PROCEDURES, 1):
        rows.append({
            "procedure_key": i,
            "code_system": system,
            "procedure_code": code,
            "procedure_description": desc,
            "service_category": cat,
            "betos_category": betos,
            "typical_units": units,
            "is_facility_only": code in FACILITY_ONLY_PROCEDURES,
            "is_msk_surgical": code in MSK_SURGICAL_PROCEDURES,
            "bilateral_capable": code in BILATERAL_CAPABLE,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- other code sets

POS_CODES = [
    ("02", "Telehealth, patient not in their home", False),
    ("10", "Telehealth, patient in their home", False),
    ("11", "Office", False),
    ("19", "Off-campus outpatient hospital", True),
    ("20", "Urgent care facility", False),
    ("21", "Inpatient hospital", True),
    ("22", "On-campus outpatient hospital", True),
    ("23", "Emergency room, hospital", True),
    ("24", "Ambulatory surgical center", True),
    ("31", "Skilled nursing facility", True),
    ("49", "Independent clinic", False),
    ("50", "Federally qualified health center", False),
    ("81", "Independent laboratory", False),
]

REVENUE_CODES = [
    ("0110", "Room and board, private"),
    ("0120", "Room and board, semi-private two bed"),
    ("0200", "Intensive care unit, general"),
    ("0250", "Pharmacy, general"),
    ("0260", "IV therapy, general"),
    ("0300", "Laboratory, general"),
    ("0320", "Radiology, diagnostic"),
    ("0360", "Operating room services, general"),
    ("0370", "Anesthesia, general"),
    ("0410", "Respiratory services, general"),
    ("0420", "Physical therapy, general"),
    ("0450", "Emergency room, general"),
    ("0460", "Pulmonary function, general"),
    ("0610", "MRI, general"),
    ("0636", "Drugs requiring detailed coding"),
    ("0710", "Recovery room, general"),
]

MS_DRGS = [
    ("470", "Major hip and knee joint replacement without MCC", 8, 1.9089, True),
    ("469", "Major hip and knee joint replacement with MCC", 15, 3.0329, True),
    ("460", "Spinal fusion except cervical without MCC", 8, 2.9133, True),
    ("291", "Heart failure and shock with MCC", 5, 1.4384, False),
    ("292", "Heart failure and shock with CC", 5, 0.9728, False),
    ("293", "Heart failure and shock without CC/MCC", 5, 0.6737, False),
    ("190", "COPD with MCC", 4, 1.1547, False),
    ("191", "COPD with CC", 4, 0.9276, False),
    ("192", "COPD without CC/MCC", 4, 0.7259, False),
    ("193", "Simple pneumonia and pleurisy with MCC", 4, 1.3853, False),
    ("194", "Simple pneumonia and pleurisy with CC", 4, 0.9424, False),
    ("871", "Septicemia without ventilator support 96+ hours with MCC", 18, 1.8577, False),
    ("872", "Septicemia without ventilator support 96+ hours without MCC", 18, 1.0532, False),
    ("247", "Percutaneous cardiovascular procedure with drug-eluting stent", 5, 1.9482, True),
    ("233", "Coronary bypass with cardiac catheterization with MCC", 5, 6.8244, True),
    ("807", "Vaginal delivery without sterilization or D&C without CC/MCC", 14, 0.5573, False),
    ("795", "Normal newborn", 15, 0.1653, False),
    ("682", "Renal failure with MCC", 11, 1.5263, False),
    ("683", "Renal failure with CC", 11, 0.9585, False),
    ("552", "Medical back problems without MCC", 8, 0.8257, False),
]

CLAIM_STATUSES = [
    ("PAID", "Paid in full", True, False, False, False),
    ("PARTIAL", "Paid, patient responsibility applied", True, False, False, False),
    ("DENY_AUTH", "Denied, no prior authorization (CO-197)", False, True, False, False),
    ("DENY_BUNDLE", "Denied, procedure bundled (CO-97)", False, True, False, False),
    ("DENY_INFO", "Denied, missing or invalid information (CO-16)", False, True, False, False),
    ("DENY_FILING", "Denied, timely filing limit exceeded (CO-29)", False, True, False, False),
    ("DENY_NONCOV", "Denied, service not covered (CO-96)", False, True, False, False),
    ("PR_DEDUCT", "Patient responsibility, deductible (PR-1)", True, False, False, False),
    ("REVERSED", "Reversal of prior adjudication", False, False, True, False),
    ("ADJUSTED", "Adjusted replacement of prior adjudication", True, False, False, True),
]

# CO-45 is a contractual write-off, NOT a denial. Modeled as an amount field on
# every line rather than as a status, because treating it as a denial is the
# single fastest way to lose a revenue-cycle person in the room.

SERVICE_LINES = [
    ("SL01", "Orthopedics", "MSK"),
    ("SL02", "Spine", "MSK"),
    ("SL03", "Sports medicine", "MSK"),
    ("SL04", "Physical therapy", "MSK"),
    ("SL05", "Cardiology", "CARDIO"),
    ("SL06", "Cardiac surgery", "CARDIO"),
    ("SL07", "Primary care", "PRIMARY"),
    ("SL08", "Pediatrics", "PRIMARY"),
    ("SL09", "Obstetrics", "WOMENS"),
    ("SL10", "Gynecology", "WOMENS"),
    ("SL11", "General surgery", "SURGICAL"),
    ("SL12", "Gastroenterology", "SURGICAL"),
    ("SL13", "Ophthalmology", "SURGICAL"),
    ("SL14", "Oncology", "ONC"),
    ("SL15", "Hematology", "ONC"),
    ("SL16", "Pulmonology", "MEDICAL"),
    ("SL17", "Nephrology", "MEDICAL"),
    ("SL18", "Endocrinology", "MEDICAL"),
    ("SL19", "Neurology", "MEDICAL"),
    ("SL20", "Rheumatology", "MEDICAL"),
    ("SL21", "Dermatology", "MEDICAL"),
    ("SL22", "Urology", "SURGICAL"),
    ("SL23", "Emergency medicine", "ACUTE"),
    ("SL24", "Urgent care", "ACUTE"),
    ("SL25", "Hospital medicine", "ACUTE"),
    ("SL26", "Radiology", "DIAGNOSTIC"),
    ("SL27", "Laboratory", "DIAGNOSTIC"),
    ("SL28", "Anesthesiology", "PERIOP"),
]


def build_dim_service_place() -> pd.DataFrame:
    return pd.DataFrame([
        {"service_place_key": i, "pos_code": c, "pos_description": d,
         "is_facility_setting": f}
        for i, (c, d, f) in enumerate(POS_CODES, 1)
    ])


def build_dim_drg() -> pd.DataFrame:
    return pd.DataFrame([
        {"drg_key": i, "drg_code": c, "drg_description": d, "mdc": mdc,
         "relative_weight": w, "is_surgical": s}
        for i, (c, d, mdc, w, s) in enumerate(MS_DRGS, 1)
    ])


def build_dim_claim_status() -> pd.DataFrame:
    return pd.DataFrame([
        {"claim_status_key": i, "status_code": c, "status_description": d,
         "is_paid": p, "is_denied": dn, "is_reversal": rv, "is_adjustment": aj}
        for i, (c, d, p, dn, rv, aj) in enumerate(CLAIM_STATUSES, 1)
    ])


def build_dim_service_line() -> pd.DataFrame:
    return pd.DataFrame([
        {"service_line_key": i, "service_line_code": c, "service_line_name": n,
         "service_line_group": g}
        for i, (c, n, g) in enumerate(SERVICE_LINES, 1)
    ])


def build_revenue_codes() -> pd.DataFrame:
    return pd.DataFrame([
        {"revenue_code": c, "revenue_code_description": d}
        for c, d in REVENUE_CODES
    ])
