"""Metric registry and the star-schema export."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT
from promisedrift.analysis import overall
from promisedrift.metrics import (
    METRIC_NAMES,
    METRICS,
    SUPPLIER,
    SUPPLIER_QUARTER,
    get_metric,
    quarter_values,
    supplier_values,
)
from promisedrift.schema import PRIMARY_KEYS, STAR, column_names

EXPECTED_NAMES = [
    "OTIF Headline %",
    "OTIF Latest Promise %",
    "OTIF First Confirmed %",
    "OTIF Requested %",
    "Bridge Early pp",
    "Bridge Re-promise pp",
    "Bridge Partial pp",
    "Promise Drift Days",
    "Lead Time P90 Days",
]


def test_registry_has_exactly_the_nine_reference_metrics():
    assert METRIC_NAMES == EXPECTED_NAMES
    assert len(set(METRIC_NAMES)) == 9
    assert [m.grain for m in METRICS].count(SUPPLIER_QUARTER) == 1


def test_every_metric_sql_runs_and_covers_all_suppliers(seed_con):
    for metric in METRICS:
        rows = seed_con.execute(metric.sql).fetchall()
        width = 2 if metric.grain == SUPPLIER else 3
        assert all(len(r) == width for r in rows), metric.name
        assert {r[0] for r in rows} == {f"SUP-{i:02d}" for i in range(1, 36)}, metric.name


def test_supplier_metrics_reproduce_the_overall_numbers(seed_con):
    total = overall(seed_con)
    lines = dict(
        seed_con.execute("SELECT supplier_id, count(*) FROM line_status GROUP BY 1").fetchall()
    )
    n = sum(lines.values())
    d1 = supplier_values(seed_con, "OTIF Headline %")
    assert sum(d1[s] * lines[s] for s in lines) / n == pytest.approx(total["d1"])
    early = supplier_values(seed_con, "Bridge Early pp")
    assert sum(early[s] * lines[s] for s in lines) / n == pytest.approx(total["early_pp"])


def test_metric_lookup_and_grain_guards(seed_con):
    assert get_metric("Promise Drift Days").unit == "days"
    with pytest.raises(KeyError, match="unknown metric"):
        get_metric("OTIF Magic %")
    with pytest.raises(ValueError, match="supplier-quarter"):
        supplier_values(seed_con, "Lead Time P90 Days")
    with pytest.raises(ValueError, match="supplier metric"):
        quarter_values(seed_con, "OTIF Headline %")


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def test_export_headers_equal_the_schema_and_row_counts_are_right(seed_export):
    for table in STAR:
        header, rows = _read(seed_export / f"{table}.csv")
        assert header == column_names(table)
        assert rows, table
    assert len(_read(seed_export / "fct_po_line_status.csv")[1]) == 9000
    assert len(_read(seed_export / "dim_supplier.csv")[1]) == 35
    assert len(_read(seed_export / "fct_lead_time.csv")[1]) == 35 * 6


def test_primary_keys_are_unique_in_the_export(seed_export):
    for table, key in PRIMARY_KEYS.items():
        values = [r[key] for r in _read(seed_export / f"{table}.csv")[1]]
        assert len(values) == len(set(values)), table


def test_export_fact_flags_agree_with_the_bridge(seed_export):
    _, rows = _read(seed_export / "fct_po_line_status.csv")
    for r in rows:
        delta = int(r["d3_otif"]) - int(r["d1_otif"])
        parts = sum(
            int(r[k])
            for k in ("bridge_early", "bridge_repromise", "bridge_partial", "bridge_other")
        )
        assert parts == delta
        assert (r["bridge_cause"] == "") == (delta == 0)


def test_dim_date_covers_every_date_the_facts_relate_to(seed_export):
    dates = {r["date"] for r in _read(seed_export / "dim_date.csv")[1]}
    for r in _read(seed_export / "fct_po_line_status.csv")[1]:
        assert r["first_confirmed_dt"] in dates
    for r in _read(seed_export / "fct_lead_time.csv")[1]:
        assert r["quarter_start"] in dates


def test_committed_export_is_what_the_current_code_produces(seed_export):
    committed = PROJECT_ROOT / "powerbi" / "data"
    for table in STAR:
        assert (committed / f"{table}.csv").read_bytes() == (
            seed_export / f"{table}.csv"
        ).read_bytes()
