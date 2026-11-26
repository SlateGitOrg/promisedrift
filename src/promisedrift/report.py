"""Markdown scorecard: OTIF under four definitions, the D1 -> D3 bridge and per-supplier ranks."""

from __future__ import annotations

import duckdb

from promisedrift.analysis import overall, scorecard


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def _pp(value: float) -> str:
    return f"{value:+.1f}" if abs(value) >= 0.05 else "0.0"


def render_report(con: duckdb.DuckDBPyConnection, top: int | None = None) -> str:
    """Render the scorecard. With top set, the supplier table lists only the top N by D1."""
    total = overall(con)
    first, last, suppliers = con.execute(
        "SELECT min(order_dt), max(order_dt), count(DISTINCT supplier_id) FROM line_status"
    ).fetchone()
    d3_minus_d1 = 100 * (total["d3"] - total["d1"])

    out = [
        "# Supplier OTIF scorecard",
        "",
        f"{suppliers} suppliers, {total['lines']:,} PO lines ordered {first} to {last}.",
        "",
        "## OTIF under four definitions",
        "",
        "| Definition | Judged against | OTIF |",
        "|---|---|---:|",
        f"| D1 ERP headline | latest promise, early counts as on time | {_pct(total['d1'])} |",
        f"| D2 latest promise | latest promise, window -3/+0 days | {_pct(total['d2'])} |",
        f"| D3 first confirmed | first confirmed date, window -3/+0 days | {_pct(total['d3'])} |",
        f"| D4 requested | requested date, window -3/+0 days | {_pct(total['d4'])} |",
        "",
        "## Bridge from headline (D1) to first-confirmed (D3)",
        "",
        "| Step | pp |",
        "|---|---:|",
        f"| D1 headline | {100 * total['d1']:.1f} |",
        f"| Early arrival | {_pp(total['early_pp'])} |",
        f"| Re-promise | {_pp(total['repromise_pp'])} |",
        f"| Partial shipment | {_pp(total['partial_pp'])} |",
        f"| Other | {_pp(total['other_pp'])} |",
        f"| D3 first confirmed | {100 * total['d3']:.1f} |",
        "",
        f"The components sum to D3 - D1 = {d3_minus_d1:+.1f} pp. Pull-ins (a promise moved earlier,"
        " delivery on the original date) count positive inside Re-promise.",
        "",
    ]

    rows = sorted(scorecard(con), key=lambda r: r["d1_rank"])
    heading = "## Suppliers by headline rank"
    if top is not None:
        rows = rows[:top]
        heading = f"## Top {top} suppliers by headline OTIF"
    out += [
        heading,
        "",
        "| Supplier | Commodity | Lines | D1 | D1 rank | D3 | D3 rank | D1 - D3 pp "
        "| Early pp | Re-promise pp | Partial pp |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        out.append(
            f"| {r['supplier_id']} {r['supplier_name']} | {r['commodity']} | {r['lines']} "
            f"| {_pct(r['d1'])} | {r['d1_rank']} | {_pct(r['d3'])} | {r['d3_rank']} "
            f"| {r['gap_pp']:.1f} | {_pp(r['early_pp'])} | {_pp(r['repromise_pp'])} "
            f"| {_pp(r['partial_pp'])} |"
        )
    out.append("")
    return "\n".join(out)
