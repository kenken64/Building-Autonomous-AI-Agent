"""Deterministic shipping-date simulation for the AgentMart Fulfillment/Shipping agents.

Dates are *computed here*, never written by a model. Every agent prompt in this lab
forbids inventing a delivery date, and the only way to hold that line is to hand the
agent real dates and let it explain them.

The simulation is deliberately simple and reproducible: an order placed on a known
date, shipped from a known warehouse by a known method, lands a known number of
working days later. Same inputs, same answer, every run — so a scenario suite can
assert on it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

# Dispatch happens same-day before the cut-off, next working day after it.
DISPATCH_CUTOFF_HOUR = 15

# Warehouses observe different non-working days. Kept as data so a workshop can edit
# it and watch the estimates move.
WEEKEND_BY_WAREHOUSE: dict[str, tuple[int, ...]] = {
    "SG-CENTRAL": (6,),          # Sunday only
    "MY-JB": (5, 6),             # Saturday + Sunday
    "US-WEST": (5, 6),
}
DEFAULT_WEEKEND = (5, 6)

# A fixed holiday table beats a real calendar here: the workshop needs the same
# answer in every room, on every machine, in any year it is run.
HOLIDAYS_BY_WAREHOUSE: dict[str, tuple[str, ...]] = {
    "SG-CENTRAL": ("01-01", "05-01", "08-09", "12-25"),
    "MY-JB": ("01-01", "05-01", "08-31", "12-25"),
    "US-WEST": ("01-01", "07-04", "11-28", "12-25"),
}

# Same-day and locker methods never carry a tracking number in this lab.
UNTRACKED_METHODS = frozenset({"locker_pickup", "same_day_courier"})


def _weekend(warehouse: str) -> tuple[int, ...]:
    return WEEKEND_BY_WAREHOUSE.get(warehouse, DEFAULT_WEEKEND)


def _is_working_day(day: date, warehouse: str) -> bool:
    if day.weekday() in _weekend(warehouse):
        return False
    return day.strftime("%m-%d") not in HOLIDAYS_BY_WAREHOUSE.get(warehouse, ())


def next_working_day(day: date, warehouse: str) -> date:
    while not _is_working_day(day, warehouse):
        day += timedelta(days=1)
    return day


def add_working_days(start: date, days: int, warehouse: str) -> date:
    """Advance `days` working days from `start`, skipping the warehouse's closures."""
    day = next_working_day(start, warehouse)
    for _ in range(max(0, days)):
        day = next_working_day(day + timedelta(days=1), warehouse)
    return day


def simulate_shipping(
    warehouse: str,
    method: str,
    eta_days: int,
    placed_at: str | datetime | None = None,
) -> dict[str, Any]:
    """Concrete dispatch and delivery dates for one fulfillment option.

    Returns the dates plus the reasoning behind them, so an agent can explain the
    estimate instead of asserting it.
    """
    if placed_at is None:
        moment = datetime.now()
    elif isinstance(placed_at, datetime):
        moment = placed_at
    else:
        cleaned = str(placed_at).replace("Z", "+00:00")
        try:
            moment = datetime.fromisoformat(cleaned)
        except ValueError:
            moment = datetime.combine(date.fromisoformat(str(placed_at)[:10]), datetime.min.time())
    moment = moment.replace(tzinfo=None)

    after_cutoff = moment.hour >= DISPATCH_CUTOFF_HOUR
    dispatch_from = moment.date() + timedelta(days=1 if after_cutoff else 0)
    dispatch = next_working_day(dispatch_from, warehouse)
    delivery = add_working_days(dispatch, int(eta_days), warehouse)

    notes = []
    if after_cutoff:
        notes.append(f"placed after the {DISPATCH_CUTOFF_HOUR}:00 cut-off, so dispatch moves to the next working day")
    if dispatch != dispatch_from:
        notes.append(f"{dispatch_from.isoformat()} is not a working day at {warehouse}")
    if int(eta_days) == 0:
        notes.append("same-day method: dispatch and delivery are the same day")

    return {
        "warehouse": warehouse,
        "method": method,
        "eta_days": int(eta_days),
        "placed_at": moment.isoformat(timespec="minutes"),
        "dispatch_date": dispatch.isoformat(),
        "delivery_date": delivery.isoformat(),
        "calendar_days": (delivery - moment.date()).days,
        "tracked": method not in UNTRACKED_METHODS,
        "notes": notes,
        "simulated": True,
    }


def simulate_options(
    options: list[dict[str, Any]],
    placed_at: str | datetime | None = None,
) -> list[dict[str, Any]]:
    """Run `simulate_shipping` across every fulfillment option, soonest first."""
    out = [
        simulate_shipping(o["warehouse"], o["method"], o.get("eta_days", 0), placed_at)
        | {"cost_usd": float(o.get("cost_usd", 0.0))}
        for o in options
    ]
    return sorted(out, key=lambda r: (r["delivery_date"], r["cost_usd"]))


def format_estimates(rows: list[dict[str, Any]]) -> str:
    """Render estimates for an agent prompt: facts only, one line each."""
    if not rows:
        return "(no fulfillment options available)"
    lines = []
    for r in rows:
        track = "tracked" if r["tracked"] else "no tracking"
        lines.append(
            f"{r['warehouse']} {r['method']}: dispatch {r['dispatch_date']}, "
            f"delivery {r['delivery_date']} ({r['calendar_days']} calendar days), "
            f"${r['cost_usd']:.2f}, {track}"
            + (f" — {'; '.join(r['notes'])}" if r["notes"] else "")
        )
    return "\n".join(lines)
