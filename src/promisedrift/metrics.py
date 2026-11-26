"""Registry of the reference metrics: name, grain and the SQL that defines each one.

The SQL here is the tested reference. The Power BI measures carry the same names, and
`validate-pbip` fails when the measure set in the semantic model differs from this registry.
Every query returns (supplier_id, value) for the supplier grain, or
(supplier_id, quarter_label, value) for the supplier-quarter grain.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

SUPPLIER = "supplier"
SUPPLIER_QUARTER = "supplier-quarter"


@dataclass(frozen=True)
class Metric:
    name: str
    grain: str
    unit: str  # ratio (0-1), pp (percentage points) or days
    sql: str
    description: str
    # How the Power BI measure must be written: aggregation kind over table[column].
    #   share  DIVIDE ( SUM ( t[c] ), COUNTROWS ( t ) )
    #   pp     100 * DIVIDE ( SUM ( t[c] ), COUNTROWS ( t ) )
    #   avg    AVERAGE ( t[c] )
    #   max    MAX ( t[c] )
    table: str = ""
    column: str = ""
    dax_kind: str = ""


def _otif(flag: str) -> str:
    return f"SELECT supplier_id, avg({flag}) AS value FROM line_otif GROUP BY supplier_id"


def _bridge(component: str) -> str:
    return (
        f"SELECT supplier_id, 100.0 * sum({component}) / count(*) AS value "
        "FROM line_bridge GROUP BY supplier_id"
    )


METRICS: list[Metric] = [
    Metric(
        "OTIF Headline %",
        SUPPLIER,
        "ratio",
        _otif("d1_otif"),
        "D1: first receipt on or before the latest promise, 98% received eventually.",
        "fct_po_line_status",
        "d1_otif",
        "share",
    ),
    Metric(
        "OTIF Latest Promise %",
        SUPPLIER,
        "ratio",
        _otif("d2_otif"),
        "D2: latest promise, window -3/+0 days, 98% received by the promise.",
        "fct_po_line_status",
        "d2_otif",
        "share",
    ),
    Metric(
        "OTIF First Confirmed %",
        SUPPLIER,
        "ratio",
        _otif("d3_otif"),
        "D3: first confirmed date, window -3/+0 days, 98% received by that date.",
        "fct_po_line_status",
        "d3_otif",
        "share",
    ),
    Metric(
        "OTIF Requested %",
        SUPPLIER,
        "ratio",
        _otif("d4_otif"),
        "D4: requested date, window -3/+0 days, 98% received by that date.",
        "fct_po_line_status",
        "d4_otif",
        "share",
    ),
    Metric(
        "Bridge Early pp",
        SUPPLIER,
        "pp",
        _bridge("bridge_early"),
        "Points of D3 - D1 explained by early arrivals.",
        "fct_po_line_status",
        "bridge_early",
        "pp",
    ),
    Metric(
        "Bridge Re-promise pp",
        SUPPLIER,
        "pp",
        _bridge("bridge_repromise"),
        "Points of D3 - D1 explained by moved promise dates (pull-ins count positive).",
        "fct_po_line_status",
        "bridge_repromise",
        "pp",
    ),
    Metric(
        "Bridge Partial pp",
        SUPPLIER,
        "pp",
        _bridge("bridge_partial"),
        "Points of D3 - D1 explained by partial shipments completed after the date.",
        "fct_po_line_status",
        "bridge_partial",
        "pp",
    ),
    Metric(
        "Promise Drift Days",
        SUPPLIER,
        "days",
        "SELECT supplier_id, avg(drift_days) AS value FROM promise_drift GROUP BY supplier_id",
        "Mean days between the first confirmed date and the latest promise.",
        "fct_po_line_status",
        "drift_days",
        "avg",
    ),
    Metric(
        "Lead Time P90 Days",
        SUPPLIER_QUARTER,
        "days",
        "SELECT supplier_id, quarter_label, actual_p90_days AS value FROM lead_time_quarter",
        "90th percentile of actual lead time (order to first receipt) in the order quarter.",
        "fct_lead_time",
        "actual_p90_days",
        "max",
    ),
]


def expected_dax(metric: Metric) -> str:
    """The DAX the model must hold for a metric, with all whitespace removed."""
    ref = f"{metric.table}[{metric.column}]"
    forms = {
        "share": f"DIVIDE(SUM({ref}),COUNTROWS({metric.table}))",
        "pp": f"100*DIVIDE(SUM({ref}),COUNTROWS({metric.table}))",
        "avg": f"AVERAGE({ref})",
        "max": f"MAX({ref})",
    }
    return forms[metric.dax_kind]


METRIC_NAMES = [m.name for m in METRICS]
_BY_NAME = {m.name: m for m in METRICS}


def get_metric(name: str) -> Metric:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"unknown metric {name!r}; known: {', '.join(METRIC_NAMES)}") from None


def supplier_values(con: duckdb.DuckDBPyConnection, name: str) -> dict[str, float]:
    """Evaluate a supplier-grain metric: {supplier_id: value}."""
    metric = get_metric(name)
    if metric.grain != SUPPLIER:
        raise ValueError(f"{name!r} is a {metric.grain} metric")
    return {sid: float(v) for sid, v in con.execute(metric.sql).fetchall()}


def quarter_values(con: duckdb.DuckDBPyConnection, name: str) -> dict[tuple[str, str], float]:
    """Evaluate a supplier-quarter metric: {(supplier_id, quarter_label): value}."""
    metric = get_metric(name)
    if metric.grain != SUPPLIER_QUARTER:
        raise ValueError(f"{name!r} is a {metric.grain} metric")
    return {(sid, q): float(v) for sid, q, v in con.execute(metric.sql).fetchall()}
