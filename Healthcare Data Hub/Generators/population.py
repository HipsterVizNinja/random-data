"""Members, households, the latent risk variable, and chronic conditions.

The single most important decision in the whole generator lives here: ONE
latent risk variable drives condition onset, utilization counts, and cost
intensity. Realistic correlation then emerges on its own instead of being
retrofitted by correlating a dozen marginals after the fact.

Households matter for a second reason: surnames, addresses, and group IDs
cluster into families, which is what makes the identity over-match anomaly
plausible rather than arbitrary.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config as C
import ids
import names as N
import org

REF_YEAR = 2024  # age reference point, mid-window


def _draw_ages(rng: np.random.Generator, n: int) -> np.ndarray:
    bands = [b for b, _ in C.AGE_BANDS]
    probs = np.array([p for _, p in C.AGE_BANDS])
    probs = probs / probs.sum()
    which = rng.choice(len(bands), size=n, p=probs)
    lo = np.array([bands[i][0] for i in which])
    hi = np.array([bands[i][1] for i in which])
    return lo + (rng.random(n) * (hi - lo + 1)).astype(int)


def _calibrate_intercept(
    logit_partial: np.ndarray,
    target: float,
    suppress: np.ndarray | None = None,
    lo: float = -20.0,
    hi: float = 20.0,
) -> float:
    """Bisect for the intercept that makes realized prevalence hit target.

    `suppress` is a multiplicative mask applied to the probability before the
    mean is taken, so the pediatric suppression is inside the calibration loop
    rather than applied afterwards. Calibrating first and suppressing second
    biases every adult condition low, which is the bug this signature fixes.
    """
    for _ in range(90):
        mid = (lo + hi) / 2.0
        p = 1.0 / (1.0 + np.exp(-(logit_partial + mid)))
        if suppress is not None:
            p = p * suppress
        if p.mean() > target:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def build_population(run: C.RunConfig) -> dict[str, pd.DataFrame]:
    rng = run.rng("population")
    n_members = run.scale.n_members

    # ---- households first, so names and addresses cluster into families
    sizes = np.array(list(C.FAMILY_SIZE_DIST.keys()))
    size_p = np.array(list(C.FAMILY_SIZE_DIST.values()))
    size_p = size_p / size_p.sum()
    drawn: list[int] = []
    total = 0
    while total < n_members:
        s = int(rng.choice(sizes, p=size_p))
        drawn.append(s)
        total += s
    # Trim the last household so the member count lands exactly.
    drawn[-1] -= total - n_members
    if drawn[-1] <= 0:
        n_members -= drawn.pop()
    household_sizes = np.array(drawn)
    n_households = len(household_sizes)

    hh_surname = rng.choice(N.SURNAMES, size=n_households)
    hh_region = rng.choice(org.REGIONS, size=n_households)
    hh_street = rng.integers(100, 9999, size=n_households)
    street_names = [
        "Oak", "Maple", "Cedar", "Elm", "Birch", "Walnut", "Chestnut", "Willow",
        "Pine", "Aspen", "Hickory", "Sycamore", "Juniper", "Poplar", "Magnolia",
        "Laurel", "Dogwood", "Spruce", "Alder", "Cypress",
    ]
    street_types = ["St", "Ave", "Rd", "Ln", "Dr", "Ct", "Way", "Blvd", "Ter", "Pl"]
    hh_street_name = rng.choice(street_names, size=n_households)
    hh_street_type = rng.choice(street_types, size=n_households)
    hh_zip_pool = {
        "North": ["64116", "64117", "64118", "64119", "64155"],
        "South": ["64130", "64131", "64132", "64137", "64138"],
        "East": ["64133", "64134", "64135", "64136", "64139"],
        "West": ["66212", "66213", "66214", "66215", "66216"],
        "Central": ["64108", "64109", "64110", "64111", "64112"],
    }
    hh_zip = np.array([
        rng.choice(hh_zip_pool[r]) for r in hh_region
    ])

    household_id = np.repeat(np.arange(1, n_households + 1), household_sizes)
    seq_in_hh = np.concatenate([np.arange(1, s + 1) for s in household_sizes])

    # ---- demographics. Subscriber (seq 1) skews adult; dependents skew young.
    ages = _draw_ages(rng, n_members)
    is_subscriber = seq_in_hh == 1
    # A subscriber under 18 is not plausible; pull them into adulthood.
    ages = np.where(is_subscriber & (ages < 18), rng.integers(23, 64, n_members), ages)
    # Dependents in multi-person households skew child or spouse.
    dep_child = (~is_subscriber) & (seq_in_hh >= 3)
    ages = np.where(dep_child, rng.integers(0, 22, n_members), ages)

    birth_year = REF_YEAR - ages
    sex = np.where(rng.random(n_members) < 0.51, "F", "M")
    # Spouses (seq 2) tend to be the opposite sex of the subscriber.
    given = np.empty(n_members, dtype=object)
    for i in range(n_members):
        pool = N.given_name_pool(sex[i], int(birth_year[i]))
        given[i] = pool[int(rng.integers(0, len(pool)))]
    middle = rng.choice(N.MIDDLE_INITIALS, size=n_members)

    surname = hh_surname[household_id - 1]
    region = hh_region[household_id - 1]
    postal = hh_zip[household_id - 1]
    address = [
        f"{hh_street[h-1]} {hh_street_name[h-1]} {hh_street_type[h-1]}"
        for h in household_id
    ]

    birth_month = rng.integers(1, 13, n_members)
    birth_day = rng.integers(1, 29, n_members)
    birth_date = pd.to_datetime(
        dict(year=birth_year, month=birth_month, day=birth_day)
    ).dt.strftime("%Y-%m-%d")

    # ---- the latent risk variable
    r = rng.lognormal(mean=0.0, sigma=C.LATENT_SIGMA, size=n_members)
    r_adj = r * np.exp(C.LATENT_AGE_COEF * (ages - 40))
    r_adj = r_adj / r_adj.mean()
    # Cap the extreme tail. Uncapped, a handful of members draw risk multiples
    # of 25x and single-handedly distort the cost concentration curve. Genuine
    # catastrophic cases are introduced deliberately and separately.
    r_adj = np.clip(r_adj, 0.0, C.LATENT_RISK_CAP)

    # ---- line of business. Age 65+ goes Medicare Advantage.
    lob = np.where(ages >= 65, "MEDICARE_ADVANTAGE", "COMMERCIAL")

    # ---- attributed clinic group, weighted by panel size
    groups = list(org.PANEL_WEIGHTS.keys())
    gw = np.array([org.PANEL_WEIGHTS[g] for g in groups])
    gw = gw / gw.sum()
    attributed_site = rng.choice(groups, size=n_members, p=gw)
    # Pediatrics only gets children; push adults out of PEDS-SBR.
    bad_peds = (attributed_site == "PEDS-SBR") & (ages >= 19)
    if bad_peds.any():
        alt = [g for g in groups if g != "PEDS-SBR"]
        aw = np.array([org.PANEL_WEIGHTS[g] for g in alt]); aw = aw / aw.sum()
        attributed_site[bad_peds] = rng.choice(alt, size=int(bad_peds.sum()), p=aw)

    members = pd.DataFrame({
        "member_seq": np.arange(1, n_members + 1),
        "household_id": household_id,
        "seq_in_household": seq_in_hh,
        "is_subscriber": is_subscriber,
        "first_name": given,
        "middle_initial": middle,
        "last_name": surname,
        "birth_date": birth_date,
        "age_2024": ages,
        "sex": sex,
        "street_address": address,
        "region": region,
        "postal_code": postal,
        "line_of_business": lob,
        "latent_risk": np.round(r_adj, 6),
        "attributed_site_code": attributed_site,
    })

    # ---- identifiers across three key spaces
    members["member_id"] = ids.mint_member_ids(n_members)
    members["mrn"] = ids.mint_mrns(rng, n_members)
    sub_ids = ids.mint_subscriber_ids(n_households)
    members["subscriber_id"] = [sub_ids[h - 1] for h in household_id]
    members["person_code"] = [ids.person_code(s) for s in seq_in_hh]
    # The attribution feed identifies people as subscriber_id + person_code,
    # which LOOKS joinable to member_id and is not.
    members["attribution_person_id"] = (
        members["subscriber_id"] + "-" + members["person_code"]
    )
    # Internal truth: one master person per real human. The crosswalk module
    # will deliberately fail to reproduce this perfectly.
    members["true_master_person_id"] = [f"MP{i:08d}" for i in range(1, n_members + 1)]

    # ---- chronic conditions via calibrated logistic on the shared risk term
    age_z = (ages - ages.mean()) / ages.std()
    is_female = (sex == "F").astype(float)
    log_r = np.log(r_adj)
    ADULT_ONLY = ("HTN", "HLD", "DM2", "CAD", "CHF", "AFIB", "COPD", "CKD", "CANC")
    cond_flags: dict[str, np.ndarray] = {}
    cond_target: dict[str, float] = {}
    for code, label, target, b_age, b_sex, b_risk in C.CONDITIONS:
        partial = b_age * age_z + b_sex * is_female + b_risk * log_r
        # Children do not get adult cardiometabolic disease.
        suppress = (
            np.where(ages < 18, 0.02, 1.0) if code in ADULT_ONLY else None
        )
        b0 = _calibrate_intercept(partial, target, suppress)
        p = 1.0 / (1.0 + np.exp(-(partial + b0)))
        if suppress is not None:
            p = p * suppress
        cond_flags[code] = rng.random(n_members) < p
        cond_target[code] = target

    # Explicit odds-ratio boosts for pairs the latent risk term under-produces
    # on its own. Each boost adds comorbid cases, then thins non-comorbid ones
    # so the marginal prevalence stays on its benchmark target.
    for a, b, orr in C.COMORBID_BOOST:
        base = cond_flags[b].copy()
        has_a = cond_flags[a]
        want_comorbid_rate = float(np.clip(cond_target[b] * orr, 0, 0.95))
        promote = has_a & ~base & (rng.random(n_members) < want_comorbid_rate)
        base = base | promote
        # Restore the marginal by dropping a matching number of positives that
        # are NOT part of the boosted pair.
        surplus = int(base.sum() - round(cond_target[b] * n_members))
        if surplus > 0:
            droppable = np.flatnonzero(base & ~has_a)
            if droppable.size:
                drop = rng.choice(
                    droppable, size=min(surplus, droppable.size), replace=False
                )
                base[drop] = False
        cond_flags[b] = base

    for code, label, *_ in C.CONDITIONS:
        members[f"cond_{code.lower()}"] = cond_flags[code]

    members["n_chronic"] = sum(
        members[f"cond_{c.lower()}"].astype(int) for c, *_ in C.CONDITIONS
    )

    # ---- pregnancy: female, 15-44 only. Enforced, not probabilistic.
    preg_eligible = (
        (members["sex"] == "F")
        & members["age_2024"].between(*C.PREGNANCY_AGE_RANGE)
    )
    n_years = 3
    members["is_pregnant_in_window"] = preg_eligible & (
        rng.random(n_members) < C.PREGNANCY_RATE * n_years
    )

    # ---- risk score (RAF-like), so raw and risk-adjusted PMPM diverge
    hcc_weight = (
        0.12 * members["cond_dm2"].astype(int)
        + 0.32 * members["cond_chf"].astype(int)
        + 0.24 * members["cond_copd"].astype(int)
        + 0.18 * members["cond_cad"].astype(int)
        + 0.28 * members["cond_ckd"].astype(int)
        + 0.42 * members["cond_canc"].astype(int)
        + 0.14 * members["cond_afib"].astype(int)
    )
    age_component = np.where(
        members["age_2024"] >= 65, 0.45 + 0.012 * (members["age_2024"] - 65), 0.25
    )
    members["risk_score"] = np.round(
        (age_component + hcc_weight) * (0.85 + 0.30 * members["latent_risk"].clip(0, 4)),
        4,
    )

    households = pd.DataFrame({
        "household_id": np.arange(1, n_households + 1),
        "household_surname": hh_surname,
        "region": hh_region,
        "postal_code": hh_zip,
        "household_size": household_sizes,
        "subscriber_id": sub_ids,
    })

    return {"members": members, "households": households}
