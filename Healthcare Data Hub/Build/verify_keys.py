#!/usr/bin/env python3
"""Verify every declared key in mart_keys.py against the shipped data.

    python Build/verify_keys.py

Checks, per table:
  - the declared PK column exists and is 100% unique and non-null
  - the declared business key is unique, or reports the violation count
  - every declared FK column exists, and its orphan rate against the parent

Writes Deliverables/mart-key-verification.json. The manifest generator reads
that file, so nothing reaches the document that has not been measured.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Build"))
import mart_keys as K  # noqa: E402

MART = ROOT / "Mart"


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(MART / f"{name}.csv.gz", low_memory=False)


def norm(series: pd.Series) -> pd.Series:
    """Normalize a key column for comparison, type-insensitively.

    A key column containing nulls is read back as float64, so 600140 becomes
    "600140.0" and a naive string comparison reports 100% orphans on a
    perfectly sound relationship. This is not a hypothetical: it is the single
    most common false alarm when profiling flat files, and it is also a real
    hazard for anyone consuming these CSVs, which is why the manifest carries
    a note about it.
    """
    s = series.dropna()
    if pd.api.types.is_float_dtype(s) and ((s % 1) == 0).all():
        return s.astype("int64").astype(str)
    return s.astype(str)


SENTINEL_KEYS = {-1, -2}


def drop_sentinels(df: pd.DataFrame, pk: str | None) -> pd.DataFrame:
    """Exclude the -1 Unknown and -2 Not Applicable dimension members.

    They exist so facts stay inner-joinable, and they deliberately share a
    NULL business key, so counting them as duplicates would be wrong.
    """
    if pk and pk in df.columns and pd.api.types.is_numeric_dtype(df[pk]):
        return df[~df[pk].isin(SENTINEL_KEYS)]
    return df


def main() -> int:
    cache: dict[str, pd.DataFrame] = {}

    def get(name):
        if name not in cache:
            cache[name] = load(name)
        return cache[name]

    results = {}
    problems = []
    for table, meta in K.KEYS.items():
        df = get(table)
        pk_decl = meta.get("pk")
        real = drop_sentinels(df, pk_decl)
        rec = {"rows": int(len(df)), "columns": int(len(df.columns)),
               "sentinel_rows": int(len(df) - len(real)),
               "grain": meta["grain"], "note": meta.get("note")}

        # ---- primary key
        pk = meta.get("pk")
        if pk:
            if pk not in df.columns:
                rec["pk"] = {"column": pk, "status": "COLUMN MISSING"}
                problems.append(f"{table}: declared PK {pk} does not exist")
            else:
                dupes = int(df[pk].duplicated().sum())
                nulls = int(df[pk].isna().sum())
                rec["pk"] = {
                    "column": pk, "duplicates": dupes, "nulls": nulls,
                    "status": "UNIQUE" if dupes == 0 and nulls == 0 else "NOT UNIQUE",
                }
                if dupes or nulls:
                    problems.append(
                        f"{table}: PK {pk} has {dupes} duplicates, {nulls} nulls")
        else:
            rec["pk"] = {"column": None,
                         "status": "none - bridge keyed on its business key"}

        # ---- business key
        bk = meta.get("business") or []
        have = [c for c in bk if c in df.columns]
        if len(have) != len(bk):
            rec["business"] = {"columns": bk, "status": "COLUMN MISSING"}
            problems.append(f"{table}: business key columns missing: "
                            f"{set(bk) - set(df.columns)}")
        elif bk:
            dupes = int(real.duplicated(have).sum())
            rec["business"] = {
                "columns": bk, "duplicates": dupes,
                "status": "UNIQUE" if dupes == 0 else f"{dupes:,} violations",
            }

        # ---- foreign keys
        fks = []
        for col, parent, pcol, note in meta["fks"]:
            entry = {"column": col, "references": f"{parent}.{pcol}", "note": note}
            if col not in df.columns:
                entry["status"] = "COLUMN MISSING"
                problems.append(f"{table}.{col}: declared FK column does not exist")
            elif parent not in K.KEYS:
                entry["status"] = "parent not in mart"
            else:
                pdf = get(parent)
                if pcol not in pdf.columns:
                    entry["status"] = f"parent column {pcol} missing"
                    problems.append(f"{table}.{col} -> {parent}.{pcol}: "
                                    f"parent column missing")
                else:
                    child = norm(df[col])
                    entry["nulls"] = int(df[col].isna().sum())
                    entry["null_pct"] = round(
                        float(df[col].isna().mean() * 100), 2)
                    entry["float_coerced"] = bool(
                        pd.api.types.is_float_dtype(df[col]))
                    if len(child):
                        parent_vals = set(norm(pdf[pcol]))
                        orphans = int((~child.isin(parent_vals)).sum())
                        entry["orphans"] = orphans
                        entry["orphan_pct"] = round(orphans / len(child) * 100, 2)
                        entry["status"] = "OK" if orphans == 0 else "has orphans"
                    else:
                        entry["orphans"] = 0
                        entry["orphan_pct"] = 0.0
                        entry["status"] = "all null"
            fks.append(entry)
        rec["fks"] = fks
        results[table] = rec
        print(f"  {table:28s} {rec['rows']:>10,} rows  "
              f"PK {rec['pk'].get('status', '?'):<12} "
              f"{len(fks)} FK")

    out = {"tables": results, "problems": problems}
    (ROOT / "Deliverables" / "mart-key-verification.json").write_text(
        json.dumps(out, indent=2))
    print()
    if problems:
        print(f"{len(problems)} problem(s) found:")
        for p in problems:
            print(f"  {p}")
    else:
        print("Every declared primary, business and foreign key verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
