"""Supplier scorecard, overall OTIF and the exact bridge, read from the SQL reference tables."""

from __future__ import annotations

from typing import Any

import duckdb

from promisedrift.metrics import supplier_values


def scorecard(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """One row per supplier with D1-D4, ranks (1 = best) and the bridge in percentage points."""
    suppliers = con.execute(
        "SELECT supplier_id, supplier_name, commodity FROM suppliers ORDER BY supplier_id"
    ).fetchall()
    lines = dict(con.execute("SELECT supplier_id, count(*) FROM line_status GROUP BY 1").fetchall())
    d1 = supplier_values(con, "OTIF Headline %")
    d2 = supplier_values(con, "OTIF Latest Promise %")
    d3 = supplier_values(con, "OTIF First Confirmed %")
    d4 = supplier_values(con, "OTIF Requested %")
    early = supplier_values(con, "Bridge Early pp")
    repromise = supplier_values(con, "Bridge Re-promise pp")
    partial = supplier_values(con, "Bridge Partial pp")

    rows = [
        {
            "supplier_id": sid,
            "supplier_name": name,
            "commodity": commodity,
            "lines": int(lines[sid]),
            "d1": d1[sid],
            "d2": d2[sid],
            "d3": d3[sid],
            "d4": d4[sid],
            "gap_pp": 100.0 * (d1[sid] - d3[sid]),
            "early_pp": early[sid],
            "repromise_pp": repromise[sid],
            "partial_pp": partial[sid],
        }
        for sid, name, commodity in suppliers
    ]
    for key, rank_key in (("d1_rank", "d1"), ("d3_rank", "d3")):
        ordered = sorted(rows, key=lambda r: (-r[rank_key], r["supplier_id"]))
        for rank, row in enumerate(ordered, start=1):
            row[key] = rank
    for row in rows:
        # Residual bucket: zero under the current rules, kept so the row always adds up.
        row["other_pp"] = -row["gap_pp"] - (
            row["early_pp"] + row["repromise_pp"] + row["partial_pp"]
        )
        row["other_pp"] = 0.0 if abs(row["other_pp"]) < 1e-9 else row["other_pp"]
    return rows


def bridge_counts(con: duckdb.DuckDBPyConnection, supplier_id: str | None = None) -> dict[str, int]:
    """Integer line counts behind the bridge, for all lines or one supplier.

    Returned keys: lines, d1_pass, d3_pass, early, repromise, partial, other. The four bridge
    components are signed counts, so early + repromise + partial + other == d3_pass - d1_pass
    holds exactly.
    """
    where = "WHERE supplier_id = ?" if supplier_id else ""
    params = [supplier_id] if supplier_id else []
    row = con.execute(
        f"""
        SELECT count(*), sum(d1_otif), sum(d3_otif), sum(bridge_early), sum(bridge_repromise),
               sum(bridge_partial), sum(bridge_other)
        FROM line_bridge {where}
        """,
        params,
    ).fetchone()
    keys = ["lines", "d1_pass", "d3_pass", "early", "repromise", "partial", "other"]
    return {k: int(v) for k, v in zip(keys, row, strict=True)}


def overall(con: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """Overall OTIF under D1-D4 (ratios) and the bridge in percentage points."""
    c = bridge_counts(con)
    n = c["lines"]
    d2, d4 = con.execute("SELECT sum(d2_otif), sum(d4_otif) FROM line_otif").fetchone()
    return {
        "lines": n,
        "d1": c["d1_pass"] / n,
        "d2": int(d2) / n,
        "d3": c["d3_pass"] / n,
        "d4": int(d4) / n,
        "early_pp": 100.0 * c["early"] / n,
        "repromise_pp": 100.0 * c["repromise"] / n,
        "partial_pp": 100.0 * c["partial"] / n,
        "other_pp": 100.0 * c["other"] / n,
    }
