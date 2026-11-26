"""The star schema exported for Power BI: tables, column order and column types.

Types use the TMDL names (string, int64, dateTime, double) so the same spec drives the CSV
export and what the validator expects in the semantic model.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    dtype: str  # string | int64 | dateTime | double


def _cols(*pairs: tuple[str, str]) -> list[ColumnSpec]:
    return [ColumnSpec(name, dtype) for name, dtype in pairs]


STAR: dict[str, list[ColumnSpec]] = {
    "dim_supplier": _cols(
        ("supplier_id", "string"),
        ("supplier_name", "string"),
        ("commodity", "string"),
    ),
    "dim_date": _cols(
        ("date", "dateTime"),
        ("year", "int64"),
        ("quarter_label", "string"),
        ("quarter_start", "dateTime"),
        ("month_start", "dateTime"),
        ("month_label", "string"),
    ),
    "fct_po_line_status": _cols(
        ("po_line_id", "string"),
        ("supplier_id", "string"),
        ("order_dt", "dateTime"),
        ("requested_dt", "dateTime"),
        ("first_confirmed_dt", "dateTime"),
        ("latest_promise_dt", "dateTime"),
        ("first_receipt_dt", "dateTime"),
        ("ordered_qty", "int64"),
        ("qty_eventual", "int64"),
        ("qty_by_requested", "int64"),
        ("qty_by_first_confirmed", "int64"),
        ("qty_by_latest_promise", "int64"),
        ("repromise_count", "int64"),
        ("drift_days", "int64"),
        ("d1_otif", "int64"),
        ("d2_otif", "int64"),
        ("d3_otif", "int64"),
        ("d4_otif", "int64"),
        ("bridge_cause", "string"),
        ("bridge_early", "int64"),
        ("bridge_repromise", "int64"),
        ("bridge_partial", "int64"),
        ("bridge_other", "int64"),
    ),
    "fct_lead_time": _cols(
        ("supplier_id", "string"),
        ("quarter_label", "string"),
        ("quarter_start", "dateTime"),
        ("lines", "int64"),
        ("quoted_lead_days", "int64"),
        ("actual_p50_days", "double"),
        ("actual_p90_days", "double"),
    ),
}

# One-side keys of the relationships; unique in the export.
PRIMARY_KEYS = {
    "dim_supplier": "supplier_id",
    "dim_date": "date",
    "fct_po_line_status": "po_line_id",
}


def column_names(table: str) -> list[str]:
    return [c.name for c in STAR[table]]
