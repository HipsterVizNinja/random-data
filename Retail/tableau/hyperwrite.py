"""Write a multi-table .hyper from pandas frames, driven by the same Col specs
that tdsbuild uses for the .tds, so the extract and the model never drift.
"""
import os

import pandas as pd
from tableauhyperapi import (Connection, CreateMode, HyperProcess, Inserter,
                             SqlType, TableDefinition, TableName, Telemetry)

SQL_TYPES = {
    "string": SqlType.text,
    "integer": SqlType.big_int,
    "real": SqlType.double,
    "date": SqlType.date,
    "datetime": SqlType.timestamp,
    "boolean": SqlType.bool,
}

CHUNK = 250_000


def _rows(frame, columns, start, stop):
    block = frame.iloc[start:stop]
    series = []
    for col in columns:
        values = block[col.remote]
        if col.dtype == "date" and pd.api.types.is_datetime64_any_dtype(values):
            values = values.dt.date
        series.append(values.astype(object).where(values.notna(), None))
    return list(zip(*(s.tolist() for s in series)))


def write_hyper(path, tables):
    """tables: list of (table name, [tdsbuild.Col], DataFrame)."""
    if os.path.exists(path):
        os.remove(path)
    # Keep hyperd.log out of whatever directory the script was run from.
    log_dir = os.path.dirname(os.path.abspath(path)) or "."
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                      parameters={"log_dir": log_dir}) as hyper:
        with Connection(hyper.endpoint, path, CreateMode.CREATE_AND_REPLACE) as conn:
            conn.catalog.create_schema("Extract")
            for name, columns, frame in tables:
                definition = TableDefinition(TableName("Extract", name), [
                    TableDefinition.Column(c.remote, SQL_TYPES[c.dtype]())
                    for c in columns])
                conn.catalog.create_table(definition)
                with Inserter(conn, definition) as inserter:
                    for start in range(0, len(frame), CHUNK):
                        inserter.add_rows(_rows(frame, columns, start, start + CHUNK))
                    inserter.execute()
                print(f"  {name}: {len(frame):,} rows", flush=True)
    return path
