"""The anomaly stage: every remaining planted defect, applied as a logged mutation.

Run as a separate FINAL stage rather than scattered through the generators,
which buys three things:

  1. The answer key is GENERATED. Every magnitude quoted in
     data-trust-validation.md and anomaly-answer-key.md is measured from the
     data that shipped, so the documentation cannot drift from the dataset.
  2. `build.py --no-anomalies` produces a clean twin dataset. Running the same
     analysis against both and showing the delta is the single best teaching
     device in the project.
  3. Each defect is independently tunable without touching generator logic.

Anomalies A1 through A8, A10 and A11a/A11c are structural - they arise from
how the source systems behave and are built into the generators themselves.
What lands here is everything that is genuinely a post-hoc mutation of
otherwise-clean output.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config as C
import org

# A9a: the extract that got re-driven, duplicating a day of claim lines.
DUPLICATE_LINES = 2_840
DUPLICATE_BATCH = "BATCH-REDRIVE-20240714"

# A12: servicing providers with no credentialing record, concentrated at the
# urgent care that staffs through an agency.
ORPHAN_PROVIDER_LINES = 1_312
ORPHAN_CONCENTRATION = 0.68

# Sex is encoded differently in every source system (A11b).
SEX_ENCODING = {
    "MERIDIAN_ELIG": {"M": "M", "F": "F", None: "U"},
    "CARELINE_EHR": {"M": "1", "F": "2", None: "9"},          # HL7 table 0001
    "NORTHLAKE_VBC": {"M": "Male", "F": "Female", None: "Unknown"},
}


def apply_anomalies(
    run: C.RunConfig,
    tables: dict[str, pd.DataFrame],
    runout_stats: dict | None = None,
) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """Mutate the table set in place-ish and return the manifest."""
    manifest: list[dict] = []
    if not run.apply_anomalies:
        manifest.append({
            "anomaly_id": "NONE",
            "name": "Clean twin dataset",
            "description": (
                "Built with --no-anomalies. Every planted defect is absent. "
                "Use this alongside the standard build to show what each "
                "anomaly actually costs an analysis."
            ),
            "applied": False,
        })
        return tables, manifest

    rng = run.rng("anomalies")
    tables, rec = _a9_duplicate_lines(run, rng, tables)
    manifest.append(rec)
    tables, rec = _a12_orphan_providers(run, rng, tables)
    manifest.append(rec)
    tables, rec = _a12b_null_prescriber(run, rng, tables)
    manifest.append(rec)
    manifest.extend(_measure_structural(run, tables))
    if runout_stats:
        manifest.append({
            "anomaly_id": "A7",
            "name": "Claims runout on the most recent service months",
            "description": (
                "Claims absent from this extract are exactly the ones that had "
                f"not adjudicated by the paid-through date of {C.PAID_THROUGH} "
                "- the slowest-paying, not a random sample. Retention below is "
                "measured against each month's own natural volume, which is "
                "the only denominator that makes the designed and realized "
                "figures comparable."
            ),
            "applied": True,
            "measured": runout_stats,
            "detect": (
                "Build the lag triangle, comparing each month against the SAME "
                "calendar month in prior years and de-trending. Comparing "
                "against an annual average measures seasonality and calls it "
                "completeness - December alone carries a 1.45x elective factor."
            ),
            "control": (
                "Filter service-date trends on dim_date.claims_runout_complete_flag, "
                "or trend on paid date, which IS complete. Mixing the two is "
                "the error."
            ),
        })
    return tables, manifest


# ---------------------------------------------------------------------- A9a

def _a9_duplicate_lines(run, rng, tables):
    """An extract re-run duplicated one day of claim lines.

    The teaching point is sharp: because claim_line_key is a SURROGATE, a
    uniqueness test on the primary key PASSES while the business key
    (claim_number, claim_line_number, adjudication_seq) is violated. A
    uniqueness test on a surrogate key is worthless.
    """
    L = tables["clm_claim_line"]
    target_day = C.DUPLICATE_BATCH_DATE.isoformat()
    month = target_day[:7]
    pool = L[(L["service_date"].str.startswith(month)) & (L["net_sign"] == 1)]
    n = min(run.n(DUPLICATE_LINES), len(pool))
    if n == 0:
        return tables, {"anomaly_id": "A9a", "applied": False,
                        "name": "Duplicate claim lines", "rows_added": 0}

    dupes = pool.sample(n=n, random_state=1407).copy()
    dupes["source_load_batch_id"] = DUPLICATE_BATCH
    # New surrogate keys, so the primary key stays unique.
    dupes["claim_line_key"] = np.arange(
        L["claim_line_key"].max() + 1, L["claim_line_key"].max() + 1 + len(dupes)
    )
    month_paid_before = L.loc[
        L["service_date"].str.startswith(month) & L["is_current_version"],
        "paid_amount",
    ].sum()
    inflation = dupes.loc[dupes["is_current_version"], "paid_amount"].sum()

    tables["clm_claim_line"] = pd.concat([L, dupes], ignore_index=True)
    return tables, {
        "anomaly_id": "A9a",
        "name": "Duplicate claim lines from a re-driven extract",
        "description": (
            f"{len(dupes):,} claim lines from service month {month} were loaded "
            f"twice under batch {DUPLICATE_BATCH}. The surrogate primary key "
            f"claim_line_key is unique across all of them, so a primary-key "
            f"uniqueness test passes. The business key "
            f"(claim_number, claim_line_number, adjudication_seq) is violated."
        ),
        "applied": True,
        "rows_added": int(len(dupes)),
        "affected_service_month": month,
        "naive_error": {
            "measure": f"paid amount for service month {month}",
            "correct": round(float(month_paid_before), 2),
            "naive": round(float(month_paid_before + inflation), 2),
            "overstatement_dollars": round(float(inflation), 2),
            "overstatement_pct": round(
                float(inflation / month_paid_before * 100), 2
            ) if month_paid_before else None,
        },
        "detect": (
            "Test grain uniqueness on the BUSINESS key, never the surrogate. "
            "Then group by source_load_batch_id to find the offending load."
        ),
        "control": (
            "De-duplicate on (claim_number, claim_line_number, "
            "adjudication_seq), keeping the earliest load batch."
        ),
    }


# ---------------------------------------------------------------------- A12

def _a12_orphan_providers(run, rng, tables):
    """Servicing provider IDs with no credentialing record.

    Locum tenens and out-of-network fill-ins, concentrated at the urgent care
    that staffs through an agency. Inner-joining the provider dimension
    silently drops these lines and that site's cost per visit looks better
    than reality.
    """
    L = tables["clm_claim_line"]
    at_site = L.index[L["service_site_code"] == org.STAFFING_AGENCY_SITE]
    elsewhere = L.index[L["service_site_code"] != org.STAFFING_AGENCY_SITE]
    want = run.n(ORPHAN_PROVIDER_LINES)
    n_site = min(int(round(want * ORPHAN_CONCENTRATION)), len(at_site))
    n_other = min(want - n_site, len(elsewhere))
    pick = np.concatenate([
        rng.choice(at_site, size=n_site, replace=False) if n_site else np.array([], dtype=int),
        rng.choice(elsewhere, size=n_other, replace=False) if n_other else np.array([], dtype=int),
    ])
    if len(pick) == 0:
        return tables, {"anomaly_id": "A12", "applied": False,
                        "name": "Orphan servicing providers", "rows_affected": 0}

    orphan_ids = np.array([
        f"LOCUM{int(v):05d}" for v in rng.integers(1, 400, size=len(pick))
    ], dtype=object)
    L.loc[pick, "servicing_provider_master_id"] = orphan_ids

    dropped = L.loc[pick]
    dropped_paid = dropped.loc[dropped["is_current_version"], "paid_amount"].sum()

    site_lines = L[(L["service_site_code"] == org.STAFFING_AGENCY_SITE)
                   & L["is_current_version"]]
    site_all = site_lines["paid_amount"].sum()
    site_kept = site_lines.loc[
        ~site_lines["servicing_provider_master_id"].astype(str).str.startswith("LOCUM"),
        "paid_amount",
    ].sum()

    tables["clm_claim_line"] = L
    return tables, {
        "anomaly_id": "A12",
        "name": "Orphan servicing providers, concentrated at one site",
        "description": (
            f"{len(pick):,} claim lines carry a servicing_provider_master_id "
            f"with no row in the credentialing source - locum tenens and "
            f"out-of-network fill-ins. {ORPHAN_CONCENTRATION:.0%} of them sit "
            f"at {org.STAFFING_AGENCY_SITE}, which staffs through an agency."
        ),
        "applied": True,
        "rows_affected": int(len(pick)),
        "concentration_site": org.STAFFING_AGENCY_SITE,
        "naive_error": {
            "measure": "paid amount silently dropped by an inner join to the provider dimension",
            "dropped_dollars": round(float(dropped_paid), 2),
            "site_paid_all_lines": round(float(site_all), 2),
            "site_paid_after_inner_join": round(float(site_kept), 2),
            "site_understatement_pct": round(
                float((1 - site_kept / site_all) * 100), 2
            ) if site_all else None,
        },
        "detect": (
            "Anti-join every foreign key before using it, and report the "
            "orphan count AND the orphan dollars. Never inner join a fact to "
            "a dimension without first counting what the join would drop."
        ),
        "control": (
            "Resolve unmatched keys to the -1 Unknown dimension member and "
            "carry provider_resolution_status so the defect stays countable."
        ),
    }


def _a12b_null_prescriber(run, rng, tables):
    """A share of referral orders carry no referring provider at all."""
    R = tables.get("ehr_referral_order")
    if R is None or R.empty:
        return tables, {"anomaly_id": "A12b", "applied": False,
                        "name": "Null referring provider", "rows_affected": 0}
    n = int(round(len(R) * 0.04))
    pick = rng.choice(R.index, size=n, replace=False)
    R.loc[pick, "referring_provider_master_id"] = None
    tables["ehr_referral_order"] = R
    return tables, {
        "anomaly_id": "A12b",
        "name": "Null referring provider on referral orders",
        "description": (
            f"{n:,} referral orders ({n/len(R):.1%}) have no referring "
            f"provider recorded. Grouping leakage by referring provider "
            f"silently excludes them."
        ),
        "applied": True,
        "rows_affected": int(n),
        "detect": "Count nulls on every grouping key before grouping by it.",
        "control": "Resolve to the -1 Unknown member and report it as a bucket.",
    }


# ------------------------------------------------- measuring structural defects

def _measure_structural(run, tables) -> list[dict]:
    """Measure the defects built into the generators, so the manifest is complete.

    These are not mutations - they arise from how the source systems behave -
    but the answer key still has to quote their magnitude, and quoting a
    MEASURED figure is the only way the documentation stays honest.
    """
    out = []
    L = tables["clm_claim_line"]
    cur = L[L["is_current_version"]]
    R = tables.get("ehr_referral_order", pd.DataFrame())

    # ---- A1 / A2: the auto-close rule and the leakage it hides
    if not R.empty and "_truth_out_of_network" in R.columns:
        R = R.copy()
        R["post"] = pd.to_datetime(R["placed_date"]) >= pd.Timestamp(C.AUTOCLOSE_EFFECTIVE)
        post = R[R["post"]]
        nr = post[post["referring_site_code"] == C.AUTOCLOSE_SITE]
        oth = post[post["referring_site_code"] != C.AUTOCLOSE_SITE]

        def rate(d, col, val=None):
            if d.empty:
                return None
            return round(float((d[col] == val).mean() if val is not None else d[col].mean()), 4)

        by_site = post.groupby("referring_site_code").apply(
            lambda d: pd.Series({
                "apparent": float((d["destination_status_per_ehr_directory"] == "NONPAR").mean()),
                "true": float(d["_truth_out_of_network"].mean()),
            }), include_groups=False
        )
        rank_apparent = int(by_site["apparent"].rank().loc[C.AUTOCLOSE_SITE]) \
            if C.AUTOCLOSE_SITE in by_site.index else None
        rank_true = int(by_site["true"].rank().loc[C.AUTOCLOSE_SITE]) \
            if C.AUTOCLOSE_SITE in by_site.index else None

        day30 = nr["days_to_closure"].astype("float").between(29, 31)
        pre = R[~R["post"] & (R["referring_site_code"] == C.AUTOCLOSE_SITE)]
        out.append({
            "anomaly_id": "A1",
            "name": "Referral auto-close rule at one site",
            "description": (
                f"A scheduling rule effective {C.AUTOCLOSE_EFFECTIVE} auto-closes "
                f"{C.AUTOCLOSE_SITE} referrals at day {C.AUTOCLOSE_DAYS} whether or "
                f"not care happened. Closure rate and open rate both stop meaning "
                f"anything at that site."
            ),
            "applied": True,
            "measured": {
                "day30_closure_share_post_rule": round(float(day30.mean()), 4),
                "day30_closure_share_pre_rule": round(
                    float(pre["days_to_closure"].astype("float").between(29, 31).mean()), 4
                ) if not pre.empty else None,
                "day30_closure_share_other_sites": round(
                    float(oth["days_to_closure"].astype("float").between(29, 31).mean()), 4
                ),
                "system_actor_share_at_site": rate(nr, "closure_actor_type", "SYSTEM"),
                "confirmation_rate_at_site": rate(nr, "_truth_care_occurred"),
                "confirmation_rate_other_sites": rate(oth, "_truth_care_occurred"),
                "open_rate_at_site": rate(nr, "referral_status", "OPEN"),
                "open_rate_other_sites": rate(oth, "referral_status", "OPEN"),
            },
            "detect": (
                "Plot time-to-status before trusting any status field. A spike at "
                "a round number is a workflow rule, not clinical behavior. Then "
                "check closure_actor_type."
            ),
            "control": (
                "Measure referral outcome against a confirming event, not against "
                "the status field. Confirm through claims AND appointments so the "
                "finding survives a challenge to either join."
            ),
        })
        out.append({
            "anomaly_id": "A2",
            "name": "Apparent versus true out-of-network leakage",
            "description": (
                f"{C.AUTOCLOSE_SITE} sends most of its out-of-network volume to "
                f"Summit Point, which still reads PAR in the EHR directory. Its "
                f"leakage is therefore invisible on EHR data alone."
            ),
            "applied": True,
            "measured": {
                "apparent_oon_rate_at_site": rate(nr, "destination_status_per_ehr_directory", "NONPAR"),
                "true_oon_rate_at_site": rate(nr, "_truth_out_of_network"),
                "apparent_oon_rate_other_sites": rate(oth, "destination_status_per_ehr_directory", "NONPAR"),
                "true_oon_rate_other_sites": rate(oth, "_truth_out_of_network"),
                "rank_by_apparent_oon_best_is_1": rank_apparent,
                "rank_by_true_oon_best_is_1": rank_true,
                "sites_ranked": int(len(by_site)),
            },
            "detect": "Join referrals to claims and re-derive network status as of the service date.",
            "control": "Never trust a directory field as a measure; derive it from the contract.",
        })

    # ---- A10: reversal netting
    total_all = float(L["paid_amount"].sum())
    total_cur = float(cur["paid_amount"].sum())
    naive_seq1 = float(L.loc[L["adjudication_seq"] == 1, "paid_amount"].sum())
    naive_pos = float(L.loc[L["paid_amount"] > 0, "paid_amount"].sum())
    no_rev = float(L.loc[L["is_current_version"] & ~L["is_reversal"], "paid_amount"].sum())
    orph = L[L["is_orphan_reversal"]]
    out.append({
        "anomaly_id": "A10",
        "name": "Reversal netting, including orphan reversals",
        "description": (
            f"{int(orph['claim_number'].nunique()):,} reversals reference an "
            f"original that adjudicated before this window opened, so there is "
            f"nothing here to net against. They are retained and flagged."
        ),
        "applied": True,
        "measured": {
            "correct_paid_all_rows": round(total_all, 2),
            "correct_paid_current_version": round(total_cur, 2),
            "two_formulas_agree": bool(abs(total_all - total_cur) < 1.0),
            "orphan_reversal_dollars": round(float(orph["paid_amount"].sum()), 2),
            "naive_seq1_overstatement_pct": round((naive_seq1 / total_cur - 1) * 100, 2),
            "naive_positive_only_overstatement_pct": round((naive_pos / total_cur - 1) * 100, 2),
            "naive_drop_all_reversals_error_pct": round((no_rev / total_cur - 1) * 100, 2),
        },
        "detect": "Check that both sanctioned nettings tie. Anti-join reversals to their originals.",
        "control": (
            "Sum every row, or sum WHERE is_current_version. Do NOT add a "
            "reversal exclusion: orphan reversals are current and negative on "
            "purpose, and excluding them breaks the tie."
        ),
    })

    # ---- A3: the stale EHR directory versus the terminated contract
    dirx = tables.get("ehr_provider_directory")
    nc = tables.get("ref_network_contract")
    if dirx is not None and nc is not None:
        cur_nc = nc[nc["is_current"] == True]  # noqa: E712
        j = dirx.merge(cur_nc[["site_code", "network_status", "effective_date",
                               "termination_reason"]],
                       on="site_code", how="left")
        mismatch = j[j["referral_network_status"] != j["network_status"]]
        ref_to_stale = 0
        if not R.empty:
            ref_to_stale = int(
                R["destination_site_code"].isin(set(mismatch["site_code"])).sum()
            )
        out.append({
            "anomaly_id": "A3",
            "name": "EHR referral directory is a stale copy of network status",
            "description": (
                "The directory is maintained separately from the contract and "
                "nobody updates it. Summit Point's contract terminated "
                f"{C.SUMMIT_POINT_TERM} and the pick-list still reads PAR. A "
                "governance failure with a price tag, and nobody made a bad "
                "clinical decision."
            ),
            "applied": True,
            "measured": {
                "sites_where_directory_disagrees_with_contract": int(len(mismatch)),
                "detail": mismatch[["site_code", "referral_network_status",
                                    "network_status", "last_maintained_date"]]
                          .to_dict(orient="records"),
                "referrals_sent_to_those_sites": ref_to_stale,
            },
            "detect": (
                "Join the directory to the contract and diff the status "
                "columns. Then check last_maintained_date - a stale date on a "
                "field that drives routing is a finding on its own."
            ),
            "control": (
                "Never treat a directory field as a measure. Derive network "
                "status from the contract with an as-of-service-date join."
            ),
        })

    # ---- A4 and A5: the two crosswalk failure modes
    xp = tables.get("xwalk_patient")
    if xp is not None:
        ehr_x = xp[xp["source_system"] == "CARELINE_EHR"]
        tiers = ehr_x["match_method"].value_counts(normalize=True).round(4)
        roster = tables.get("vbc_attribution_month")
        skew = None
        if roster is not None and not R.empty:
            site_by_mrn = R.drop_duplicates("mrn").set_index("mrn")["referring_site_code"]
            tmp = ehr_x.assign(
                site=ehr_x["source_patient_id"].map(site_by_mrn),
                unmatched=ehr_x["match_method"].eq("UNMATCHED"),
            ).dropna(subset=["site"])
            at_site = tmp.loc[tmp["site"] == C.AUTOCLOSE_SITE, "unmatched"].mean()
            elsewhere = tmp.loc[tmp["site"] != C.AUTOCLOSE_SITE, "unmatched"].mean()
            if elsewhere:
                skew = {
                    "unmatched_rate_at_site": round(float(at_site), 4),
                    "unmatched_rate_elsewhere": round(float(elsewhere), 4),
                    "skew_factor": round(float(at_site / elsewhere), 2),
                }
        out.append({
            "anomaly_id": "A4",
            "name": "Crosswalk under-match, and it is NOT random",
            "description": (
                "A share of EHR records never resolve to a member. The loss "
                f"skews toward {C.AUTOCLOSE_SITE} patients, whose registration "
                "workflow does not capture the subscriber ID. So a naive inner "
                "join deletes part of the headline finding and UNDERSTATES the "
                "leakage - the careless analyst gets a wrong answer that still "
                "looks plausible, which is the worst kind."
            ),
            "applied": True,
            "measured": {"match_tier_shares": tiers.to_dict(), "skew": skew},
            "detect": (
                "Profile the unmatched population against the matched on "
                "several attributes before reporting ANY cross-source rate. If "
                "it is skewed, every rate built on an inner join is biased in "
                "a direction you have not measured."
            ),
            "control": (
                "Left join, resolve unmatched to the -1 Unknown member, and "
                "report that bucket rather than dropping it."
            ),
        })

        pat = tables.get("ehr_patient")
        if pat is not None:
            j = ehr_x.merge(pat[["mrn", "sex", "birth_date"]],
                            left_on="source_patient_id", right_on="mrn", how="inner")
            j = j[j["master_person_id"].notna()]
            g = j.groupby("master_person_id").agg(
                sexes=("sex", "nunique"), dobs=("birth_date", "nunique"))
            by_sex = int((g["sexes"] > 1).sum())
            collapsed = int(((g["sexes"] > 1) | (g["dobs"] > 1)).sum())
            out.append({
                "anomaly_id": "A5",
                "name": "Crosswalk over-match: two people wearing one identity",
                "description": (
                    "Twins and Jr/Sr pairs matched on name, date of birth and "
                    "address. They surface as artificial super-utilizers at the "
                    "very top of the cost distribution, contaminating precisely "
                    "the top-1% figure the demo quotes. Over-matching is the "
                    "more interesting failure and is almost never demonstrated."
                ),
                "applied": True,
                "measured": {
                    "master_persons_collapsing_multiple_people": collapsed,
                    "found_by_sex_mismatch_alone": by_sex,
                    "found_only_by_date_of_birth": collapsed - by_sex,
                    # The cost-tail contamination is the CLAIM this anomaly
                    # makes, so it is measured here rather than asserted in
                    # prose. Selecting over-match pairs at random leaves the
                    # collapsed persons at the 52nd percentile of cost, where
                    # they contaminate nothing - the description above was
                    # true of the mechanism and false of the data until the
                    # pairs were drawn from the heaviest utilizers.
                    **_overmatch_cost_tail(tables, xp, j),
                },
                "detect": (
                    "Within each master_person_id, count distinct sex and "
                    "distinct date of birth. Sex mismatch is the cheapest "
                    "detector but it only catches mixed-sex pairs; same-sex "
                    "twins need the date-of-birth check."
                ),
                "control": (
                    "Exclude or split PROBABILISTIC matches below a score "
                    "threshold, and report counts at both thresholds so the "
                    "sensitivity is visible rather than hidden."
                ),
            })

    # ---- A6: retroactive roster restatement
    rest = tables.get("vbc_attribution_restatement")
    if rest is not None and len(rest):
        retro = rest[rest["restatement_reason"].str.startswith("Inpatient")]
        out.append({
            "anomaly_id": "A6",
            "name": "Retroactive attribution restatement",
            "description": (
                "High-cost members are retro-terminated from attribution in "
                "exactly the months containing an inpatient stay at a "
                "non-affiliated hospital. Their cost leaves the numerator and "
                "their member-months leave the denominator, so PMPM improves "
                "without any care changing."
            ),
            "applied": True,
            "measured": {
                "restated_member_months": int(len(rest)),
                "retro_terminated_members": int(retro["member_id"].nunique()),
                "retro_terminated_member_months": int(len(retro)),
                "ordinary_churn_member_months": int(len(rest) - len(retro)),
            },
            "detect": (
                "Compare roster VERSIONS, not just the current roster. Hold a "
                "cohort fixed and re-run the measure."
            ),
            "control": (
                "Report PMPM on a fixed cohort alongside the open-panel "
                "figure, and state the as-of date of the roster used."
            ),
        })

    # ---- A8: overlapping eligibility spans
    spans = tables.get("elig_eligibility_span")
    if spans is not None:
        ov = spans[spans["overlap_reason"].notna()]
        out.append({
            "anomaly_id": "A8",
            "name": "Overlapping coverage spans, concentrated in one group",
            "description": (
                "COBRA running alongside active coverage, and an acquisition "
                "where the prior group span was never terminated. Summing span "
                "lengths double counts every overlap, and because the overlap "
                "concentrates in one employer group the error is UNEVEN: that "
                "group's PMPM reads better than truth. A number that is wrong "
                "unevenly is the kind that survives review."
            ),
            "applied": True,
            "measured": {
                "members_with_overlap": int(ov["member_id"].nunique()),
                "overlap_share_of_members": round(
                    float(ov["member_id"].nunique()
                          / max(spans["member_id"].nunique(), 1)), 4),
                "reasons": ov["overlap_reason"].value_counts().to_dict(),
            },
            "detect": (
                "Test member-month grain uniqueness, and compare the "
                "de-duplicated union against the naive span sum BY GROUP, not "
                "just in total. The total hides it."
            ),
            "control": (
                "Build the denominator as a gaps-and-islands union of coverage. "
                "Never compute member-months from raw spans."
            ),
        })

    # ---- A9b: the duplicates that are NOT duplicates
    bil = L[L["modifier_1"].isin(["50", "76", "LT", "RT"])]
    out.append({
        "anomaly_id": "A9b",
        "name": "Legitimate lines that look like duplicates",
        "description": (
            "Bilateral procedures and same-day repeats produce near-identical "
            "rows distinguished ONLY by modifier. De-duplicating on 'the "
            "obvious business columns' destroys them and UNDERSTATES paid. This "
            "runs in the opposite direction to A9a, and the naive fix for one "
            "creates the other."
        ),
        "applied": True,
        "measured": {
            "lines_distinguished_only_by_modifier": int(len(bil)),
            "paid_at_risk_if_wrongly_deduplicated": round(
                float(bil.loc[bil["is_current_version"], "paid_amount"].sum()), 2),
            "modifier_mix": bil["modifier_1"].value_counts().to_dict(),
        },
        "detect": (
            "Before de-duplicating, check whether the candidate rows differ on "
            "modifier. If they do, they are distinct services."
        ),
        "control": "Modifiers are part of line identity. Include them in the key.",
    })

    # ---- A11a and A11c: encoding drift and the renumbered hospital
    enc = tables.get("ehr_encounter")
    fx = tables.get("ref_facility_crosswalk")
    if enc is not None:
        amb = enc[enc["encounter_class"] == "AMBULATORY"]
        out.append({
            "anomaly_id": "A11a",
            "name": "Encounter type encoded differently by site, one value unmapped",
            "description": (
                "Most sites emit OFFICE, four emit OFFICE VISIT, and one emits "
                "AMB - which has no row in the crosswalk seed at all. It lands "
                "as UNKNOWN and gets filtered out as junk unless someone "
                "profiles distinct values by source."
            ),
            "applied": True,
            "measured": {
                "value_counts": enc["encounter_type_source"].value_counts().to_dict(),
                "unmapped_value": "AMB",
                "unmapped_share_of_ambulatory": round(
                    float((amb["encounter_type_source"] == "AMB").mean()), 4),
            },
            "detect": (
                "Profile distinct values of every low-cardinality column BY "
                "SOURCE and BY MONTH. The month cut is what turns a mystery "
                "into a visible step change."
            ),
            "control": (
                "Assert conformance COVERAGE: every distinct source value must "
                "have a mapping. That one check catches this class of defect "
                "everywhere it occurs."
            ),
        })
    if fx is not None:
        renum = fx[fx["site_code"] == org.RENUMBERED_SITE]
        out.append({
            "anomaly_id": "A11c",
            "name": "One hospital renumbered mid-window by an EMR upgrade",
            "description": (
                f"{org.RENUMBERED_SITE} emits a different department identifier "
                f"from {C.RENUMBER_EFFECTIVE} onward. Without the crosswalk, "
                "volume by facility splits one physical hospital into two as a "
                "step change in the middle of the year."
            ),
            "applied": True,
            "measured": {
                "department_identifiers": renum["ehr_dept_id"].tolist(),
                "effective_windows": renum[["ehr_dept_id", "effective_date",
                                            "expiration_date"]]
                                     .to_dict(orient="records"),
            },
            "detect": "Count distinct facility identifiers by month, not just in total.",
            "control": "Resolve through the versioned facility crosswalk, as-of the service date.",
        })

    # ---- A11b: sex encoding, applied at write time
    out.append({
        "anomaly_id": "A11b",
        "name": "Sex encoded differently in every source system",
        "description": (
            "Eligibility emits M/F/U, the EHR emits HL7 table 0001 values "
            "1/2/9, and the attribution feed emits Male/Female/Unknown. "
            "Conforming them is a prerequisite for any demographic cut."
        ),
        "applied": True,
        "measured": {"encodings": {k: list(v.values()) for k, v in SEX_ENCODING.items()}},
        "detect": "Profile distinct values of every low-cardinality column BY SOURCE.",
        "control": "One conformed dimension with a documented source-of-truth per attribute.",
    })
    return out


def encode_sex_for_source(series: pd.Series, source_system: str) -> pd.Series:
    """Re-encode sex into a given source system's convention (anomaly A11b)."""
    mapping = SEX_ENCODING[source_system]
    return series.map(lambda v: mapping.get(v, mapping[None]))


def _overmatch_cost_tail(tables, xp, joined) -> dict:
    """Where the collapsed identities land in the cost distribution.

    A defect nobody can find in the data is indistinguishable from a defect
    that is not there, so the answer key reports the figure that makes this
    one findable.
    """
    lines = tables.get("clm_claim_line")
    if lines is None or xp is None:
        return {}
    over = set(joined.groupby("master_person_id").filter(
        lambda g: g["sex"].nunique() > 1 or g["birth_date"].nunique() > 1
    )["master_person_id"].unique())
    # Claims live in the PAYER key space, so the collapse only reaches the
    # cost distribution through the eligibility slice of the crosswalk. That
    # slice used to be forced EXACT against the truth column, which is exactly
    # why this figure was zero.
    elig = xp[xp["source_system"] == "MERIDIAN_ELIG"]
    if not len(elig):
        return {}
    m = dict(zip(elig["source_patient_id"], elig["master_person_id"]))
    cur = lines[lines["is_current_version"]] if "is_current_version" in lines \
        else lines
    cur = cur.assign(_mp=cur["member_id"].map(m))
    tot = cur.groupby("_mp")["allowed_amount"].sum().sort_values(ascending=False)
    if not len(tot):
        return {}
    top1 = tot.head(max(1, len(tot) // 100))
    hits = [k for k in top1.index if k in over]
    return {
        "collapsed_persons_in_top_1pct_of_cost": len(hits),
        "their_allowed_amount": round(float(tot.reindex(hits).sum()), 2),
        "top_1pct_threshold_allowed": round(float(top1.min()), 2),
    }
