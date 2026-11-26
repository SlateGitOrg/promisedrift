"""OTIF definitions and the D1 -> D3 bridge on hand-computed fixtures."""

from __future__ import annotations

import pytest

from helpers import build_fixture, day, line, ten_line_fixture
from promisedrift.analysis import bridge_counts, overall, scorecard


@pytest.fixture
def ten(tmp_path):
    return build_fixture(tmp_path, ten_line_fixture())


def test_ten_line_fixture_otif_by_definition(ten):
    result = overall(ten)
    assert result["lines"] == 10
    assert result["d1"] == pytest.approx(0.90)
    assert result["d2"] == pytest.approx(0.70)
    assert result["d3"] == pytest.approx(0.50)
    assert result["d4"] == pytest.approx(0.40)


def test_ten_line_fixture_bridge_components(ten):
    result = overall(ten)
    assert result["early_pp"] == pytest.approx(-10.0)
    assert result["repromise_pp"] == pytest.approx(-20.0)
    assert result["partial_pp"] == pytest.approx(-10.0)
    assert result["other_pp"] == 0.0


def test_ten_line_fixture_each_line_gets_its_own_cause(ten):
    causes = dict(ten.execute("SELECT po_line_id, cause FROM line_bridge").fetchall())
    assert causes["L06"] == "early"
    assert causes["L07"] == causes["L08"] == "repromise"
    assert causes["L09"] == "partial"
    assert [causes[f"L{i:02d}"] for i in (1, 2, 3, 4, 5, 10)] == [None] * 6


def test_bridge_identity_overall_and_per_supplier(ten):
    for supplier in (None, "SUP-A", "SUP-B"):
        c = bridge_counts(ten, supplier)
        assert (
            c["early"] + c["repromise"] + c["partial"] + c["other"] == c["d3_pass"] - c["d1_pass"]
        )
    b = bridge_counts(ten, "SUP-B")
    assert (b["d1_pass"], b["d3_pass"]) == (4, 0)
    assert (b["early"], b["repromise"], b["partial"]) == (-1, -2, -1)


def test_scorecard_ranks_and_gap_on_fixture(ten):
    rows = {r["supplier_id"]: r for r in scorecard(ten)}
    assert rows["SUP-A"]["d1"] == 1.0 and rows["SUP-A"]["d1_rank"] == 1
    assert rows["SUP-B"]["d3"] == 0.0 and rows["SUP-B"]["d3_rank"] == 2
    assert rows["SUP-B"]["gap_pp"] == pytest.approx(80.0)
    total = rows["SUP-B"]["early_pp"] + rows["SUP-B"]["repromise_pp"] + rows["SUP-B"]["partial_pp"]
    assert total == pytest.approx(-80.0)


@pytest.mark.parametrize(
    ("receipt_offset", "expected"),
    [(-4, 0), (-3, 1), (0, 1), (1, 0)],
)
def test_window_edges_for_first_confirmed(tmp_path, receipt_offset, expected):
    con = build_fixture(tmp_path, [line("L1", [(day(receipt_offset), 100)])])
    assert con.execute("SELECT d3_otif FROM line_otif").fetchone()[0] == expected


@pytest.mark.parametrize(("received", "expected"), [(98, 1), (97, 0), (100, 1)])
def test_quantity_threshold_is_exactly_98_percent(tmp_path, received, expected):
    con = build_fixture(tmp_path, [line("L1", [(day(0), received)])])
    row = con.execute("SELECT d1_otif, d3_otif FROM line_otif").fetchone()
    assert row == (expected, expected)


def test_early_arrival_passes_headline_but_fails_windowed_definitions(tmp_path):
    con = build_fixture(tmp_path, [line("L1", [(day(-6), 100)])])
    assert con.execute("SELECT d1_otif, d2_otif, d3_otif, d4_otif FROM line_otif").fetchone() == (
        1,
        0,
        0,
        0,
    )


def test_pull_in_counts_positive_and_is_attributed_to_repromise(tmp_path):
    # Promise pulled in to day -5, delivered on the original date: D1 fails, D3 passes.
    pulled = line("L1", [(day(0), 100)], changes=[(1, day(-12), day(-5))])
    con = build_fixture(tmp_path, [pulled])
    assert con.execute("SELECT d1_otif, d3_otif FROM line_otif").fetchone() == (0, 1)
    assert con.execute("SELECT delta, cause, bridge_repromise FROM line_bridge").fetchone() == (
        1,
        "repromise",
        1,
    )
    assert overall(con)["repromise_pp"] == pytest.approx(100.0)


def test_line_with_no_receipt_fails_every_definition_and_has_no_bridge_entry(tmp_path):
    con = build_fixture(tmp_path, [line("L1", [])])
    assert con.execute("SELECT d1_otif, d2_otif, d3_otif, d4_otif FROM line_otif").fetchone() == (
        0,
        0,
        0,
        0,
    )
    assert con.execute("SELECT cause FROM line_bridge").fetchone() == (None,)


def test_re_promised_and_early_line_is_attributed_to_early_first(tmp_path):
    # Promise pushed to day 9 but the goods arrive on day -5: early wins over re-promise.
    both = line("L1", [(day(-5), 100)], changes=[(1, day(-8), day(9))])
    con = build_fixture(tmp_path, [both])
    assert con.execute("SELECT cause FROM line_bridge").fetchone() == ("early",)
