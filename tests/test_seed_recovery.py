"""The analysis recovers the behaviours injected into the seeded data."""

from __future__ import annotations

import pytest

from promisedrift.analysis import bridge_counts, scorecard
from promisedrift.engine import build_database
from promisedrift.generator import generate, write_tables
from promisedrift.metrics import quarter_values

REPROMISERS = {"SUP-07", "SUP-19", "SUP-28"}


@pytest.fixture(scope="module")
def rows(seed_con):
    return {r["supplier_id"]: r for r in scorecard(seed_con)}


def _top3_d1_bottom5_d3(rows) -> tuple[set[str], set[str]]:
    by_d1 = sorted(rows.values(), key=lambda r: r["d1_rank"])
    by_d3 = sorted(rows.values(), key=lambda r: -r["d3_rank"])
    return {r["supplier_id"] for r in by_d1[:3]}, {r["supplier_id"] for r in by_d3[:5]}


def test_repromisers_are_top_three_by_headline_and_bottom_five_by_first_confirmed(rows):
    top3, bottom5 = _top3_d1_bottom5_d3(rows)
    assert top3 == REPROMISERS
    assert REPROMISERS <= bottom5


def test_repromisers_headline_and_first_confirmed_levels(rows):
    for sid in REPROMISERS:
        assert rows[sid]["d1"] >= 0.94
        assert rows[sid]["d3"] <= 0.66


def test_repromisers_gap_is_mostly_repromise(seed_con, rows):
    for sid in REPROMISERS:
        assert rows[sid]["gap_pp"] >= 25.0
        c = bridge_counts(seed_con, sid)
        total = c["d3_pass"] - c["d1_pass"]
        assert c["repromise"] / total >= 0.80


def test_partial_supplier_bridge_is_mostly_partial_shipment(seed_con):
    c = bridge_counts(seed_con, "SUP-12")
    assert c["partial"] / (c["d3_pass"] - c["d1_pass"]) >= 0.70


def test_early_supplier_bridge_is_mostly_early_arrival(seed_con):
    c = bridge_counts(seed_con, "SUP-23")
    assert c["early"] / (c["d3_pass"] - c["d1_pass"]) >= 0.70


def test_bridge_identity_holds_exactly_for_every_supplier_and_overall(seed_con):
    suppliers = [r[0] for r in seed_con.execute("SELECT supplier_id FROM suppliers").fetchall()]
    for sid in [None, *suppliers]:
        c = bridge_counts(seed_con, sid)
        assert (
            c["early"] + c["repromise"] + c["partial"] + c["other"] == c["d3_pass"] - c["d1_pass"]
        )
        assert c["other"] == 0


def test_resin_supplier_lead_time_steps_while_quote_stays_flat(seed_con):
    p90 = quarter_values(seed_con, "Lead Time P90 Days")
    quarters = sorted(q for sid, q in p90 if sid == "SUP-03")
    assert quarters == ["2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]
    before = [p90[("SUP-03", q)] for q in quarters[:3]]
    after = [p90[("SUP-03", q)] for q in quarters[3:]]
    assert max(before) <= 18
    assert min(after) >= 25
    quoted = seed_con.execute(
        "SELECT DISTINCT quoted_lead_days FROM lead_time_quarter WHERE supplier_id = 'SUP-03'"
    ).fetchall()
    assert quoted == [(14,)]


def test_lead_time_step_shows_in_requested_definition_not_first_confirmed(seed_con, rows):
    # SUP-03 confirms the longer date, so D3 stays near its peers while D4 collapses.
    assert rows["SUP-03"]["d3"] >= 0.75
    assert rows["SUP-03"]["d4"] <= 0.45


@pytest.mark.parametrize("seed", [1, 3])
def test_findings_hold_on_other_seeds(tmp_path, seed):
    tables, _ = generate(seed)
    write_tables(tmp_path, tables)
    rows = {r["supplier_id"]: r for r in scorecard(build_database(tmp_path))}
    top3, bottom5 = _top3_d1_bottom5_d3(rows)
    assert top3 == REPROMISERS
    assert REPROMISERS <= bottom5
