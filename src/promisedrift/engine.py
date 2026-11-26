"""Load the raw CSVs into DuckDB and run the SQL reference."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import duckdb

RAW_TYPES: dict[str, dict[str, str]] = {
    "suppliers": {
        "supplier_id": "VARCHAR",
        "supplier_name": "VARCHAR",
        "commodity": "VARCHAR",
        "quoted_lead_days": "INTEGER",
    },
    "po_lines": {
        "po_line_id": "VARCHAR",
        "supplier_id": "VARCHAR",
        "order_dt": "DATE",
        "requested_dt": "DATE",
        "first_confirmed_dt": "DATE",
        "ordered_qty": "INTEGER",
    },
    "promise_changes": {
        "po_line_id": "VARCHAR",
        "change_seq": "INTEGER",
        "change_dt": "DATE",
        "old_promise_dt": "DATE",
        "new_promise_dt": "DATE",
    },
    "receipts": {
        "receipt_id": "VARCHAR",
        "po_line_id": "VARCHAR",
        "receipt_dt": "DATE",
        "qty_received": "INTEGER",
    },
}

# SQL file stem -> table it materialises. Order matters: later files read earlier tables.
SQL_PIPELINE: list[tuple[str, str]] = [
    ("line_status", "line_status"),
    ("otif_by_definition", "line_otif"),
    ("otif_bridge", "line_bridge"),
    ("promise_drift", "promise_drift"),
    ("lead_time", "lead_time_quarter"),
]


def read_sql(stem: str) -> str:
    """Return the text of a packaged SQL file without a trailing semicolon."""
    text = resources.files("promisedrift").joinpath("sql", f"{stem}.sql").read_text("utf-8")
    return text.strip().rstrip(";")


def load_raw(con: duckdb.DuckDBPyConnection, data_dir: Path) -> None:
    """Create the four raw tables from CSV files in data_dir."""
    for table, types in RAW_TYPES.items():
        path = data_dir / f"{table}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} not found; run `promisedrift generate` first")
        columns = ", ".join(f"'{name}': '{dtype}'" for name, dtype in types.items())
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(
            f"CREATE TABLE {table} AS "
            f"SELECT * FROM read_csv(?, header = true, columns = {{{columns}}})",
            [str(path)],
        )


def run_pipeline(con: duckdb.DuckDBPyConnection) -> None:
    """Define the shared macros, then materialise every reference table from its SQL file."""
    con.execute(read_sql("macros") + ";")
    for stem, table in SQL_PIPELINE:
        con.execute(f"CREATE OR REPLACE TABLE {table} AS {read_sql(stem)}")


def build_database(data_dir: Path, db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Load raw data and run the SQL reference. In memory when db_path is None."""
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path) if db_path is not None else ":memory:")
    load_raw(con, data_dir)
    run_pipeline(con)
    return con
