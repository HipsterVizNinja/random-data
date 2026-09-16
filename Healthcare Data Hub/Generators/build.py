#!/usr/bin/env python3
"""Build the Healthcare Data Hub synthetic dataset.

    python Generators/build.py --scale demo
    python Generators/build.py --scale dev --no-anomalies
    python Generators/build.py --scale demo --verify

Execution order IS the dependency chain: reference and population first,
providers and eligibility next, then clinical, scheduling, claims,
attribution, and finally identity resolution. The anomaly stage runs last so
that a clean dataset exists before any defect is applied.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import anomalies as AN
import attribution as AT
import claims as CM
import clinical as CL
import config as C
import crosswalk as XW
import eligibility as EL
import org
import population as POP
import providers as PR
import reference as REF
import scheduling as SC
import write as W

# Which source-system folder each table lands in.
LANDING = {
    "raw_elig": ["elig_member", "elig_eligibility_span", "elig_employer_group",
                 "elig_coverage_plan"],
    "raw_clm": ["clm_claim_header", "clm_claim_line", "clm_claim_diagnosis"],
    "raw_ehr": ["ehr_encounter", "ehr_encounter_diagnosis", "ehr_lab_result",
                "ehr_referral_order", "ehr_provider_directory"],
    "raw_pm": ["pm_appointment", "pm_authorization", "pm_referral_workflow_config"],
    "raw_vbc": ["vbc_attribution_month", "vbc_attribution_restatement",
                "vbc_roster_version", "vbc_benchmark", "vbc_contract_terms"],
    "raw_ref": ["ref_date", "ref_diagnosis", "ref_procedure", "ref_service_place",
                "ref_drg", "ref_claim_status", "ref_service_line",
                "ref_revenue_code", "ref_facility", "ref_network_contract",
                "ref_service_line_crosswalk", "ref_facility_crosswalk",
                "ref_provider", "ref_provider_affiliation", "ref_npi_registry"],
}
MART_TABLES = ["xwalk_patient", "xwalk_provider", "dim_master_person",
               "fct_member_month"]


def log(msg: str, t0: float) -> None:
    print(f"  [{time.time() - t0:6.1f}s] {msg}", flush=True)


def build(run: C.RunConfig) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    t0 = time.time()
    tables: dict[str, pd.DataFrame] = {}

    print(f"\nBuilding scale={run.scale.name} "
          f"members={run.scale.n_members:,} seed={run.seed} "
          f"anomalies={run.apply_anomalies}")

    # ---- reference
    tables["ref_date"] = REF.build_dim_date()
    tables["ref_diagnosis"] = REF.build_dim_diagnosis()
    tables["ref_procedure"] = REF.build_dim_procedure()
    tables["ref_service_place"] = REF.build_dim_service_place()
    tables["ref_drg"] = REF.build_dim_drg()
    tables["ref_claim_status"] = REF.build_dim_claim_status()
    tables["ref_service_line"] = REF.build_dim_service_line()
    tables["ref_revenue_code"] = REF.build_revenue_codes()
    fac_rng = run.rng("org")
    fac = org.build_dim_facility(fac_rng)
    tables["ref_facility"] = fac
    tables["ref_network_contract"] = org.build_network_contract(fac)
    tables["ref_service_line_crosswalk"] = org.build_service_line_crosswalk()
    tables["ref_facility_crosswalk"] = org.build_facility_crosswalk(fac)
    plans = org.build_dim_coverage_plan()
    tables["elig_coverage_plan"] = plans
    log("reference and org", t0)

    # ---- population
    pop = POP.build_population(run)
    members = pop["members"]
    log(f"population: {len(members):,} members, "
        f"{len(pop['households']):,} households", t0)

    # ---- providers
    pv = PR.build_providers(run, fac)
    tables["ref_provider"] = pv["provider_scd2"]
    tables["ref_provider_affiliation"] = pv["affiliation"]
    tables["ehr_provider_directory"] = pv["ehr_provider_directory"]
    tables["ref_npi_registry"] = pv["provider_master"][
        ["npi", "provider_master_id", "first_name", "last_name", "credential",
         "primary_specialty", "taxonomy_code", "tin"]
    ].copy()
    log(f"providers: {len(pv['provider_master']):,} master, "
        f"{len(pv['provider_scd2']):,} type-2 rows", t0)

    # ---- eligibility
    el = EL.build_eligibility(run, members, plans)
    tables["elig_eligibility_span"] = el["eligibility_span"]
    tables["elig_employer_group"] = el["employer_group"]
    tables["fct_member_month"] = el["member_month"]
    log(f"eligibility: {len(el['eligibility_span']):,} spans, "
        f"{len(el['member_month']):,} member-months", t0)

    # ---- clinical
    cl = CL.build_clinical(run, members, pv["provider_master"], fac,
                           el["member_month"])
    tables["ehr_encounter"] = cl["ehr_encounter"]
    tables["ehr_encounter_diagnosis"] = cl["ehr_encounter_diagnosis"]
    tables["ehr_lab_result"] = cl["ehr_lab_result"]
    tables["ehr_referral_order"] = cl["ehr_referral_order"]
    log(f"clinical: {len(cl['ehr_encounter']):,} encounters, "
        f"{len(cl['ehr_referral_order']):,} referrals", t0)

    # ---- scheduling
    sc = SC.build_scheduling(run, cl["ehr_referral_order"], cl["ehr_encounter"])
    tables.update(sc)
    log(f"scheduling: {len(sc['pm_appointment']):,} appointments", t0)

    # ---- claims
    cm = CM.build_claims(run, members, pv["provider_master"], fac,
                         cl["ehr_encounter"], cl["ehr_referral_order"],
                         el["eligibility_span"], plans)
    runout_stats = cm.pop("_runout_stats", {})
    tables.update(cm)
    log(f"claims: {len(cm['clm_claim_header']):,} headers, "
        f"{len(cm['clm_claim_line']):,} lines", t0)

    # ---- attribution
    at = AT.build_attribution(run, members, el["member_month"],
                              cl["ehr_encounter"], cm["clm_claim_line"])
    tables.update(at)
    n_term = int((at["vbc_attribution_restatement"].new_status
                  == "RETRO_TERMINATED").sum())
    n_add = int((at["vbc_attribution_restatement"].new_status
                 == "ATTRIBUTED").sum())
    log(f"attribution: {len(at['vbc_attribution_month']):,} roster months, "
        f"{n_term:,} retro-terminations and {n_add:,} retro-additions across "
        f"{len(at['vbc_roster_version'])} roster versions", t0)

    # ---- identity resolution
    xw = XW.build_crosswalks(run, members, pv["provider_master"])
    tables.update(xw)
    log(f"crosswalk: {len(xw['xwalk_patient']):,} patient keys, "
        f"{len(xw['dim_master_person']):,} master persons", t0)

    # ---- the member table as the eligibility source sees it, with that
    # source's own sex encoding (anomaly A11b).
    mem_out = members[[
        "member_id", "subscriber_id", "person_code", "first_name",
        "middle_initial", "last_name", "birth_date", "sex", "street_address",
        "postal_code", "region", "line_of_business", "risk_score",
    ]].copy()
    mem_out["sex"] = AN.encode_sex_for_source(mem_out["sex"], "MERIDIAN_ELIG")
    tables["elig_member"] = mem_out

    # The EHR knows the same people under its own identifiers and its own
    # encoding. This is the join the whole hub exists to make possible.
    enc_pat = members[["mrn", "first_name", "last_name", "birth_date", "sex",
                       "postal_code"]].copy()
    enc_pat["sex"] = AN.encode_sex_for_source(enc_pat["sex"], "CARELINE_EHR")
    tables["ehr_patient"] = enc_pat
    LANDING["raw_ehr"].append("ehr_patient")

    # ---- anomalies last, so a clean dataset exists first
    tables, manifest = AN.apply_anomalies(run, tables, runout_stats)
    applied = sum(1 for m in manifest if m.get("applied"))
    log(f"anomalies: {applied} records in manifest", t0)

    return tables, manifest


def write_all(run: C.RunConfig, tables: dict, manifest: list[dict]) -> list[dict]:
    entries = []
    truth_dir = run.out_root / "Deliverables" / "truth"
    for folder, names in LANDING.items():
        for name in names:
            if name not in tables:
                continue
            df = tables[name]
            path = run.raw_dir / folder / f"{name}.csv.gz"
            entries.append(W.write_table(df, path, name))
            t = W.truth_columns(df, W.SORT_KEYS.get(name, list(df.columns)[:2]))
            if t is not None:
                W.write_table(t, truth_dir / f"{name}_truth.csv.gz", name,
                              add_classification=False)
    for name in MART_TABLES:
        if name in tables:
            path = run.mart_dir / f"{name}.csv.gz"
            entries.append(W.write_table(tables[name], path, name))

    man_path = run.out_root / "Deliverables" / "anomaly-manifest.json"
    man_path.parent.mkdir(parents=True, exist_ok=True)
    man_path.write_text(json.dumps({
        "scale": run.scale.name,
        "members": run.scale.n_members,
        "seed": run.seed,
        "anomalies_applied": run.apply_anomalies,
        "anomalies": manifest,
    }, indent=2, default=str) + "\n")
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scale", default=C.DEFAULT_SCALE, choices=sorted(C.SCALES))
    ap.add_argument("--seed", type=int, default=C.MASTER_SEED)
    ap.add_argument("--no-anomalies", action="store_true",
                    help="build the clean twin dataset")
    ap.add_argument("--out", type=Path, default=None,
                    help="alternate output root (default: the project folder)")
    ap.add_argument("--verify", action="store_true",
                    help="compare this build against the stored manifest")
    ap.add_argument("--only", nargs="*", default=None,
                    help="write only these tables")
    args = ap.parse_args()

    run = C.make_run(
        scale=args.scale, seed=args.seed,
        apply_anomalies=not args.no_anomalies, out_root=args.out,
    )
    t0 = time.time()
    tables, manifest = build(run)
    if args.only:
        tables = {k: v for k, v in tables.items() if k in set(args.only)}
    entries = write_all(run, tables, manifest)

    man_path = run.out_root / "Deliverables" / "manifest.sha256"
    if args.verify:
        ok, problems = W.verify_manifest(entries, man_path)
        print()
        if ok:
            print("VERIFY OK - every file reproduced byte-for-byte")
        else:
            print(f"VERIFY FAILED - {len(problems)} difference(s):")
            for p in problems[:20]:
                print(f"  {p}")
            return 1
    else:
        W.write_manifest(entries, run, man_path)

    total_rows = sum(e["rows"] for e in entries)
    total_mb = sum(e["bytes_gzipped"] for e in entries) / 1e6
    print()
    print(f"Wrote {len(entries)} tables, {total_rows:,} rows, "
          f"{total_mb:,.1f} MB gzipped in {time.time() - t0:.1f}s")
    print(f"  source data  {run.raw_dir}")
    print(f"  mart         {run.mart_dir}")
    print(f"  manifest     {man_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
