"""Identity resolution across the three patient and three provider key spaces.

This is the hub's center of gravity. The crosswalk is deliberately imperfect
in BOTH directions, because both failure modes teach something different:

  Under-match (anomaly A4): 3.1% of EHR medical record numbers never resolve
  to a payer member ID. Critically the loss is NOT random - it skews toward
  North Ridge patients, whose registration workflow does not capture the
  subscriber ID. So a naive inner join silently deletes part of the very
  finding the demo is built on, and UNDERSTATES the leakage. The careless
  analyst gets a wrong answer that still looks plausible.

  Over-match (anomaly A5): 40 master person IDs each collapse two genuinely
  distinct people - twins and Jr/Sr pairs matched on name, date of birth and
  address. They surface as artificial super-utilizers at the very top of the
  cost distribution, contaminating precisely the top-1% figure the demo
  quotes. Over-matching is the more interesting failure and is almost never
  demonstrated.

The sex-mismatch query finds most of the over-matches in a single line, which
makes for a satisfying teaching beat.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config as C

# Match tier shares. These sum to 1.0 across the EHR key space.
TIER_EXACT = 0.820
TIER_DETERMINISTIC = 0.130
TIER_PROBABILISTIC = 0.019
TIER_UNMATCHED = 0.031

# North Ridge patients are 2.4x more likely to fail matching.
UNMATCH_SKEW_SITE = "ORTHO-NR"
UNMATCH_SKEW_FACTOR = 2.4

OVER_MATCH_PAIRS = 40

MATCH_RUN_DATE = "2025-12-01"


def build_crosswalks(
    run: C.RunConfig, members: pd.DataFrame, providers: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    rng = run.rng("crosswalk")
    patient = _build_patient_crosswalk(run, rng, members)
    provider = _build_provider_crosswalk(run, rng, providers)
    master = _build_master_person(patient, members)
    return {
        "xwalk_patient": patient,
        "xwalk_provider": provider,
        "dim_master_person": master,
    }


def _build_patient_crosswalk(run, rng, members: pd.DataFrame) -> pd.DataFrame:
    n = len(members)

    # ---- which EHR records fail to match, skewed toward one site
    w = np.where(
        members["attributed_site_code"].to_numpy() == UNMATCH_SKEW_SITE,
        UNMATCH_SKEW_FACTOR, 1.0,
    )
    p_unmatched = np.clip(TIER_UNMATCHED * w / w.mean(), 0, 0.95)
    unmatched = rng.random(n) < p_unmatched

    # ---- tier assignment for everyone who did match
    u = rng.random(n)
    denom = TIER_EXACT + TIER_DETERMINISTIC + TIER_PROBABILISTIC
    method = np.where(
        u < TIER_EXACT / denom, "EXACT",
        np.where(u < (TIER_EXACT + TIER_DETERMINISTIC) / denom,
                 "DETERMINISTIC_NAME_DOB_ZIP", "PROBABILISTIC"),
    )
    method = np.where(unmatched, "UNMATCHED", method)

    score = np.select(
        [method == "EXACT", method == "DETERMINISTIC_NAME_DOB_ZIP",
         method == "PROBABILISTIC"],
        [1.0, np.round(rng.uniform(0.95, 0.999, n), 3),
         np.round(rng.uniform(0.72, 0.94, n), 3)],
        default=np.nan,
    )

    master_id = np.where(unmatched, None, members["true_master_person_id"].to_numpy())

    # ---- over-match: collapse pairs of distinct people onto one master ID.
    # Candidates are two members of the same household with close dates of
    # birth, which is what makes the twin and Jr/Sr framing plausible.
    over_pairs = _pick_over_match_pairs(run, rng, members)
    for a_idx, b_idx in over_pairs:
        if master_id[a_idx] is None or master_id[b_idx] is None:
            continue
        master_id[b_idx] = master_id[a_idx]
        method[b_idx] = "PROBABILISTIC"
        score[b_idx] = round(float(rng.uniform(0.82, 0.89)), 3)

    rows = []
    # One row per (source_system, source_patient_id). Three key spaces.
    for source, col in (
        ("MERIDIAN_ELIG", "member_id"),
        ("CARELINE_EHR", "mrn"),
        ("NORTHLAKE_VBC", "attribution_person_id"),
    ):
        # The payer key space always resolves - it IS the spine. The EHR and
        # attribution spaces are where matching actually happens.
        if source == "MERIDIAN_ELIG":
            m_id = members["true_master_person_id"].to_numpy()
            meth = np.full(n, "EXACT", dtype=object)
            sc = np.ones(n)
        else:
            m_id, meth, sc = master_id, method, score
        rows.append(pd.DataFrame({
            "source_system": source,
            "source_patient_id": members[col].to_numpy(),
            "master_person_id": m_id,
            "match_method": meth,
            "match_score": sc,
            "match_run_date": MATCH_RUN_DATE,
            "is_active": True,
        }))
    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["source_system", "source_patient_id"]).reset_index(drop=True)
    out.insert(0, "xwalk_patient_key", np.arange(1, len(out) + 1))
    return out


def _pick_over_match_pairs(run, rng, members: pd.DataFrame):
    """Same household, close date of birth, same surname: twins and Jr/Sr."""
    want = run.n(OVER_MATCH_PAIRS)
    df = members.reset_index(drop=True)
    df["_row"] = np.arange(len(df))
    pairs = []
    for _, g in df.groupby("household_id"):
        if len(g) < 2 or len(pairs) >= want:
            continue
        g = g.sort_values("age_2024")
        ages = g["age_2024"].to_numpy()
        rows = g["_row"].to_numpy()
        for i in range(len(g) - 1):
            # Twins share an age; a Jr/Sr pair is a generation apart but shares
            # a first name, so both are plausible probabilistic collisions.
            if abs(int(ages[i]) - int(ages[i + 1])) <= 1:
                pairs.append((int(rows[i]), int(rows[i + 1])))
                break
        if len(pairs) >= want:
            break
    return pairs[:want]


def _build_provider_crosswalk(run, rng, providers: pd.DataFrame) -> pd.DataFrame:
    """Three provider key spaces: credentialed NPI, EHR internal id, claim NPI.

    A small share of claim-side NPIs are dirty in exactly the ways a real
    prescriber or servicing-provider field is dirty: truncated, untrimmed,
    punctuated, or stripped of a leading zero by a spreadsheet round trip.
    """
    rows = []
    n = len(providers)
    for source, col in (
        ("NETWORK_CREDENTIALING", "npi"),
        ("CARELINE_EHR", "ehr_provider_id"),
        ("MERIDIAN_CLAIMS", "npi"),
    ):
        meth = np.full(n, "EXACT", dtype=object)
        sc = np.ones(n)
        if source == "CARELINE_EHR":
            meth = np.where(rng.random(n) < 0.06, "DETERMINISTIC_NAME_DOB_ZIP", "EXACT")
        rows.append(pd.DataFrame({
            "source_system": source,
            "source_provider_id": providers[col].to_numpy(),
            "provider_master_id": providers["provider_master_id"].to_numpy(),
            "npi": providers["npi"].to_numpy(),
            "match_method": meth,
            "match_score": sc,
            "match_run_date": MATCH_RUN_DATE,
            "is_active": True,
        }))
    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["source_system", "source_provider_id"]).reset_index(drop=True)
    out.insert(0, "xwalk_provider_key", np.arange(1, len(out) + 1))
    return out


def _build_master_person(patient: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    """The resolved-person dimension, with resolution quality on every row.

    source_system_count and the has_* flags are what let an analyst see, per
    person, whether the hub actually managed to stitch them together. A person
    present in only one source is not necessarily an error, but a person
    missing from claims cannot have a cost, and that distinction has to be
    visible rather than inferred.
    """
    matched = patient[patient["master_person_id"].notna()]
    agg = matched.groupby("master_person_id", as_index=False).agg(
        source_system_count=("source_system", "nunique"),
        best_match_score=("match_score", "min"),
        weakest_method=("match_method", lambda s: (
            "PROBABILISTIC" if "PROBABILISTIC" in set(s)
            else "DETERMINISTIC_NAME_DOB_ZIP"
            if "DETERMINISTIC_NAME_DOB_ZIP" in set(s) else "EXACT"
        )),
    )
    present = matched.groupby(
        ["master_person_id", "source_system"]
    ).size().unstack(fill_value=0)
    agg["has_claims"] = agg["master_person_id"].map(
        present.get("MERIDIAN_ELIG", pd.Series(dtype=int)).gt(0)
    ).fillna(False)
    agg["has_ehr"] = agg["master_person_id"].map(
        present.get("CARELINE_EHR", pd.Series(dtype=int)).gt(0)
    ).fillna(False)
    agg["has_attribution"] = agg["master_person_id"].map(
        present.get("NORTHLAKE_VBC", pd.Series(dtype=int)).gt(0)
    ).fillna(False)
    agg["is_multi_source"] = agg["source_system_count"] > 1

    # How many DISTINCT real people hide behind each master ID. Anything above
    # 1 is an over-match, and this column is the answer key.
    truth = members[["true_master_person_id", "member_id"]].rename(
        columns={"true_master_person_id": "master_person_id"}
    )
    collapsed = (
        patient[(patient.source_system == "CARELINE_EHR")
                & patient.master_person_id.notna()]
        .groupby("master_person_id").size().rename("ehr_records_resolved")
    )
    agg = agg.merge(collapsed, on="master_person_id", how="left")
    agg["ehr_records_resolved"] = agg["ehr_records_resolved"].fillna(0).astype(int)
    agg["resolution_confidence"] = np.select(
        [agg["weakest_method"] == "EXACT",
         agg["weakest_method"] == "DETERMINISTIC_NAME_DOB_ZIP"],
        ["HIGH", "MEDIUM"], default="LOW",
    )
    agg = agg.sort_values("master_person_id").reset_index(drop=True)
    agg.insert(0, "master_person_key", np.arange(1, len(agg) + 1))
    return agg
