"""Export the DuckDB reference tables as the CSV star schema the Power BI model loads."""

from __future__ import annotations

from pathlib import Path

import duckdb

from promisedrift.schema import STAR, column_names

# Source query per exported table. The column list comes from schema.STAR, so the CSV header is
# the schema by construction.
SOURCES: dict[str, str] = {
    "dim_supplier": "SELECT * FROM suppliers",
    "dim_date": """
        WITH bounds AS (
            SELECT
                date_trunc('month', min(order_dt)) AS lo,
                last_day(greatest(
                    max(first_confirmed_dt), max(latest_promise_dt), max(last_receipt_dt)
                )) AS hi
            FROM line_status
        )
        SELECT
            CAST(d AS DATE) AS date,
            CAST(year(d) AS BIGINT) AS year,
            strftime(d, '%Y') || '-Q' || CAST(quarter(d) AS VARCHAR) AS quarter_label,
            CAST(date_trunc('quarter', d) AS DATE) AS quarter_start,
            CAST(date_trunc('month', d) AS DATE) AS month_start,
            strftime(d, '%Y-%m') AS month_label
        FROM bounds, generate_series(lo, hi, INTERVAL 1 DAY) AS t(d)
    """,
    "fct_po_line_status": """
        SELECT
            s.po_line_id,
            s.supplier_id,
            s.order_dt,
            s.requested_dt,
            s.first_confirmed_dt,
            s.latest_promise_dt,
            s.first_receipt_dt,
            s.ordered_qty,
            s.qty_eventual,
            s.qty_by_requested,
            s.qty_by_first_confirmed,
            s.qty_by_latest_promise,
            d.n_repromise AS repromise_count,
            d.drift_days,
            o.d1_otif,
            o.d2_otif,
            o.d3_otif,
            o.d4_otif,
            b.cause AS bridge_cause,
            b.bridge_early,
            b.bridge_repromise,
            b.bridge_partial,
            b.bridge_other
        FROM line_status AS s
        INNER JOIN line_otif AS o USING (po_line_id)
        INNER JOIN line_bridge AS b USING (po_line_id)
        INNER JOIN promise_drift AS d USING (po_line_id)
    """,
    "fct_lead_time": "SELECT * FROM lead_time_quarter",
}

ORDER_BY = {
    "dim_supplier": "supplier_id",
    "dim_date": "date",
    "fct_po_line_status": "po_line_id",
    "fct_lead_time": "supplier_id, quarter_start",
}


def export_star(con: duckdb.DuckDBPyConnection, out_dir: Path) -> dict[str, int]:
    """Write one CSV per star-schema table into out_dir and return the row counts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for table in STAR:
        columns = ", ".join(column_names(table))
        query = f"SELECT {columns} FROM ({SOURCES[table]}) ORDER BY {ORDER_BY[table]}"
        path = out_dir / f"{table}.csv"
        con.execute(f"COPY ({query}) TO '{path}' (FORMAT CSV, HEADER, DELIMITER ',')")
        counts[table] = int(con.execute(f"SELECT count(*) FROM ({query})").fetchone()[0])
    return counts
