"""line_status, promise_drift and lead_time SQL on small known inputs."""

from __future__ import annotations

from datetime import date

from helpers import build_fixture, day, line


def test_latest_promise_follows_change_seq_not_row_order(tmp_path):
    ln = line(
        "L1",
        [(day(9), 100)],
        changes=[(2, day(1), day(9)), (1, day(-3), day(5))],  # seq 2 is written first
    )
    con = build_fixture(tmp_path, [ln])
    row = con.execute("SELECT latest_promise_dt, n_repromise FROM line_status").fetchone()
    assert row == (day(9), 2)


def test_latest_promise_defaults_to_first_confirmed(tmp_path):
    con = build_fixture(tmp_path, [line("L1", [(day(0), 100)], confirmed=day(3))])
    assert con.execute("SELECT latest_promise_dt, n_repromise FROM line_status").fetchone() == (
        day(3),
        0,
    )


def test_quantity_by_each_basis_date(tmp_path):
    # requested day 0, confirmed day 2, latest promise day 5; receipts on days 1, 4 and 8.
    ln = line(
        "L1",
        [(day(1), 30), (day(4), 50), (day(8), 20)],
        confirmed=day(2),
        changes=[(1, day(0), day(5))],
    )
    con = build_fixture(tmp_path, [ln])
    row = con.execute(
        "SELECT first_receipt_dt, last_receipt_dt, n_receipts, qty_by_requested, "
        "qty_by_first_confirmed, qty_by_latest_promise, qty_eventual FROM line_status"
    ).fetchone()
    assert row == (day(1), day(8), 3, 0, 30, 80, 100)


def test_promise_drift_is_signed_days_and_count(tmp_path):
    pushed = line("L1", [(day(6), 100)], changes=[(1, day(-2), day(4)), (2, day(2), day(6))])
    pulled = line("L2", [(day(0), 100)], changes=[(1, day(-9), day(-4))])
    steady = line("L3", [(day(0), 100)])
    con = build_fixture(tmp_path, [pushed, pulled, steady])
    rows = {r[0]: r[1:] for r in con.execute("SELECT * FROM promise_drift").fetchall()}
    assert rows["L1"] == ("SUP-A", 2, 6)
    assert rows["L2"] == ("SUP-A", 1, -4)
    assert rows["L3"] == ("SUP-A", 0, 0)


def test_lead_time_percentiles_per_supplier_quarter(tmp_path):
    # Eleven lines ordered in 2025-Q1 with actual lead times 1..11 days, quoted 7.
    lines = [
        line(
            f"L{i:02d}",
            [(date(2025, 2, 1 + i), 100)],
            order=date(2025, 2, 1),
            requested=date(2025, 2, 8),
        )
        for i in range(1, 12)
    ]
    lines.append(line("M01", [(date(2025, 5, 20), 100)], order=date(2025, 5, 1)))
    con = build_fixture(tmp_path, lines, quoted={"SUP-A": 7})
    rows = con.execute(
        "SELECT quarter_label, quarter_start, lines, quoted_lead_days, actual_p50_days, "
        "actual_p90_days FROM lead_time_quarter ORDER BY quarter_start"
    ).fetchall()
    assert rows[0] == ("2025-Q1", date(2025, 1, 1), 11, 7, 6.0, 10.0)
    assert rows[1] == ("2025-Q2", date(2025, 4, 1), 1, 7, 19.0, 19.0)
