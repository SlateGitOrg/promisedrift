"""The seeded generator: determinism, volumes and structural invariants."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date

from promisedrift.generator import END, START, generate, write_tables


def _digest(tables) -> str:
    h = hashlib.sha256()
    for name in sorted(tables):
        for row in tables[name]:
            h.update(repr(sorted(row.items())).encode())
    return h.hexdigest()


def test_same_seed_gives_identical_data_and_other_seeds_differ():
    assert _digest(generate(7)[0]) == _digest(generate(7)[0])
    assert _digest(generate(7)[0]) != _digest(generate(8)[0])


def test_volumes_match_the_stated_profile(seed_data):
    tables, _ = seed_data
    suppliers = tables["suppliers"]
    assert len(suppliers) == 35
    assert Counter(s["commodity"] for s in suppliers) == {
        "resin": 6,
        "fasteners": 7,
        "fabric": 6,
        "foam": 5,
        "stampings": 6,
        "electronics": 5,
    }
    assert len(tables["po_lines"]) == 9000
    assert 2300 <= len(tables["promise_changes"]) <= 2700
    assert 10000 <= len(tables["receipts"]) <= 11000
    assert all(10 <= s["quoted_lead_days"] <= 45 for s in suppliers)


def test_orders_span_eighteen_months(seed_data):
    orders = [row["order_dt"] for row in seed_data[0]["po_lines"]]
    assert START <= min(orders) <= date(2024, 7, 10)
    assert date(2025, 12, 20) <= max(orders) <= END


def test_receipts_never_exceed_the_order_and_follow_it(seed_data):
    tables, _ = seed_data
    lines = {row["po_line_id"]: row for row in tables["po_lines"]}
    received = Counter()
    for r in tables["receipts"]:
        received[r["po_line_id"]] += r["qty_received"]
        assert r["receipt_dt"] > lines[r["po_line_id"]]["order_dt"]
    assert set(received) == set(lines)
    assert all(received[k] <= lines[k]["ordered_qty"] for k in lines)


def test_promise_log_is_a_consistent_chain(seed_data):
    tables, _ = seed_data
    lines = {row["po_line_id"]: row for row in tables["po_lines"]}
    previous: dict[str, tuple[int, date, date]] = {}
    for change in tables["promise_changes"]:
        key = change["po_line_id"]
        if key in previous:
            seq, last_change, last_new = previous[key]
            assert change["change_seq"] == seq + 1
            assert change["old_promise_dt"] == last_new
            assert change["change_dt"] >= last_change
        else:
            assert change["change_seq"] == 1
            assert change["old_promise_dt"] == lines[key]["first_confirmed_dt"]
        previous[key] = (change["change_seq"], change["change_dt"], change["new_promise_dt"])


def test_write_tables_round_trips_row_counts(tmp_path, seed_data):
    write_tables(tmp_path, seed_data[0])
    for name, rows in seed_data[0].items():
        with (tmp_path / f"{name}.csv").open() as fh:
            assert sum(1 for _ in fh) == len(rows) + 1


def test_truth_record_names_the_injected_suppliers(seed_data):
    truth = seed_data[1]
    assert truth["repromise_suppliers"] == ["SUP-07", "SUP-19", "SUP-28"]
    assert truth["lead_time_step"]["supplier"] == "SUP-03"


def test_no_promise_change_precedes_its_order(seed_data):
    tables, _ = seed_data
    ordered = {row["po_line_id"]: row["order_dt"] for row in tables["po_lines"]}
    early = [c for c in tables["promise_changes"] if c["change_dt"] <= ordered[c["po_line_id"]]]
    assert early == []
    assert tables["promise_changes"]


def test_clamping_holds_on_other_seeds():
    for seed in (1, 3):
        tables, _ = generate(seed)
        ordered = {row["po_line_id"]: row["order_dt"] for row in tables["po_lines"]}
        assert all(c["change_dt"] > ordered[c["po_line_id"]] for c in tables["promise_changes"])
