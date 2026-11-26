"""Builders for tiny hand-computed datasets."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from promisedrift.engine import build_database
from promisedrift.generator import Tables, write_tables

D = date(2025, 3, 10)  # the base due date used by the fixtures


def day(offset: int, base: date = D) -> date:
    return base + timedelta(days=offset)


def line(
    line_id: str,
    receipts: list[tuple[date, int]],
    *,
    supplier: str = "SUP-A",
    requested: date = D,
    confirmed: date | None = None,
    changes: list[tuple[int, date, date]] | None = None,
    qty: int = 100,
    order: date | None = None,
) -> dict[str, Any]:
    """One PO line: `changes` are (change_seq, change_dt, new_promise_dt); `receipts` (dt, qty)."""
    return {
        "id": line_id,
        "supplier": supplier,
        "order": order or requested - timedelta(days=20),
        "requested": requested,
        "confirmed": confirmed or requested,
        "qty": qty,
        "changes": changes or [],
        "receipts": receipts,
    }


def build_fixture(
    tmp_path: Path, lines: list[dict[str, Any]], quoted: dict[str, int] | None = None
) -> duckdb.DuckDBPyConnection:
    """Write the lines as raw CSVs and run the SQL reference over them."""
    suppliers = sorted({ln["supplier"] for ln in lines})
    quoted = quoted or {}
    tables: Tables = {
        "suppliers": [
            {
                "supplier_id": s,
                "supplier_name": f"Supplier {s}",
                "commodity": "resin",
                "quoted_lead_days": quoted.get(s, 20),
            }
            for s in suppliers
        ],
        "po_lines": [],
        "promise_changes": [],
        "receipts": [],
    }
    n = 0
    for ln in lines:
        tables["po_lines"].append(
            {
                "po_line_id": ln["id"],
                "supplier_id": ln["supplier"],
                "order_dt": ln["order"],
                "requested_dt": ln["requested"],
                "first_confirmed_dt": ln["confirmed"],
                "ordered_qty": ln["qty"],
            }
        )
        old = ln["confirmed"]
        for seq, change_dt, new in ln["changes"]:
            tables["promise_changes"].append(
                {
                    "po_line_id": ln["id"],
                    "change_seq": seq,
                    "change_dt": change_dt,
                    "old_promise_dt": old,
                    "new_promise_dt": new,
                }
            )
            old = new
        for rdt, rqty in ln["receipts"]:
            n += 1
            tables["receipts"].append(
                {
                    "receipt_id": f"R{n:04d}",
                    "po_line_id": ln["id"],
                    "receipt_dt": rdt,
                    "qty_received": rqty,
                }
            )
    data_dir = tmp_path / "raw"
    write_tables(data_dir, tables)
    return build_database(data_dir)


def ten_line_fixture() -> list[dict[str, Any]]:
    """Five clean lines, one early by 6 days, two re-promised, one 88% partial, one late."""
    return [
        # Supplier A: five clean lines.
        line("L01", [(day(0), 100)]),
        line("L02", [(day(-2), 100)]),
        line("L03", [(day(-3), 100)]),  # exactly 3 days early is still in the window
        line("L04", [(day(4), 100)], confirmed=day(4)),  # confirmed later than requested
        line("L05", [(day(0), 98)]),  # exactly 98% counts as complete
        # Supplier B.
        line("L06", [(day(-6), 100)], supplier="SUP-B"),  # early by 6 days
        line("L07", [(day(7), 100)], supplier="SUP-B", changes=[(1, day(-2), day(7))]),
        line(
            "L08",
            [(day(5), 100)],
            supplier="SUP-B",
            changes=[(1, day(-2), day(3)), (2, day(1), day(5))],
        ),
        line("L09", [(day(0), 88), (day(7), 12)], supplier="SUP-B"),  # partial, balance 7 days on
        line("L10", [(day(4), 100)], supplier="SUP-B"),  # late past its only promise
    ]
