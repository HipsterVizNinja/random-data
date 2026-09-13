"""Output writers: gzipped CSV, deterministic sort order, and a hash manifest.

Gzipped CSV rather than Parquet because the build carries no dependency
beyond pandas and numpy, and because both Tableau and Sigma read it directly.
Every file is sorted by its business key before writing, so byte-identical
regeneration is achievable and the manifest means something.

Internal truth columns (anything prefixed with an underscore) never reach the
Source Data folder. They are written separately under Deliverables/truth/ and
clearly labeled as the answer key.
"""
from __future__ import annotations

import gzip
import hashlib
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import config as C

TRUTH_PREFIX = "_"

# Business keys used to impose a deterministic sort before writing.
SORT_KEYS = {
    "clm_claim_line": ["claim_number", "claim_line_number", "adjudication_seq", "net_sign"],
    "clm_claim_header": ["claim_number", "adjudication_seq", "net_sign"],
    "clm_claim_diagnosis": ["claim_number", "diagnosis_position"],
    "ehr_encounter": ["encounter_id"],
    "ehr_encounter_diagnosis": ["encounter_id", "diagnosis_position"],
    "ehr_lab_result": ["encounter_id", "lab_code"],
    "ehr_referral_order": ["referral_id"],
    "ehr_provider_directory": ["site_code"],
    "elig_eligibility_span": ["member_id", "span_start_date", "group_id"],
    "elig_member": ["member_id"],
    "elig_employer_group": ["group_id"],
    "elig_coverage_plan": ["plan_code"],
    "pm_appointment": ["appointment_id"],
    "pm_authorization": ["authorization_id"],
    "pm_referral_workflow_config": ["workflow_config_key"],
    "vbc_attribution_month": ["member_id", "year_month"],
    "vbc_attribution_restatement": ["member_id", "year_month"],
    "vbc_benchmark": ["year_month", "line_of_business"],
}


def strip_truth(df: pd.DataFrame) -> pd.DataFrame:
    drop = [c for c in df.columns if c.startswith(TRUTH_PREFIX)]
    return df.drop(columns=drop) if drop else df


def truth_columns(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame | None:
    cols = [c for c in df.columns if c.startswith(TRUTH_PREFIX)]
    if not cols:
        return None
    keep = [k for k in keys if k in df.columns]
    return df[keep + cols].copy()


def _sort(name: str, df: pd.DataFrame) -> pd.DataFrame:
    keys = [k for k in SORT_KEYS.get(name, []) if k in df.columns]
    if keys:
        return df.sort_values(keys, kind="mergesort").reset_index(drop=True)
    return df


def write_table(
    df: pd.DataFrame, path: Path, name: str, add_classification: bool = True
) -> dict:
    """Write one gzipped CSV and return its manifest entry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = _sort(name, strip_truth(df))
    if add_classification and "data_classification" not in out.columns:
        # Belt and suspenders: every fact and dimension declares itself
        # synthetic, so the label survives being loaded into any tool.
        out["data_classification"] = "SYNTHETIC"

    # mtime=0 so gzip headers do not change between runs; the bytes then
    # depend only on the data, which is what makes --verify meaningful.
    buf = out.to_csv(index=False, lineterminator="\n").encode("utf-8")
    with open(path, "wb") as fh:
        with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
            gz.write(buf)

    return {
        "file": str(path.relative_to(C.PROJECT_ROOT)),
        "table": name,
        "rows": int(len(out)),
        "columns": int(len(out.columns)),
        "sha256": hashlib.sha256(buf).hexdigest(),
        "bytes_gzipped": path.stat().st_size,
    }


def write_manifest(entries: list[dict], run: C.RunConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total_rows = sum(e["rows"] for e in entries)
    total_bytes = sum(e["bytes_gzipped"] for e in entries)
    lines = [
        "# Healthcare Data Hub - output manifest",
        "#",
        "# Hashes are of the UNCOMPRESSED CSV bytes, so they are stable across",
        "# gzip implementations. Re-run build.py --verify to confirm the dataset",
        "# regenerates identically.",
        "#",
        f"# generated_utc      {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"# scale              {run.scale.name} ({run.scale.n_members:,} members)",
        f"# master_seed        {run.seed}",
        f"# anomalies_applied  {run.apply_anomalies}",
        f"# python             {sys.version.split()[0]}",
        f"# pandas             {pd.__version__}",
        f"# numpy              {np.__version__}",
        f"# platform           {platform.platform()}",
        f"# tables             {len(entries)}",
        f"# total_rows         {total_rows:,}",
        f"# total_bytes_gzip   {total_bytes:,}",
        "#",
        "# sha256  rows  file",
    ]
    for e in sorted(entries, key=lambda x: x["file"]):
        lines.append(f"{e['sha256']}  {e['rows']}  {e['file']}")
    path.write_text("\n".join(lines) + "\n")


def verify_manifest(entries: list[dict], path: Path) -> tuple[bool, list[str]]:
    """Compare a fresh build against a stored manifest."""
    if not path.exists():
        return False, ["no stored manifest to compare against"]
    stored = {}
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        sha, rows, file = line.split(None, 2)
        stored[file] = (sha, int(rows))
    problems = []
    for e in entries:
        prev = stored.get(e["file"])
        if prev is None:
            problems.append(f"new file not in manifest: {e['file']}")
        elif prev[0] != e["sha256"]:
            problems.append(
                f"hash changed: {e['file']} ({prev[1]:,} -> {e['rows']:,} rows)"
            )
    for f in stored:
        if f not in {e["file"] for e in entries}:
            problems.append(f"file missing from this build: {f}")
    return not problems, problems
