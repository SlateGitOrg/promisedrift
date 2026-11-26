"""Seeded synthetic purchase-order data with injected supplier behaviours.

The data models a tier-1 interior-systems manufacturer buying from 35 tier-2 suppliers over 18
months. Four tables come out: suppliers, po_lines, promise_changes and receipts, plus a truth
record of what was injected so tests can check the analysis recovers it.

Baseline suppliers deliver in the -3/+0 day window with probability 78-93%, arrive late by 1-12
days otherwise, confirm a later date than requested on 10-30% of lines, ship partials on 8% of
lines and push their promise out by 1-3 days as a buffer on a share of lines they then deliver on
the original date. A few percent of on-time lines carry a pull-in (the promise moved earlier, the
delivery did not).

Injected on top of that:

* SUP-07, SUP-19, SUP-28 re-promise almost every late line 1-4 days before it is due, to the real
  ship date, so the ERP headline stays high while delivery against the first confirmation is poor.
* SUP-12 ships 85-92% of the quantity on the date and the balance 6-10 days later on 40% of lines.
* SUP-23 delivers 4-9 days early on 35% of lines.
* SUP-03 (resin) needs about 28 days from April 2025 onward (month 10) while its quoted lead time
  stays 14. It confirms the longer date, so it still scores well against its own confirmation;
  only the lead-time view and the requested-date definition show the step.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

START = date(2024, 7, 1)
END = date(2025, 12, 31)
STEP_DATE = date(2025, 4, 1)
STEP_LEAD_DAYS = 28
TOTAL_LINES = 9000
DEFAULT_SEED = 7

RAW_COLUMNS: dict[str, list[str]] = {
    "suppliers": ["supplier_id", "supplier_name", "commodity", "quoted_lead_days"],
    "po_lines": [
        "po_line_id",
        "supplier_id",
        "order_dt",
        "requested_dt",
        "first_confirmed_dt",
        "ordered_qty",
    ],
    "promise_changes": [
        "po_line_id",
        "change_seq",
        "change_dt",
        "old_promise_dt",
        "new_promise_dt",
    ],
    "receipts": ["receipt_id", "po_line_id", "receipt_dt", "qty_received"],
}

# (commodity, supplier count, quoted lead-time range in days, name suffix)
COMMODITIES = [
    ("resin", 6, (10, 21), "Polymers"),
    ("fasteners", 7, (14, 28), "Fasteners"),
    ("fabric", 6, (21, 35), "Textiles"),
    ("foam", 5, (10, 21), "Foam Products"),
    ("stampings", 6, (28, 45), "Metal Stampings"),
    ("electronics", 5, (30, 45), "Electronics"),
]

NAME_STEMS = [
    "Altair", "Brennick", "Calloway", "Dunmore", "Elmcrest", "Farrow", "Garnet", "Halden",
    "Ironvale", "Juniper", "Kestrel", "Larchmont", "Marlowe", "Northgate", "Oakhurst", "Pennant",
    "Quillon", "Ridgeway", "Stanmore", "Tolliver", "Underhill", "Vantage", "Westerly", "Yarrow",
    "Zephyr", "Ashgrove", "Bramley", "Cobalt", "Denholm", "Eastvale", "Fairmont", "Glenrock",
    "Hartwell", "Kingsley", "Lyndhurst",
]  # fmt: skip

WINDOW_OFFSETS = [-3, -2, -1, 0]
WINDOW_WEIGHTS = [0.10, 0.15, 0.25, 0.50]


@dataclass(frozen=True)
class Profile:
    """Behaviour of one supplier. Probabilities are per PO line."""

    supplier_id: str
    name: str
    commodity: str
    quoted_lead_days: int
    n_lines: int
    p_ontime: float
    p_confirm_later: float
    p_partial: float
    p_short_close: float = 0.015
    p_sandbag: float = 0.0
    p_pull_in: float = 0.0
    p_repromise_late: float = 0.10
    p_early: float = 0.0
    late_days: tuple[int, int] = (1, 12)
    confirm_days: tuple[int, int] = (1, 6)
    partial_fraction: tuple[float, float] = (0.60, 0.95)
    balance_gap_days: tuple[int, int] = (3, 12)
    partial_on_date: bool = False
    lead_step: bool = False


@dataclass
class _Line:
    supplier_id: str
    order_dt: date
    requested_dt: date
    first_confirmed_dt: date
    ordered_qty: int
    changes: list[tuple[date, date]]  # (change date, new promise date) in log order
    receipts: list[tuple[date, int]]


Tables = dict[str, list[dict[str, Any]]]


def _ri(rng: np.random.Generator, lo: int, hi: int) -> int:
    """Uniform integer in [lo, hi], both ends included."""
    return int(rng.integers(lo, hi + 1))


def _day(d: date, n: int) -> date:
    return d + timedelta(days=n)


def build_profiles(rng: np.random.Generator) -> list[Profile]:
    """Draw one profile per supplier, then apply the injected behaviours by supplier id."""
    weights = rng.uniform(0.7, 1.4, size=35)
    counts = np.round(TOTAL_LINES * weights / weights.sum()).astype(int)
    counts[-1] += TOTAL_LINES - int(counts.sum())

    profiles: list[Profile] = []
    n = 0
    for commodity, how_many, (lo, hi), suffix in COMMODITIES:
        for _ in range(how_many):
            sid = f"SUP-{n + 1:02d}"
            profiles.append(
                Profile(
                    supplier_id=sid,
                    name=f"{NAME_STEMS[n]} {suffix}",
                    commodity=commodity,
                    quoted_lead_days=_ri(rng, lo, hi),
                    n_lines=int(counts[n]),
                    p_ontime=float(rng.uniform(0.78, 0.93)),
                    p_confirm_later=float(rng.uniform(0.10, 0.30)),
                    p_partial=0.13,
                    p_sandbag=float(rng.uniform(0.18, 0.31)),
                    p_pull_in=0.02,
                )
            )
            n += 1

    by_id = {p.supplier_id: p for p in profiles}

    def override(sid: str, **changes: Any) -> None:
        by_id[sid] = replace(by_id[sid], **changes)

    for sid, p_ontime in (("SUP-07", 0.57), ("SUP-19", 0.54), ("SUP-28", 0.60)):
        override(
            sid,
            p_ontime=p_ontime,
            p_repromise_late=0.97,
            p_partial=0.04,
            p_sandbag=0.0,
            p_pull_in=0.0,
            late_days=(1, 14),
        )
    override(
        "SUP-12",
        p_ontime=0.85,
        p_partial=0.40,
        partial_fraction=(0.85, 0.92),
        balance_gap_days=(6, 10),
        partial_on_date=True,
    )
    override("SUP-23", p_ontime=0.82, p_early=0.35)
    override(
        "SUP-03",
        quoted_lead_days=14,
        p_ontime=0.92,
        p_confirm_later=0.05,
        confirm_days=(1, 2),
        late_days=(1, 3),
        lead_step=True,
    )
    return [by_id[p.supplier_id] for p in profiles]


def _simulate_line(rng: np.random.Generator, p: Profile, order_dt: date) -> _Line:
    stepped = p.lead_step and order_dt >= STEP_DATE
    requested = _day(order_dt, p.quoted_lead_days)
    first_confirmed = _day(order_dt, STEP_LEAD_DAYS) if stepped else requested
    if rng.random() < p.p_confirm_later:
        first_confirmed = _day(first_confirmed, _ri(rng, *p.confirm_days))
    qty = _ri(rng, 50, 5000)

    partial = rng.random() < p.p_partial
    short = (not partial) and rng.random() < p.p_short_close

    # Delivery offset against the first confirmed date.
    if rng.random() < p.p_early:
        kind, offset = "early", -_ri(rng, 4, 9)
    elif partial and p.partial_on_date:
        kind, offset = "ontime", 0
    elif rng.random() < p.p_ontime:
        kind = "ontime"
        offset = int(rng.choice(WINDOW_OFFSETS, p=WINDOW_WEIGHTS))
    else:
        kind, offset = "late", _ri(rng, *p.late_days)

    changes: list[tuple[date, date]] = []
    if kind == "ontime":
        if rng.random() < p.p_pull_in:
            # Promised earlier, delivered on the original date: headline fails, D3 passes.
            offset = 0
            changes.append(
                (_day(first_confirmed, -_ri(rng, 10, 20)), _day(first_confirmed, -_ri(rng, 1, 5)))
            )
        elif rng.random() < p.p_sandbag:
            # A buffer: promise pushed out by 1-3 days, delivery still on the original date.
            k1 = _ri(rng, 1, 3)
            changes.append((_day(first_confirmed, -_ri(rng, 5, 15)), _day(first_confirmed, k1)))
            if k1 < 3 and rng.random() < 0.10:
                extra = _ri(rng, 1, 3 - k1)
                changes.append(
                    (_day(first_confirmed, -_ri(rng, 1, 4)), _day(first_confirmed, k1 + extra))
                )
    elif kind == "late" and rng.random() < p.p_repromise_late:
        # Re-promise to the date the shipment will really arrive, shortly before the due date.
        real = _day(first_confirmed, offset)
        notice = _day(first_confirmed, -_ri(rng, 1, 4))
        if offset >= 2 and rng.random() < 0.25:
            mid = _day(first_confirmed, _ri(rng, 1, offset - 1))
            changes.append((notice, mid))
            changes.append((_day(mid, -1), real))
        else:
            changes.append((notice, real))

    # A promise cannot change before the PO exists; clamping keeps the log in date order.
    floor = _day(order_dt, 1)
    changes = [(max(change_dt, floor), new) for change_dt, new in changes]

    first_receipt = _day(first_confirmed, offset)
    if short:
        receipts = [(first_receipt, max(1, round(qty * float(rng.uniform(0.85, 0.96)))))]
    elif partial:
        first_qty = max(1, round(qty * float(rng.uniform(*p.partial_fraction))))
        balance = qty - first_qty
        gap = _ri(rng, *p.balance_gap_days)
        if not p.partial_on_date and balance >= 2 and rng.random() < 0.35:
            part = _ri(rng, 1, balance - 1)
            receipts = [
                (first_receipt, first_qty),
                (_day(first_receipt, gap), part),
                (_day(first_receipt, gap + _ri(rng, 2, 6)), balance - part),
            ]
        else:
            receipts = [(first_receipt, first_qty), (_day(first_receipt, gap), balance)]
    else:
        receipts = [(first_receipt, qty)]

    return _Line(p.supplier_id, order_dt, requested, first_confirmed, qty, changes, receipts)


def generate(seed: int = DEFAULT_SEED) -> tuple[Tables, dict[str, Any]]:
    """Return the four raw tables and a truth record of the injected behaviours."""
    rng = np.random.default_rng(seed)
    profiles = build_profiles(rng)
    span = (END - START).days

    lines: list[_Line] = []
    for p in profiles:
        for _ in range(p.n_lines):
            lines.append(_simulate_line(rng, p, _day(START, _ri(rng, 0, span))))
    lines.sort(key=lambda ln: (ln.order_dt, ln.supplier_id, ln.requested_dt, ln.ordered_qty))

    tables: Tables = {name: [] for name in RAW_COLUMNS}
    for p in profiles:
        tables["suppliers"].append(
            {
                "supplier_id": p.supplier_id,
                "supplier_name": p.name,
                "commodity": p.commodity,
                "quoted_lead_days": p.quoted_lead_days,
            }
        )
    receipt_rows: list[tuple[date, str, int]] = []
    for i, ln in enumerate(lines, start=1):
        line_id = f"POL-{i:05d}"
        tables["po_lines"].append(
            {
                "po_line_id": line_id,
                "supplier_id": ln.supplier_id,
                "order_dt": ln.order_dt,
                "requested_dt": ln.requested_dt,
                "first_confirmed_dt": ln.first_confirmed_dt,
                "ordered_qty": ln.ordered_qty,
            }
        )
        old = ln.first_confirmed_dt
        for seq, (change_dt, new_dt) in enumerate(ln.changes, start=1):
            tables["promise_changes"].append(
                {
                    "po_line_id": line_id,
                    "change_seq": seq,
                    "change_dt": change_dt,
                    "old_promise_dt": old,
                    "new_promise_dt": new_dt,
                }
            )
            old = new_dt
        receipt_rows.extend((rdt, line_id, rqty) for rdt, rqty in ln.receipts)
    receipt_rows.sort()
    for j, (rdt, line_id, rqty) in enumerate(receipt_rows, start=1):
        tables["receipts"].append(
            {
                "receipt_id": f"RCV-{j:05d}",
                "po_line_id": line_id,
                "receipt_dt": rdt,
                "qty_received": rqty,
            }
        )

    truth = {
        "seed": seed,
        "period": [START.isoformat(), END.isoformat()],
        "repromise_suppliers": ["SUP-07", "SUP-19", "SUP-28"],
        "partial_balance_supplier": "SUP-12",
        "early_supplier": "SUP-23",
        "lead_time_step": {
            "supplier": "SUP-03",
            "from_order_date": STEP_DATE.isoformat(),
            "quoted_lead_days": 14,
            "actual_lead_days_after": STEP_LEAD_DAYS,
        },
    }
    return tables, truth


def write_tables(out_dir: Path, tables: Tables) -> None:
    """Write raw tables as CSV files named after the tables."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, columns in RAW_COLUMNS.items():
        with (out_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            for row in tables[name]:
                writer.writerow(
                    {k: v.isoformat() if isinstance(v, date) else v for k, v in row.items()}
                )
